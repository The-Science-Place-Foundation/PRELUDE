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

import json
import mimetypes
import os
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

_sessions: dict[str, dict] = {}


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
    """Pick the next comparison.

    Currently pairs stimuli round-robin with a catch trial roughly every sixth,
    at a jittered position so the listener cannot learn to spot them. When the
    candidate pool is wired in, this is where prelude.fitting.SimulatorFitter
    chooses the pair by expected information gain instead.
    """
    n = len(sess["responses"])
    if n >= MAX_TRIALS:
        return None

    pool = _stimuli()
    if len(pool) < 2:
        return None

    # Jittered catch trials: identical audio both sides, no correct answer.
    # They measure response bias, which is the floor every other result is read
    # against.
    is_catch = (n > 0) and (n % 6 == (hash(sess["session_id"]) % 3 + 4))

    a = pool[n % len(pool)]
    b = a if is_catch else pool[(n + 1 + (n // len(pool))) % len(pool)]
    if b == a and not is_catch:
        b = pool[(n + 2) % len(pool)]

    order = [0, 1] if (hash(sess["session_id"] + str(n)) % 2 == 0) else [1, 0]
    trial = {
        "trial_id": uuid.uuid4().hex[:10],
        "index": n,
        "is_catch": is_catch,
        "options": [a, b],
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
            sess["responses"].append({
                "trial_id": payload.get("trial_id"),
                "chose": payload.get("chose"),          # 0, 1, or "same"
                "response_ms": payload.get("response_ms"),
                "at": _now(),
            })
            self._json(200, {"trial": _next_trial(sess)})
            return

        if route == "/api/finish":
            sid = payload.get("session_id")
            sess = _sessions.get(sid)
            if not sess:
                self._json(404, {"error": "unknown session"})
                return
            sess["finished_at"] = _now()
            sess["notes"] = payload.get("notes", "")
            sess["ended_early"] = bool(payload.get("ended_early"))
            record = {k: v for k, v in sess.items() if k != "catch_positions"}

            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            out = SESSION_DIR / f"{sess['started_at'][:10]}-{sess['session_id']}.json"
            out.write_text(json.dumps(record, indent=2))
            self._json(200, {"saved": out.name, "trials": len(sess["responses"])})
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
