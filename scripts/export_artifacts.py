#!/usr/bin/env python3
# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.

"""Export a self-contained record of everything measured from one listener.

Written for use **outside this project and after it**. Nothing in the output
imports PRELUDE, depends on its file layout, or needs its code to be readable:
CSV and JSON for the data, Markdown for the method, checksums for the stimuli,
and one dependency-free Python reader.

The measurements here cannot be repeated. The listener's hearing is
degenerative, the clinic is not reachable, and the frequency allocation table
and audiogram that would ordinarily supply this were never obtainable. What is
exported is therefore treated as a primary record rather than as intermediate
output - raw responses are copied verbatim alongside every derived figure, so
a future reader can disagree with the derivation and redo it.

Usage
-----
    python scripts/export_artifacts.py -o private/artifacts
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

#: Semitone shift below which a match counts as "no appreciable shift", set to
#: the method's own resolution. The finest probe rung is an eighth of an octave
#: (1.5 semitones), so anything inside that is indistinguishable from zero.
RESOLUTION_ST = 1.5


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _semitones(a: float, b: float) -> float:
    from math import log2
    return 12.0 * log2(a / b)


def export(mapping: Path, sessions: Path, calibration: Path,
           stimuli: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "raw").mkdir(exist_ok=True)
    (out / "derived").mkdir(exist_ok=True)
    (out / "stimuli").mkdir(exist_ok=True)

    m = json.loads(mapping.read_text())

    # ---- raw, verbatim -------------------------------------------------
    shutil.copy2(mapping, out / "raw" / "mapping.json")
    if calibration.is_file():
        shutil.copy2(calibration, out / "raw" / "calibration.json")
    raw_sessions = out / "raw" / "listening-sessions"
    raw_sessions.mkdir(exist_ok=True)
    n_sessions = 0
    if sessions.is_dir():
        for f in sorted(sessions.glob("*.json")):
            if f.name in ("calibration.json", "mapping.json"):
                continue
            shutil.copy2(f, raw_sessions / f.name)
            n_sessions += 1

    # ---- derived: the frequency-place map ------------------------------
    rows = []
    for e in m.get("match", []):
        ci, mt = e.get("ci_hz"), e.get("match_hz")
        rows.append({
            "input_hz": ci,
            "perceived_as_hz": mt,
            "shift_semitones": (round(_semitones(mt, ci), 3)
                                if mt and ci else None),
            "basis": e.get("basis"),
            "bracketed": e.get("bracketed"),
            "settled": e.get("settled"),
            "spread_semitones": e.get("spread_semitones"),
            "n_trials": e.get("n_trials"),
            "started_below": e.get("started_below"),
        })
    rows.sort(key=lambda r: r["input_hz"] or 0)
    with (out / "derived" / "frequency-place-map.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["input_hz"])
        w.writeheader()
        w.writerows(rows)

    # ---- derived: audibility -------------------------------------------
    aud = [{"center_hz": d.get("center_hz"), "verdict": d.get("heard")}
           for d in m.get("detect", [])]
    aud.sort(key=lambda r: r["center_hz"] or 0)
    with (out / "derived" / "audibility.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["center_hz", "verdict"])
        w.writeheader()
        w.writerows(aud)

    # ---- derived: machine-readable map with an explicit interpolation ---
    # Piecewise linear in log-frequency, deliberately. Three points cannot
    # support a fitted model, and imposing one would invent structure between
    # and beyond them. Held flat outside the measured range, because
    # extrapolating a frequency-place map is exactly the kind of plausible
    # invention this project has been bitten by.
    knots = [(r["input_hz"], r["perceived_as_hz"]) for r in rows
             if r["perceived_as_hz"]]
    place = {
        "listener": "P01",
        "measured": m.get("first_measured_at"),
        "method": "interaural pitch match, third-octave noise bursts",
        "interpolation": "piecewise linear in log2(frequency)",
        "extrapolation": "held flat outside the measured range",
        "resolution_semitones": RESOLUTION_ST,
        "knots_hz": [{"input": a, "perceived_as": b} for a, b in knots],
        "caveat": (
            "Three points. The shift is not constant across them, and the "
            "direction is downward where cochlear implant literature expects "
            "upward, since arrays do not reach the apex. Interpolate; do not "
            "fit, and do not extrapolate."),
    }
    (out / "derived" / "place-map.json").write_text(json.dumps(place, indent=2))

    # ---- stimuli: identity, so they can be checked or regenerated -------
    stim = {"source": "scripts/make_mapping_session.py", "files": []}
    if stimuli.is_dir():
        for f in sorted(stimuli.glob("map_*.wav")):
            stim["files"].append({"file": f.name, "bytes": f.stat().st_size,
                                  "sha256": _sha256(f)})
    manifest = stimuli / "mapping.json"
    if manifest.is_file():
        stim["manifest"] = json.loads(manifest.read_text())
    (out / "stimuli" / "stimulus-checksums.json").write_text(json.dumps(stim, indent=2))

    return {"n_match": len(rows), "n_detect": len(aud),
            "n_sessions": n_sessions, "n_stimuli": len(stim["files"])}


READER = '''#!/usr/bin/env python3
"""Read this archive without PRELUDE, or any third-party package.

    python read_map.py                 # summary
    python read_map.py --hz 1000       # where the implant places 1000 Hz
