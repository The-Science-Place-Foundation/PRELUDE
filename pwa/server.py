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

import hashlib
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

#: Shortest credible deliberation, in milliseconds.
#:
#: ``response_ms`` is measured from the moment PLAYBACK FINISHES, not from when
#: the trial appeared - the page locks its buttons until both candidates have
#: played, so the timer starts when there is something to judge. A listener who
#: knows what they are listening for decides in a second or two, and that is a
#: good response, not a suspicious one.
#:
#: This threshold therefore catches only a stray tap landing on a freshly
#: enabled control. An earlier version of this guard compared deliberation time
#: against the audio duration and would have rejected every genuine response in
#: the study.
MIN_DELIBERATION_MS = 250

#: Assumed discrimination sharpness in the choice model. Higher means
#: judgements are treated as more reliable.
#:
#: **The posterior is highly sensitive to this.** On the same seven judgements
#: it reports 83% at beta 6.0, 52% at 3.0 and 24% at 1.5.
#:
#: This is assumed, not measured, and there is currently no way to measure it
#: here. An attempt to calibrate it from catch-trial performance was written
#: and removed; see BETA_RANGE for why, and report the range rather than
#: quoting a single number as though the constant behind it were known.
DEFAULT_BETA = 6.0

#: Report the posterior across this range rather than at one value.
#:
#: Catch trials present identical stimuli, so a response to one cannot depend
#: on discrimination - distance is zero either way. They measure *response
#: bias*, which is a different quantity, and a listener who discriminates
#: nothing and coin-flips every trial produces textbook 50/50 catch
#: performance. Estimating sharpness from them rewarded that listener with
#: maximum trust.
#:
#: Four catch trials cannot carry the estimate either: from a true chance
#: responder the removed estimator returned beta 6.0, 3.0 or 0.9 with
#: probability 0.375 / 0.5 / 0.125 - a lottery over four coin flips, labelled
#: as measured. A spread the reader can see beats a point estimate built on
#: sand.
BETA_RANGE = (1.5, 3.0, 6.0)

#: Catch trials needed before the position-bias diagnostic says anything.
#: Below this, "both answered the same way" is what two coin flips do half
#: the time.
MIN_CATCH_FOR_BIAS = 6

#: Level-control trials at the head of each session. Identical audio at two
#: levels, so a consistent choice measures sensitivity to level and nothing
#: else. Three is enough to notice 3/3 while costing very little.
CONTROL_TRIALS = 3

#: Below this envelope distance, two candidates are not separable by this
#: procedure and a fit must not claim to have chosen between them.
#:
#: Simulated against the real pool, whether the true candidate is recovered is
#: predicted almost entirely by how close its nearest neighbour is: candidates
#: whose nearest neighbour is 0.19 or further away are identified in 5-6 runs
#: out of 6, and those within 0.07 in 0-3. The anchor itself is in the second
#: group - ``env900`` sits 0.021 from it - so the single most important
#: hypothesis in the pool is one the fit cannot pick out on its own.
#:
#: The response is to report the tie, not to break it. Deleting a candidate on
#: a metric's say-so was tried here before and removed the comparisons that
#: would have settled the question; the listener's judgements decide whether
#: two stimuli really are the same, not the distance matrix.
NEAR_DUPLICATE_DISTANCE = 0.05

_sessions: dict[str, dict] = {}
_pool: dict | None = None

#: Where the listener's calibration lives. One file, overwritten - the most
#: recent measurement is the one that applies, and hearing changes over time so
#: an old reading is not a second opinion.
CALIB_FILE = lambda: SESSION_DIR / "calibration.json"  # noqa: E731


def _read_calibration() -> dict | None:
    f = CALIB_FILE()
    if f.is_file():
        try:
            return json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            return None
    return None


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


