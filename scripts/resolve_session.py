#!/usr/bin/env python3
"""Resolve a recorded session's candidate indices to stimulus names.

A session record stores judgements as bare integers - ``chose_idx`` 9 beat
``rejected_idx`` 3. Those integers only mean something relative to the
candidate pool that was mounted at the time, and rebuilding the pool renumbers
them. Changing the anchor from 22 to 19 channels re-derived every candidate
and shifted eight of them, so index 9 stopped being the pulse carrier and
became a candidate that had not existed when the listener sat down. Scoring
across that boundary does not fail; it silently answers a different question.

Pools now carry a ``pool_id`` and sessions record it, so the server can refuse
that mismatch. This script solves the other half of the problem: sessions
recorded *before* pool identity existed, whose referent would otherwise have
to be guessed.

It does not guess. Every trial record already stores both the indices and the
filenames that were actually served:

    {"a_idx": 9, "b_idx": 3, "options": ["cand_carrier_pulse.wav", ...]}

so the mapping from index to stimulus is reconstructible from the session
alone, with no pool present and no assumption about which one was mounted.
Both sessions recorded before pool identity existed resolve completely this
way, and the mapping is self-consistent in each - no index is ever served
under two different filenames.

Worth knowing why this matters here: ``archive/pool-v1-as-she-heard-it`` was
reconstructed from git history and named as though it were the pool behind the
early sessions. It is not. It holds the right *set* of stimuli but in a
different order, so resolving indices through it silently renames several
judgements. The session's own records disagree with it and the session's own
records are the primary source.

Usage
-----
    python scripts/resolve_session.py private/sessions/*.json
    python scripts/resolve_session.py --check private/sessions/*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def resolve(session: dict) -> tuple[dict[int, str], list[str]]:
    """Index -> stimulus filename, plus any inconsistencies found.

    Built only from the session's own trial records. An index served under two
    different filenames within one session would mean the pool changed
    mid-session, which should be impossible; it is reported rather than
    silently resolved to whichever came last.
    """
    mapping: dict[int, str] = {}
    problems: list[str] = []
    for t in session.get("trials", []):
        options = t.get("options") or []
        for idx, fname in zip((t.get("a_idx"), t.get("b_idx")), options, strict=False):
            if idx is None:
                continue
            if idx in mapping and mapping[idx] != fname:
                problems.append(
                    f"index {idx} served as both {mapping[idx]} and {fname}")
            mapping[idx] = fname
    return mapping, problems


def summarise(path: Path) -> dict:
    session = json.loads(path.read_text())
    mapping, problems = resolve(session)

    judgements = []
    for r in session.get("responses", []):
        chosen, rejected = r.get("chose_idx"), r.get("rejected_idx")
        if chosen is None or rejected is None:
            continue
        judgements.append((mapping.get(chosen), mapping.get(rejected)))

    unresolved = sorted(
        {i for r in session.get("responses", [])
         for i in (r.get("chose_idx"), r.get("rejected_idx"))
         if i is not None and i not in mapping}
    )

    # Level-control trials, where identical audio was presented at two levels.
    controls = [r for r in session.get("responses", []) if r.get("chose_quieter") is not None]

    return {
        "file": path.name,
        "session_id": session.get("session_id"),
        "started_at": session.get("started_at"),
        "pool_id": session.get("pool_id"),
        "mapping": mapping,
        "problems": problems,
        "unresolved": unresolved,
        "judgements": judgements,
        "n_responses": len(session.get("responses", [])),
        "control_n": len(controls),
        "control_quieter": sum(1 for r in controls if r["chose_quieter"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="+", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any session cannot be fully resolved")
    args = ap.parse_args()

    failed = False
    for path in args.sessions:
        if path.name == "calibration.json" or not path.is_file():
            continue
        s = summarise(path)
        print(f"\n{s['file']}")
        print(f"  session {s['session_id']}   started {s['started_at']}")
        print(f"  pool_id: {s['pool_id'] or 'none recorded (predates pool identity)'}")
        print(f"  {s['n_responses']} responses, {len(s['judgements'])} scored judgements, "
              f"{len(s['mapping'])} indices resolved from its own trial records")

        if s["problems"]:
            failed = True
            print("  INCONSISTENT:")
            for p in s["problems"]:
                print(f"    {p}")
        if s["unresolved"]:
            failed = True
            print(f"  UNRESOLVABLE indices (judged but never served in a "
                  f"recorded trial): {s['unresolved']}")
        if not s["problems"] and not s["unresolved"]:
            print("  fully resolvable with no pool present")

        if s["control_n"]:
            print(f"  level control: chose the quieter interval "
                  f"{s['control_quieter']}/{s['control_n']}")

        chosen = Counter(c for c, _ in s["judgements"] if c)
        if chosen:
            print("  chose:")
            for name, n in chosen.most_common():
                print(f"    {n:2d}x  {name}")
        # A preference is only readable against what was actually offered: a
        # candidate chosen 6 times but presented 6 times is not the same
        # finding as one chosen 6 times out of 12.
        offered = Counter(x for pair in s["judgements"] for x in pair if x)
        if chosen:
            print("  win rate (chosen / presented):")
            for name, n in chosen.most_common():
                print(f"    {n}/{offered[name]}  {name}")

    if args.check and failed:
        print("\nat least one session could not be fully resolved", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