"""
from __future__ import annotations
import argparse, csv, json
from math import log2
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_place_map() -> dict:
    return json.loads((HERE / "derived" / "place-map.json").read_text())


def perceived_as(hz: float, place: dict | None = None) -> float:
    """Acoustic frequency the implant's percept of ``hz`` was matched to.

    Piecewise linear in log-frequency between measured points, held flat
    outside them. Deliberately not a fitted curve: there are three knots, and
    a model over three points invents structure it cannot support.
    """
    place = place or load_place_map()
    k = [(p["input"], p["perceived_as"]) for p in place["knots_hz"]]
    k.sort()
    if hz <= k[0][0]:
        return hz * (k[0][1] / k[0][0])
    if hz >= k[-1][0]:
        return hz * (k[-1][1] / k[-1][0])
    for (x0, y0), (x1, y1) in zip(k, k[1:]):
        if x0 <= hz <= x1:
            t = (log2(hz) - log2(x0)) / (log2(x1) - log2(x0))
            return 2 ** (log2(y0) + t * (log2(y1) - log2(y0)))
    raise ValueError(hz)


def audibility() -> list[dict]:
    with (HERE / "derived" / "audibility.csv").open() as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hz", type=float)
    a = ap.parse_args()
    place = load_place_map()
    if a.hz:
        got = perceived_as(a.hz, place)
        print(f"{a.hz:.0f} Hz -> perceived at {got:.1f} Hz "
              f"({12 * log2(got / a.hz):+.2f} semitones)")
        return 0
    print(f"Listener {place['listener']}, measured {place['measured']}")
    print(f"  {place['method']}")
    print(f"  resolution: {place['resolution_semitones']} semitones\\n")
    print("  frequency-place map:")
    for p in place["knots_hz"]:
        st = 12 * log2(p["perceived_as"] / p["input"])
        print(f"    {p['input']:>7.0f} Hz -> {p['perceived_as']:>7.1f} Hz  "
              f"({st:+.2f} st)")
    print("\\n  audibility of the acoustic ear at the presentation level:")
    for r in audibility():
        print(f"    {float(r['center_hz']):>7.0f} Hz  {r['verdict']}")
    print(f"\\n  {place['caveat']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", type=Path, default=Path("private/artifacts"))
    ap.add_argument("--mapping", type=Path,
                    default=Path("private/mapping/2026-07-30-mapping-P01-run1.json"))
    ap.add_argument("--sessions", type=Path, default=Path("private/sessions"))
    ap.add_argument("--calibration", type=Path,
                    default=Path("private/sessions/calibration.json"))
    ap.add_argument("--stimuli", type=Path, default=Path("pool_new"))
    args = ap.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = args.output / f"{stamp}-P01-frequency-map"
    counts = export(args.mapping, args.sessions, args.calibration,
                    args.stimuli, out)
    (out / "read_map.py").write_text(READER)
    (out / "read_map.py").chmod(0o755)

    print(f"wrote {out}")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