def _position_bias(sess: dict) -> dict:
    """What catch trials can actually tell us: does one slot get picked more?

    This is a diagnostic, not a correction. Catch trials carry no distance
    signal, so they say nothing about how sharply the listener discriminates -
    only whether their choices are tied to position. Reported so a reader can
    weigh the result; deliberately not folded back into the fit.

    Two reasons it is not folded in. A position bias is directional evidence -
    it says a slot was favoured - whereas lowering beta just shrinks the
    posterior toward uniform, which is not the same correction. And the
    honest model for it is an additive position term in the choice model,
    which is a real change to the fit and needs its own validation rather
    than being smuggled in as a constant.

    Catch responses that were flagged ``too_fast`` are excluded: a stray tap
    is not a judgement about position.
    """
    catch = [r for r in sess["responses"]
             if r.get("is_catch") and isinstance(r.get("chose"), int)
             and not r.get("too_fast")]
    n = len(catch)
    if n == 0:
        return {"n_catch": 0, "measurable": False,
                "note": "no catch trials yet"}
    first = sum(1 for r in catch if r["chose"] == 0)
    out = {
        "n_catch": n,
        "chose_first": first,
        "fraction_first": round(first / n, 3),
        "measurable": n >= MIN_CATCH_FOR_BIAS,
    }
    if n < MIN_CATCH_FOR_BIAS:
        out["note"] = (f"{n} catch trial(s); {MIN_CATCH_FOR_BIAS} needed before "
                       f"a lopsided split means anything")
    elif first in (0, n):
        out["note"] = f"every catch trial answered on one side ({first}/{n}) - treat with care"
    else:
        out["note"] = f"{first}/{n} on the first interval"
    return out


def _stored_sessions() -> list[dict]:
    """Every readable session record on disk.

    Anything that is not a well-formed session is skipped rather than trusted.
    A malformed file must not be able to end a live session: this runs inside
    /api/finish, before the final write, so an exception here would show the
    listener the trouble screen at the very end and lose the fit, the control
    result and their notes. Valid JSON of the wrong *shape* is the case that
    actually got through - a bare list, or ``responses: null``.
    """
    out: list[dict] = []
    try:
        files = sorted(SESSION_DIR.glob("*.json"))
    except OSError:
        return out
    for f in files:
        if f.name == "calibration.json":
            continue
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        if not isinstance(rec.get("responses"), list):
            continue
        if not isinstance(rec.get("trials"), list):
            rec["trials"] = []
        out.append(rec)
    return out


def _with_trial_metadata(sess: dict) -> list[dict]:
    """Responses, with ``is_catch`` recovered from the trial record if absent.

    ``is_catch`` began being written on the response only recently, so earlier
    sessions carry it on the *trial* alone. Without this join those sessions
    contribute nothing to the bias diagnostic, and the diagnostic would say
    nothing for several more sittings - which is the whole reason it pools.
    The data is already on disk; it just needs the trial_id join.
    """
    trials = {t.get("trial_id"): t for t in sess.get("trials", [])
              if isinstance(t, dict)}
    out = []
    for r in sess.get("responses", []):
        if not isinstance(r, dict):
            continue
        if "is_catch" not in r:
            t = trials.get(r.get("trial_id"))
            if isinstance(t, dict) and "is_catch" in t:
                r = {**r, "is_catch": t["is_catch"]}
        out.append(r)
    return out


def _pooled_position_bias(current: dict) -> dict:
    """Position bias over every session on disk, plus the one in flight.

    Deliberately pooled across pools. A tendency to favour the first interval
    belongs to the listener and the interface, not to which candidates were
    mounted, so unlike anything index-based this is safe to accumulate - and
    it has to be, because a single session is too short to collect enough
    catch trials to say anything.
    """
    seen: dict[str, list] = {current["session_id"]: _with_trial_metadata(current)}
    for rec in _stored_sessions():
        sid = rec.get("session_id")
        if sid and sid not in seen:
            seen[sid] = _with_trial_metadata(rec)
    merged = {"responses": [r for rs in seen.values() for r in rs]}
    out = _position_bias(merged)
    out["n_sessions"] = len(seen)
    return out


