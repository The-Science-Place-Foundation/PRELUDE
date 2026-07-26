# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""LAN-only server for the listening companion.

Deliberately small: standard library only, no framework, no database, no auth.
It runs on a home network for a single listener, and every dependency it does
not have is one that cannot break at 10pm mid-session.

**The fitter runs here, not in the browser.** The adaptive fitting logic is
already written and tested in Python; reimplementing it in JavaScript would mean
maintaining two versions of the one component whose correctness decides whether
the collected judgements mean anything. The page presents trials and reports
choices; this process decides what to ask next.

**Session data is written here, not kept on the phone.** Safari caps
script-writable storage and can evict it after a period of disuse, which would
silently lose weeks of judgements. The phone keeps a local copy as a safety net;
this server is the record.

Not exposed to the internet. No authentication, because a login screen on
something opened while tired at the end of a day would cost more than it
protects on a single-user LAN.
"""

from __future__ import annotations

import itertools
import json
import math
import mimetypes
import os
import random
import re
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(os.environ.get("PRELUDE_APP", "/app/static"))
AUDIO_DIR = Path(os.environ.get("PRELUDE_AUDIO", "/data/audio"))
SESSION_DIR = Path(os.environ.get("PRELUDE_SESSIONS", "/data/sessions"))
PORT = int(os.environ.get("PRELUDE_PORT", "8080"))

#: Hard ceiling on trials per session. Mirrors the fatigue limit in
#: prelude.study.session - fatigued discrimination data cannot be told apart
#: from a null result, so an over-long session produces misleading numbers
#: rather than merely wasted ones.
MAX_TRIALS = 40

SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

#: Discrimination sharpness in the choice model. Higher means judgements are
#: treated as more reliable. Calibrate from catch-trial performance: a listener
#: answering identical pairs at chance is discriminating on the real trials and
#: supports a higher value; a strong position bias means the opposite.
BETA = 6.0

_sessions: dict[str, dict] = {}
_pool: dict | None = None


def _load_pool() -> dict | None:
    """Candidate pool and its pairwise distance matrix, rendered offline.

    Doing the rendering and the distance computation ahead of time is what
    lets this server stay dependency-free: the fitting maths below is a few
    loops over a matrix, which needs no numerical library.
    """
    global _pool
    if _pool is None:
        f = AUDIO_DIR / "pool.json"
        if f.is_file():
            _pool = json.loads(f.read_text())
    return _pool


def _log_sigmoid(x: float) -> float:
    """log(1 / (1 + e^-x)), without overflowing on either tail."""
    return -math.log1p(math.exp(-x)) if x > -30 else x


def _posterior(sess: dict) -> list[float]:
    """Normalised posterior over which candidate the listener is hearing.

    Sequential Bayesian update. Presented with two candidates, a listener
    prefers whichever sounds closer to their own percept, so for a hypothesised
    truth t:

        P(choose A over B | t) = sigmoid(beta * [D(B,t) - D(A,t)])

    D is computable for any hypothesised t, so a choice can be scored without
    ever knowing the answer.
    """
    pool = _load_pool()
    if not pool:
        return []
    dist = pool["distances"]
    n = len(dist)
    logp = [0.0] * n

    for r in sess["responses"]:
        chosen, rejected = r.get("chose_idx"), r.get("rejected_idx")
        # "They feel the same" carries real information - it says the two are
        # near-equidistant from the listener's percept - but not as a preference,
        # so it updates nothing here rather than being forced into one.
        if chosen is None or rejected is None:
            continue
        for t in range(n):
            logp[t] += _log_sigmoid(BETA * (dist[rejected][t] - dist[chosen][t]))

    m = max(logp)
    w = [math.exp(v - m) for v in logp]
    total = sum(w)
    return [x / total for x in w] if total > 0 else [1.0 / n] * n


def _information_gain(a: int, b: int, post: list[float], dist: list[list[float]]) -> float:
    """Expected reduction in posterior entropy from asking about (a, b).

    Choosing the most informative comparison rather than a random one is what
    makes a short session worth sitting through - listening time is the binding
    constraint on the whole project.
    """
    la = [_log_sigmoid(BETA * (dist[b][t] - dist[a][t])) for t in range(len(post))]
    lb = [_log_sigmoid(BETA * (dist[a][t] - dist[b][t])) for t in range(len(post))]
    pa = sum(p * math.exp(v) for p, v in zip(post, la, strict=True))
    pb = sum(p * math.exp(v) for p, v in zip(post, lb, strict=True))
    tot = pa + pb
    if tot <= 0:
        return -1e9
    pa, pb = pa / tot, pb / tot

    def ent(ll):
        q = [p * math.exp(v) for p, v in zip(post, ll, strict=True)]
        s = sum(q)
        if s <= 0:
            return 0.0
        return -sum((x / s) * math.log(x / s) for x in q if x > 0)

    prior = -sum(p * math.log(p) for p in post if p > 0)
    return prior - (pa * ent(la) + pb * ent(lb))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stimuli() -> list[str]:
    """Available stimulus files, sorted for stable trial construction."""
    if not AUDIO_DIR.is_dir():
        return []
    return sorted(p.name for p in AUDIO_DIR.glob("*.wav"))


def _new_session(listener: str = "P01") -> dict:
    return {
        "session_id": uuid.uuid4().hex[:12],
        "listener": listener,
        "started_at": _now(),
        "trials": [],
        "responses": [],
        "catch_positions": set(),
    }


def _next_trial(sess: dict) -> dict | None:
    """Choose the next comparison by expected information gain."""
    n = len(sess["responses"])
    if n >= MAX_TRIALS:
        return None

    pool = _load_pool()
    if not pool or len(pool["candidates"]) < 2:
        return None

    cands = pool["candidates"]
    dist = pool["distances"]
    total = len(cands)
    rng = random.Random(f"{sess['session_id']}:{n}")

    # Catch trial: the same candidate on both sides, so there is no correct
    # answer. Any consistent preference measures response bias, which is the
    # floor every other result has to be read against. Position is jittered -
    # a fixed interval would let a listener learn to spot them.
    is_catch = n > 0 and rng.random() < 1.0 / 6.0
    if is_catch:
        a = b = rng.randrange(total)
    else:
        post = _posterior(sess)
        # Restrict to candidates still plausibly the answer, then pick the pair
        # that most reduces uncertainty.
        live = [i for i, p in enumerate(post) if p > max(post) * 1e-3] or list(range(total))
        if len(live) > 10:
            live = sorted(live, key=lambda i: -post[i])[:10]
        asked = {tuple(sorted((t["a_idx"], t["b_idx"]))) for t in sess["trials"]}
        best, best_gain = None, -1e9
        for i, j in itertools.combinations(live, 2):
            if tuple(sorted((i, j))) in asked:
                continue
            g = _information_gain(i, j, post, dist)
            if g > best_gain:
                best, best_gain = (i, j), g
        if best is None:
            order = sorted(range(total), key=lambda i: -post[i])
            best = (order[0], order[1])
        a, b = best

    order = [0, 1]
    rng.shuffle(order)
    trial = {
        "trial_id": uuid.uuid4().hex[:10],
        "index": n,
        "is_catch": is_catch,
        "a_idx": a, "b_idx": b,
        "options": [cands[a]["file"], cands[b]["file"]],
        "presentation_order": order,
        "remaining": MAX_TRIALS - n,
    }
    sess["trials"].append(trial)
    return trial


class Handler(BaseHTTPRequestHandler):
    server_version = "prelude"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
        # Quiet by default; request logs on a single-user LAN service are noise
        # and would record which stimuli were heard when.
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # No caching of API responses; audio is immutable and may be cached.
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json",
                   {"Cache-Control": "no-store"})

    def _file(self, path: Path, cache: str) -> None:
        if not path.is_file():
            self._json(404, {"error": f"not found: {path.name}"})
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype, {"Cache-Control": cache})

    # -------------------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802 - stdlib signature
        route = self.path.split("?")[0].rstrip("/") or "/"

        if route == "/health":
            self._json(200, {
                "ok": True, "time": _now(),
                "stimuli": len(_stimuli()),
                "candidates": len((_load_pool() or {}).get("candidates", [])),
                "sessions_on_disk": len(list(SESSION_DIR.glob("*.json")))
                if SESSION_DIR.is_dir() else 0,
            })
            return

        if route == "/api/session":
            sess = _new_session()
            _sessions[sess["session_id"]] = sess
            trial = _next_trial(sess)
            self._json(200, {
                "session_id": sess["session_id"],
                "max_trials": MAX_TRIALS,
                "trial": trial,
            })
            return

        if route.startswith("/audio/"):
            name = route[len("/audio/"):]
            if not SAFE_NAME.match(name):
                self._json(400, {"error": "bad filename"})
                return
            # Immutable: stimuli are regenerated under new names, never edited.
            self._file(AUDIO_DIR / name, "public, max-age=31536000, immutable")
            return

        # Static app. Unknown paths fall through to the shell so the PWA can
        # own its own routing.
        rel = route.lstrip("/") or "index.html"
        candidate = (APP_DIR / rel).resolve()
        if APP_DIR.resolve() in candidate.parents or candidate == APP_DIR.resolve():
            if candidate.is_file():
                self._file(candidate, "no-cache")
                return
        self._file(APP_DIR / "index.html", "no-cache")

    # ------------------------------------------------------------------- POST
    def do_POST(self):  # noqa: N802 - stdlib signature
        route = self.path.split("?")[0].rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            self._json(413, {"error": "payload too large"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "malformed JSON"})
            return

        if route == "/api/respond":
            sid = payload.get("session_id")
            sess = _sessions.get(sid)
            if not sess:
                self._json(404, {"error": "unknown session - start a new one"})
                return
            chose = payload.get("chose")               # 0, 1, or "same"
            trial = next((t for t in sess["trials"]
                          if t["trial_id"] == payload.get("trial_id")), None)
            rec = {
                "trial_id": payload.get("trial_id"),
                "chose": chose,
                "response_ms": payload.get("response_ms"),
                "at": _now(),
            }
            # Resolve the blinded choice back to candidate indices. The page is
            # never told which card is which; that mapping lives only here.
            if trial and isinstance(chose, int) and not trial["is_catch"]:
                shown = [trial["a_idx"], trial["b_idx"]]
                picked = shown[trial["presentation_order"][chose]]
                other = shown[trial["presentation_order"][1 - chose]]
                rec["chose_idx"], rec["rejected_idx"] = picked, other
            sess["responses"].append(rec)
            self._json(200, {"trial": _next_trial(sess)})
            return

        if route == "/api/finish":
            sid = payload.get("session_id")
            sess = _sessions.get(sid)
            if not sess:
                self._json(404, {"error": "unknown session"})
                return
            post = _posterior(sess)
            if post:
                top = max(range(len(post)), key=lambda i: post[i])
                pool = _load_pool()
                sess["fit"] = {
                    "best_candidate": pool["candidates"][top]["name"],
                    "probability": round(post[top], 4),
                    "converged": post[top] >= 0.80,
                    "posterior": [round(p, 4) for p in post],
                }
            sess["finished_at"] = _now()
            sess["notes"] = payload.get("notes", "")
            sess["ended_early"] = bool(payload.get("ended_early"))
            record = {k: v for k, v in sess.items() if k != "catch_positions"}

            try:
                SESSION_DIR.mkdir(parents=True, exist_ok=True)
                out = SESSION_DIR / f"{sess['started_at'][:10]}-{sess['session_id']}.json"
                out.write_text(json.dumps(record, indent=2))
                self._json(200, {"saved": out.name,
                                 "trials": len(sess["responses"])})
            except OSError as exc:
                # The judgements exist; only the write failed. Hand the whole
                # record back so the client keeps it, and say plainly that it
                # is not on disk. Silently losing a completed session would be
                # far worse than an error the listener never sees.
                self._json(200, {
                    "saved": None,
                    "error": f"could not write to disk: {exc.strerror}",
                    "trials": len(sess["responses"]),
                    "record": record,
                })
            return

        self._json(404, {"error": "no such endpoint"})


def main() -> None:
    for d in (AUDIO_DIR, SESSION_DIR):
        d.mkdir(parents=True, exist_ok=True)
    print(f"prelude listening companion on :{PORT}", flush=True)
    print(f"  app      {APP_DIR}", flush=True)
    print(f"  audio    {AUDIO_DIR} ({len(_stimuli())} stimuli)", flush=True)
    print(f"  sessions {SESSION_DIR}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