def _pooled_judgements(current: dict) -> tuple[list[dict], int]:
    """Scored judgements from every session recorded against the mounted pool.

    Returns the judgements and how many sessions contributed.

    **This is what pool identity is for.** A single sitting yields a handful of
    judgements - the two real sessions ran six and nine responses - and a fit
    over that many will not converge honestly no matter how the threshold is
    set. Requiring convergence within one session either never fires or fires
    on noise.

    Accumulating indices across sessions is exactly the operation that was
    unsafe before ``pool_id`` existed, because a rebuild renumbers candidates
    and the same integer silently means a different sound. With the id
    recorded on both sides it becomes safe, and refusing to use it would spend
    the listener's evenings on a verdict that can never be printed.

    Sessions whose ``pool_id`` does not match the mounted pool are skipped,
    not translated. Their judgements remain readable by name through
    scripts/resolve_session.py.
    """
    pool = _load_pool() or {}
    mounted = pool.get("pool_id")
    seen: dict[str, list] = {}
    if not _pool_mismatch(current):
        seen[current["session_id"]] = current["responses"]
    for rec in _stored_sessions():
        sid = rec.get("session_id")
        if not sid or sid in seen:
            continue
        # An unstamped session cannot be confirmed to share the mounted pool,
        # so it is not folded in. Silence beats a plausible wrong answer.
        if mounted is None or rec.get("pool_id") != mounted:
            continue
        seen[sid] = rec["responses"]

    judgements = [
        r for rs in seen.values() for r in rs
        if isinstance(r, dict)
        and isinstance(r.get("chose_idx"), int)
        and isinstance(r.get("rejected_idx"), int)
    ]
    return judgements, len(seen)


def _pool_mismatch(sess: dict) -> str | None:
    """Whether this session's indices mean anything against the mounted pool.

    Session records store bare integers. Rebuilding the pool renumbers them:
    moving the anchor from 22 to 19 channels re-derived every candidate and
    shifted eight of them, so index 9 stopped being the pulse carrier and
    became a candidate that did not exist when the listener sat down. Scoring
    across that boundary does not fail - it silently answers a different
    question. Refuse instead.
    """
    pool = _load_pool()
    if not pool:
        return "no pool mounted"
    mounted = pool.get("pool_id")
    recorded = sess.get("pool_id")
    if mounted is None:
        return None                      # pre-identity pool; nothing to check
    if recorded is None:
        return "session predates pool identity - cannot confirm it matches"
    if recorded != mounted:
        return f"session was recorded against pool {recorded}, mounted pool is {mounted}"
    return None


def _posterior(sess: dict, beta: float = DEFAULT_BETA) -> list[float]:
    """Normalised posterior over which candidate the listener is hearing.

    Sequential Bayesian update. Presented with two candidates, a listener
    prefers whichever sounds closer to their own percept, so for a hypothesised
    truth t:

        P(choose A over B | t) = sigmoid(beta * [D(B,t) - D(A,t)])

    D is computable for any hypothesised t, so a choice can be scored without
    ever knowing the answer.

    ``beta`` is supplied by the caller and is an assumption. The result moves
    a long way with it, so callers reporting a confidence to a human should
    report the spread over BETA_RANGE rather than one number.

    Judgements are accumulated across every session recorded against the
    mounted pool, not just the current one - a sitting is far too short to
    settle a twenty-candidate pool on its own. See :func:`_pooled_judgements`.
    """
    pool = _load_pool()
    if not pool:
        return []
    if _pool_mismatch(sess):
        return []
    dist = pool["distances"]
    n = len(dist)
    logp = [0.0] * n

    judgements, _ = _pooled_judgements(sess)
    for r in judgements:
        # "They feel the same" carries real information - it says the two are
        # near-equidistant from the listener's percept - but not as a preference,
        # so it updates nothing here rather than being forced into one.
        # _pooled_judgements has already dropped those.
        chosen, rejected = r["chose_idx"], r["rejected_idx"]
        if not (0 <= chosen < n and 0 <= rejected < n):
            continue          # a record from a pool with more candidates
        for t in range(n):
            logp[t] += _log_sigmoid(beta * (dist[rejected][t] - dist[chosen][t]))

    m = max(logp)
    w = [math.exp(v - m) for v in logp]
    total = sum(w)
    return [x / total for x in w] if total > 0 else [1.0 / n] * n


def _information_gain(a: int, b: int, post: list[float], dist: list[list[float]],
                      beta: float = DEFAULT_BETA) -> float:
    """Expected reduction in posterior entropy from asking about (a, b).

    Choosing the most informative comparison rather than a random one is what
    makes a short session worth sitting through - listening time is the binding
    constraint on the whole project.
    """
    la = [_log_sigmoid(beta * (dist[b][t] - dist[a][t])) for t in range(len(post))]
    lb = [_log_sigmoid(beta * (dist[a][t] - dist[b][t])) for t in range(len(post))]
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


def _persist(sess: dict) -> None:
    """Write the session to disk now, not at the end.

    A session that is abandoned by closing the app never reaches /api/finish.
    Holding responses in memory until then lost one of the first two real
    sessions outright. Every response is worth keeping whether or not the
    listener taps through to the end - and stopping early is a normal, expected
    outcome that the interface actively encourages.
    """
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        record = {k: v for k, v in sess.items() if k != "catch_positions"}
        out = SESSION_DIR / f"{sess['started_at'][:10]}-{sess['session_id']}.json"
        out.write_text(json.dumps(record, indent=2))
    except OSError:
        # Losing the write is survivable; losing the session mid-flight is not,
        # so never let a disk problem interrupt a listener.
        pass


def _asset_version(name: str) -> str:
    """Content hash of a static asset, used to bust caches on change."""
    f = APP_DIR / name
    if not f.is_file():
        return "0"
    return hashlib.sha256(f.read_bytes()).hexdigest()[:8]


def _shell() -> bytes:
    """index.html with asset URLs stamped by content hash.

    Without this an installed PWA can hold a stale script indefinitely. It did:
    a fix that locked the choice buttons until playback finished was live on the
    server for forty minutes before a session that ignored it entirely, because
    the phone was still running the previous copy.
    """
    html = (APP_DIR / "index.html").read_text()
    for asset in ("app.js", "style.css"):
        html = html.replace(f'"/{asset}"', f'"/{asset}?v={_asset_version(asset)}"')
    return html.encode()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stimuli() -> list[str]:
    """Available stimulus files, sorted for stable trial construction."""
    if not AUDIO_DIR.is_dir():
        return []
    return sorted(p.name for p in AUDIO_DIR.glob("*.wav"))


def _new_session(listener: str = "P01") -> dict:
    pool = _load_pool() or {}
    return {
        "session_id": uuid.uuid4().hex[:12],
        "listener": listener,
        "started_at": _now(),
        # Which pool the indices below refer to. Without this a session is a
        # list of integers with no referent, and rebuilding the pool
        # reinterprets it silently rather than failing.
        "pool_id": pool.get("pool_id"),
        "trials": [],
        "responses": [],
        "complete": False,
        "catch_positions": set(),
    }


def _next_trial(sess: dict) -> dict | None:
    """Choose the next comparison by expected information gain.

    Returns None to end the session, which the app presents as a normal
    finish.
    """
    # If the pool changed under a live session, every index this session has
    # recorded now means something else. End it cleanly rather than serving
    # trials that cannot be scored: _posterior returns [] on a mismatch, and
    # the selection below would then index an empty posterior.
    if _pool_mismatch(sess):
        return None

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

    def counterbalanced_order() -> list[int]:
        """Which slot gets the first-named stimulus, balanced in blocks of two.

        See the note at the candidate-trial call site: independent per-trial
        draws streaked far enough in one real session to place the favoured
        candidate in the same interval five times running.
        """
        blk = random.Random(f"{sess['session_id']}:block:{n // 2}")
        flip = blk.random() < 0.5
        if n % 2 == 0:
            return [0, 1] if flip else [1, 0]
        return [1, 0] if flip else [0, 1]

    # ---- level control, first --------------------------------------------
    # Identical audio at two levels. If the listener reliably picks the
    # quieter interval, then any candidate preference that happens to
    # correlate with level explains itself, and the pulse-carrier result from
    # the first session - where that candidate sat 3 dB below every other -
    # does not survive.
    #
    # First in the session, not sprinkled through it: this is the question the
    # whole rebuild exists to answer, and sessions end early by design. A
    # control that only runs if the listener keeps going is not a control.
    ctrl = pool.get("control_pair")
    if ctrl and n < CONTROL_TRIALS:
        files = list(ctrl["files"])            # [reference, quieter]
        order = counterbalanced_order()
        trial = {
            "trial_id": uuid.uuid4().hex[:10],
            "index": n,
            "is_catch": False,
            "is_control": True,
            "control_kind": "level",
            # Which slot held the quieter file, so the response can be scored
            # without trusting the client to report it.
            "quiet_first": order[0] == 1,
            "audio_ms": int(ctrl.get("duration_s", 0.0) * 2000),
            "a_idx": None, "b_idx": None,
            "options": files,
            "presentation_order": order,
            "remaining": MAX_TRIALS - n,
        }
        sess["trials"].append(trial)
        return trial

    # Catch trial: the same candidate on both sides, so there is no correct
    # answer. Any consistent preference measures response bias, which is the
    # floor every other result has to be read against. Position is jittered -
    # a fixed interval would let a listener learn to spot them.
    #
    # Back to one in six after a brief spell at one in four. The higher rate
    # was there to reach four catch trials in a session so beta could be
    # estimated from them; that estimator has been removed as unsound. At the
    # length sessions actually run - around nine responses - one in four
    # bought roughly two catch trials instead of one and a half, reached the
    # diagnostic threshold almost never, and cost most of an informative
    # judgement every session. Bias is a trait of the listener rather than of
    # the sitting, so it accumulates across sessions instead (see
    # _pooled_position_bias) and does not need to be bought twice over.
    is_catch = n > 0 and rng.random() < (1.0 / 6.0)
    if is_catch:
        a = b = rng.randrange(total)
    else:
        post = _posterior(sess)
        if not post:
            return None      # nothing scoreable; end rather than serve untrackable trials
        # Restrict to candidates still plausibly the answer, then pick the pair
        # that most reduces uncertainty.
        live = [i for i, p in enumerate(post) if p > max(post) * 1e-3] or list(range(total))
        if len(live) > 10:
            live = sorted(live, key=lambda i: -post[i])[:10]
        asked = {tuple(sorted((t["a_idx"], t["b_idx"]))) for t in sess["trials"]
                 if t.get("a_idx") is not None and t.get("b_idx") is not None}
        best, best_gain = None, -1e9
        for i, j in itertools.combinations(live, 2):
            if tuple(sorted((i, j))) in asked:
                continue
            g = _information_gain(i, j, post, dist, DEFAULT_BETA)
            if g > best_gain:
                best, best_gain = (i, j), g
        if best is None:
            order = sorted(range(total), key=lambda i: -post[i])
            best = (order[0], order[1])
        a, b = best

    # Presentation order, counterbalanced in blocks of two rather than drawn
    # independently per trial.
    #
    # Independent coin flips streak, and a streak here is not cosmetic. The
    # information-gain selector puts the leading candidate first in most pairs,
    # so the order decides which slot the leader occupies - and in the session
    # of 2026-07-29 the per-trial draws came up [1,0] six times running, which
    # placed the favoured candidate in the second interval on all five trials
    # it appeared in. "Preferred that candidate" and "pressed the second
    # button" then predict identical data, which is the same shape of confound
    # as the level problem and just as capable of producing a clean-looking
    # result.
    #
    # The shuffle was not broken - measured 0.501 over 4000 seeds. Randomness
    # streaking is not a bug, which is exactly why the design must not depend
    # on it not streaking. Blocks of two bound the imbalance to one trial.
    order = counterbalanced_order()
    dur_a = cands[a].get("duration_s", 0.0)
    dur_b = cands[b].get("duration_s", 0.0)
    trial = {
        "trial_id": uuid.uuid4().hex[:10],
        "index": n,
        "is_catch": is_catch,
        # Both candidates play in sequence, so this is the floor for a response
        # that involved listening.
        "audio_ms": int((dur_a + dur_b) * 1000),
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

    def do_HEAD(self):  # noqa: N802 - stdlib signature
        self.do_GET()

    # -------------------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802 - stdlib signature
        route = self.path.split("?")[0].rstrip("/") or "/"

        if route == "/health":
            self._json(200, {
                "ok": True, "time": _now(),
                "stimuli": len(_stimuli()),
                "candidates": len((_load_pool() or {}).get("candidates", [])),
                "calibrated": _read_calibration() is not None,
                "sessions_on_disk": len(list(SESSION_DIR.glob("*.json")))
                if SESSION_DIR.is_dir() else 0,
            })
            return

        if route == "/api/calibration":
            # ``pool_balance_db`` is how much of the measured balance is
            # already baked into the rendered stimuli. The app applies the
            # remainder at playback and must not reapply the whole offset.
            #
            # This exists because it was got wrong: a pool rendered with
            # --balance-db 6.0 was about to be served to an app that also
            # applies the measured 6 dB at playback, which would have put the
            # ears 12 dB apart against a balance measured at 6. Reporting what
            # is already in the file makes the double-application structural
            # rather than a thing to remember.
            pool = _load_pool() or {}
            self._json(200, {
                "calibration": _read_calibration(),
                "pool_balance_db": float(pool.get("balance_db") or 0.0),
            })
            return

        if route == "/api/session":
            sess = _new_session()
            sess["calibration"] = _read_calibration()
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
            # Immutable is safe because candidate and control filenames carry
            # the config hash of the audio in them, so a rebuild produces new
            # URLs rather than new bytes at old ones. The two fixed-name
            # calibration stimuli are carried forward between pools unchanged
            # for the same reason.
            self._file(AUDIO_DIR / name, "public, max-age=31536000, immutable")
            return

        # Static app. Unknown paths fall through to the shell so the PWA can
        # own its own routing.
        rel = route.lstrip("/") or "index.html"
        # The shell is generated, not served raw: it carries the asset version
        # stamps. Serving the file directly would bypass that and leave every
        # other asset pinned to whatever a cached copy referenced.
        if rel == "index.html":
            self._send(200, _shell(), "text/html", {"Cache-Control": "no-store"})
            return
        candidate = (APP_DIR / rel).resolve()
        if APP_DIR.resolve() in candidate.parents or candidate == APP_DIR.resolve():
            if candidate.is_file():
                # Assets are requested with a content-hash query, so they are
                # safe to cache forever; a change produces a different URL.
                cache = ("public, max-age=31536000, immutable"
                         if self.path.find("?v=") > 0 else "no-store")
                self._file(candidate, cache)
                return
        # The shell is never cached. It carries the asset versions, so a stale
        # copy pins every other file to whatever it referenced.
        self._send(200, _shell(), "text/html", {"Cache-Control": "no-store"})

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

            # Only a stray tap is rejected. The response is still recorded -
            # discarding data silently is worse than keeping it flagged.
            too_fast = (payload.get("response_ms") or 0) < MIN_DELIBERATION_MS
            rec = {
                "trial_id": payload.get("trial_id"),
                "chose": chose,
                "response_ms": payload.get("response_ms"),
                "at": _now(),
            }
            rec["too_fast"] = too_fast
            rec["is_catch"] = bool(trial and trial.get("is_catch"))
            # Resolve the blinded choice back to candidate indices. The page is
            # never told which card is which; that mapping lives only here.
            # Skipped when the response beat the audio: without indices the
            # posterior cannot use it.
            # Score the level control: did they pick the quieter interval?
            # Recorded from the server's own record of which slot held it, so
            # a client bug cannot invert the answer.
            if trial and trial.get("is_control") and isinstance(chose, int) and not too_fast:
                quiet_slot = 0 if trial["quiet_first"] else 1
                rec["chose_quieter"] = (chose == quiet_slot)

            if (trial and isinstance(chose, int) and not trial["is_catch"]
                    and not trial.get("is_control") and not too_fast):
                shown = [trial["a_idx"], trial["b_idx"]]
                picked = shown[trial["presentation_order"][chose]]
                other = shown[trial["presentation_order"][1 - chose]]
                rec["chose_idx"], rec["rejected_idx"] = picked, other
            sess["responses"].append(rec)
            _persist(sess)   # durable immediately, not only on finish
            self._json(200, {"trial": _next_trial(sess)})
            return

        if route == "/api/calibration":
            # Balance offset in dB on the implant side, plus whether the audio
            # path was verified to keep the ears separate. Both are required
            # before any comparison means anything: an unbalanced pair makes
            # every judgement partly a judgement about level, and a path that
            # collapses to mono makes them all meaningless while still sounding
            # perfectly plausible.
            record = {
                "balance_db": payload.get("balance_db"),
                "channels_separate": payload.get("channels_separate"),
                "reversals": payload.get("reversals", []),
                "responses": payload.get("responses", []),
                "measured_at": _now(),
            }
            try:
                SESSION_DIR.mkdir(parents=True, exist_ok=True)
                CALIB_FILE().write_text(json.dumps(record, indent=2))
                self._json(200, {"saved": True, "calibration": record})
            except OSError as exc:
                self._json(200, {"saved": False,
                                 "error": f"could not write: {exc.strerror}",
                                 "calibration": record})
            return

        if route == "/api/finish":
            sid = payload.get("session_id")
            sess = _sessions.get(sid)
            if not sess:
                self._json(404, {"error": "unknown session"})
                return

            usable = sum(1 for r in sess["responses"]
                         if r.get("chose_idx") is not None)
            discarded = sum(1 for r in sess["responses"] if r.get("too_fast"))
            sess["usable_responses"] = usable
            sess["discarded_too_fast"] = discarded
            # Level control, reported whether or not the fit ran. If the
            # listener picked the quieter interval every time, a candidate
            # preference that tracks level is explained and the fit below is
            # not the story.
            ctrl_resp = [r for r in sess["responses"]
                         if r.get("chose_quieter") is not None]
            if ctrl_resp:
                n_ctrl = len(ctrl_resp)
                n_quiet = sum(1 for r in ctrl_resp if r["chose_quieter"])
                # Symmetric, and honest about how weak three trials are.
                #
                # An all-louder run is a level effect too - the same confound
                # with the opposite sign - and an earlier wording filed it
                # under "no consistent pull", which would have hidden exactly
                # the result that refutes the pulse-carrier story.
                #
                # Three of three is p = 0.125 under indifference. The bias
                # diagnostic next door refuses to read six trials as evidence
                # for the same reason, and it would be incoherent to declare a
                # confound proven off three.
                if n_quiet == n_ctrl:
                    note = ("always chose the quieter interval - suggestive of "
                            "a level effect, but 1 in 8 by chance at three "
                            "trials; treat any level-correlated preference as "
                            "unproven until there are more")
                elif n_quiet == 0:
                    note = ("always chose the louder interval - also a level "
                            "effect, same caveat: 1 in 8 by chance at three "
                            "trials")
                else:
                    note = "mixed; no evidence that level alone drives the choice"
                sess["level_control"] = {
                    "n": n_ctrl,
                    "chose_quieter": n_quiet,
                    "difference_db": (_load_pool() or {}).get(
                        "control_pair", {}).get("difference_db"),
                    "one_sided": n_quiet in (0, n_ctrl),
                    "p_if_indifferent": round(0.5 ** (n_ctrl - 1), 4)
                                        if n_quiet in (0, n_ctrl) else None,
                    "interpretation": note,
                }

            sess["position_bias"] = _pooled_position_bias(sess)

            mismatch = _pool_mismatch(sess)
            if mismatch:
                sess["fit"] = {"unavailable": mismatch}
            post = _posterior(sess)
            if post:
                top = max(range(len(post)), key=lambda i: post[i])
                pool = _load_pool()
                # The posterior moves a long way with beta and beta is
                # assumed, so report the spread rather than one number
                # dressed up as a measurement. An earlier version estimated
                # beta from catch-trial performance; catch trials measure
                # position bias, not sharpness, and four of them made the
                # reported confidence a lottery over four coin flips.
                spread = {}
                for b in BETA_RANGE:
                    pb = _posterior(sess, b)
                    spread[str(b)] = round(pb[top], 4) if pb else None
                pooled, n_sessions = _pooled_judgements(sess)
                # Candidates this procedure cannot separate from the winner.
                # Naming one of a near-identical pair as "the answer" would be
                # an artefact of which pairs happened to be asked.
                dist = pool["distances"]
                tied = [pool["candidates"][i]["name"] for i in range(len(post))
                        if i != top and dist[top][i] < NEAR_DUPLICATE_DISTANCE]
                sess["fit"] = {
                    "best_candidate": pool["candidates"][top]["name"],
                    "not_separable_from": tied,
                    "probability": round(post[top], 4),
                    # Convergence needs enough judgements to have earned it. A
                    # high posterior over a handful of responses is an artefact
                    # of which pairs happened to be asked. It also has to hold
                    # at the pessimistic end of the beta range - a result that
                    # only appears when the listener is assumed reliable is an
                    # assumption, not a finding.
                    #
                    # Counted over every session sharing this pool, not just
                    # this one. Within a single sitting the threshold could
                    # only ever fire on noise or never fire at all: the two
                    # real sessions ran six and nine responses against a
                    # twenty-candidate pool.
                    #
                    # Evaluated at the assumed beta. Requiring it to hold at
                    # the bottom of BETA_RANGE as well was tried and reverted:
                    # simulated against the real pool it never fired, because
                    # the pool deliberately clusters fine variations around
                    # the anchor and separating the anchor from its own
                    # neighbours at beta 1.5 needs on the order of a hundred
                    # judgements - ten or more sittings. A criterion that
                    # cannot fire is not conservative, it is broken, and it
                    # spends someone's evenings printing nothing.
                    #
                    # The sensitivity is reported instead of being buried in
                    # the threshold: robust_across_beta below says whether the
                    # result survives the pessimistic assumption, and
                    # probability_by_beta shows the whole spread.
                    # A tie with a near-duplicate is not convergence, however
                    # high the posterior climbs: the mass is on a pair, and
                    # which member holds it is arbitrary.
                    "converged": (post[top] >= 0.80 and len(pooled) >= 12
                                  and not tied),
                    "robust_across_beta": (spread[str(min(BETA_RANGE))] or 0) >= 0.80,
                    "usable_responses": usable,
                    "pooled_judgements": len(pooled),
                    "pooled_sessions": n_sessions,
                    "discarded_too_fast": discarded,
                    "beta_assumed": DEFAULT_BETA,
                    "beta_is_assumed_not_measured": True,
                    "probability_by_beta": spread,
                    "posterior": [round(p, 4) for p in post],
                }
            sess["complete"] = True
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
