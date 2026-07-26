#!/usr/bin/env python3
# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Render a pool of candidate simulations, and the distances between them.

The fitting loop asks "which of these two is closer to what your implant makes
of it?", so the two things being compared must be **different simulations of the
same source** - not different source material, and not the same simulation at
different levels. A pool of near-identical candidates produces trials where
every honest answer is "they sound the same", which is exactly what happens if
calibration stimuli are used here by mistake.

Two things are written:

``<name>.wav``
    One dichotic file per candidate. The implanted ear hears the unmodified
    source; the acoustic ear hears that candidate's simulation of it. Levels are
    matched per ear.

``pool.json``
    The full pairwise perceptual distance matrix, plus each candidate's
    configuration. The server needs the matrix to run the posterior update and
    to choose informative comparisons, and computing it here means the container
    needs no numerical libraries at all.

Usage
-----
    python3 scripts/make_candidate_pool.py --source speech.wav \
        --implant-ear right -o pool/
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from prelude.audio import Audio, load_audio, save_audio
from prelude.ci_sim import SimulatorConfig, simulate
from prelude.fitting import envelope_distance
from prelude.study import Ear, EarAssignment, PresentationMode, build_dichotic

SR = 20000


def candidate_configs() -> list[tuple[str, SimulatorConfig]]:
    """A spread of plausible devices, chosen to be audibly distinct.

    Spread matters more than realism at this stage. If two candidates differ
    only in a way the listener cannot hear, the trial comparing them costs a
    minute and returns nothing. These vary the parameters that dominate the
    percept - channel count, how many channels survive peak picking, carrier,
    envelope bandwidth, and current spread.

    Defaults elsewhere follow a Cochlear Nucleus platform: 22 electrodes,
    ACE-style peak picking, 900 pps.
    """
    base = dict(low_freq=300.0, high_freq=8500.0, stimulation_rate_hz=900.0, seed=0)
    out: list[tuple[str, SimulatorConfig]] = []

    # Channel count: the single strongest determinant of fidelity.
    for n in (4, 8, 12, 16, 22):
        out.append((f"ch{n:02d}", SimulatorConfig(
            n_channels=n, n_selected=n, carrier="noise",
            envelope_cutoff_hz=300.0, interaction_decay_db=8.0, **base)))

    # n-of-m depth on a 22-electrode array.
    for n_sel in (4, 8, 12):
        out.append((f"ace{n_sel:02d}of22", SimulatorConfig(
            n_channels=22, n_selected=n_sel, carrier="noise",
            envelope_cutoff_hz=300.0, interaction_decay_db=8.0, **base)))

    # Current spread. Pushed to extremes deliberately: measured on channel
    # envelopes, 3 vs 13 dB/channel differ by less than 0.1 - far below what a
    # listener could report - so intermediate values only waste trials.
    for db, tag in ((1.5, "smeared"), (30.0, "focused")):
        out.append((f"spread_{tag}", SimulatorConfig(
            n_channels=22, n_selected=8, carrier="noise",
            envelope_cutoff_hz=300.0, interaction_decay_db=db, **base)))

    # Envelope bandwidth. Same reasoning: 300 vs 600 Hz is not separable in
    # this domain, so the pool spans a range that is.
    for cut, tag in ((25.0, "slow"), (1500.0, "fast")):
        out.append((f"env_{tag}", SimulatorConfig(
            n_channels=22, n_selected=8, carrier="noise",
            envelope_cutoff_hz=cut, interaction_decay_db=8.0, **base)))

    # Pulsatile carrier at two synchronisation levels. Included because the
    # carrier changes the character of the percept more than any single
    # parameter, and which one a listener recognises is an open question.
    for sync, tag in ((1.0, "tight"), (0.5, "loose")):
        out.append((f"pulse_{tag}", SimulatorConfig(
            n_channels=22, n_selected=8, carrier="pulse", synchronization=sync,
            envelope_cutoff_hz=300.0, interaction_decay_db=8.0, **base)))

    # Tone carrier: cleaner and more musical than noise.
    out.append(("tone22", SimulatorConfig(
        n_channels=22, n_selected=8, carrier="tone",
        envelope_cutoff_hz=300.0, interaction_decay_db=8.0, **base)))

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True,
                    help="speech or music clip to simulate")
    ap.add_argument("--implant-ear", choices=["left", "right"], required=True)
    ap.add_argument("-o", "--output", type=Path, default=Path("pool"))
    ap.add_argument("--seconds", type=float, default=6.0,
                    help="clip length; short keeps each trial brief")
    ap.add_argument("--balance-db", type=float, default=0.0,
                    help="implant-ear level offset from calibration")
    ap.add_argument("--min-distance", type=float, default=0.08,
                    help="drop candidates closer than this to one already kept. "
                         "A trial between two indistinguishable candidates costs "
                         "a minute of scarce listening time and returns nothing.")
    args = ap.parse_args()

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    assignment = EarAssignment(implant_ear=Ear(args.implant_ear))

    src = load_audio(args.source, target_rate=SR, mono=True).samples
    src = src[: int(args.seconds * SR)]

    configs = candidate_configs()
    print(f"rendering {len(configs)} candidates from {args.source.name}")

    entries, audio = [], []
    for i, (name, cfg) in enumerate(configs):
        sim = simulate(src, SR, cfg).audio
        audio.append(sim)
        d = build_dichotic(
            src, sim, SR, assignment,
            mode=PresentationMode.ALTERNATING, segment_ms=500,
            implant_target_lufs=-23.0 + args.balance_db,
            acoustic_target_lufs=-23.0,
        )
        fname = f"cand_{name}.wav"
        save_audio(out / fname, Audio(d.samples, SR))
        entries.append({
            "index": i, "name": name, "file": fname,
            "config": {k: v for k, v in vars(cfg).items()},
            "duration_s": round(d.duration_s, 2),
        })
        print(f"  {i + 1:2d}/{len(configs)}  {fname}")

    # Pairwise perceptual distance, on channel envelopes rather than waveforms:
    # envelopes are what an implant transmits, so two signals with matching
    # envelopes sound alike through one however different their samples look.
    n = len(audio)
    dist = [[0.0] * n for _ in range(n)]
    print("computing pairwise distances...")
    for i, j in itertools.combinations(range(n), 2):
        d = float(envelope_distance(audio[i], audio[j], SR))
        dist[i][j] = dist[j][i] = d

    # Greedily keep candidates that are audibly distinct from everything kept
    # so far. Curating this by hand does not scale and gets it wrong: several
    # parameters that look independent on paper turn out to be inseparable in
    # the envelope domain, which is the domain the listener judges in.
    keep: list[int] = []
    for i in range(n):
        if all(dist[i][j] >= args.min_distance for j in keep):
            keep.append(i)
    dropped = [entries[i]["name"] for i in range(n) if i not in keep]
    if dropped:
        print(f"\npruned {len(dropped)} indistinguishable candidate(s): "
              f"{', '.join(dropped)}")
        for i in range(n):
            if i not in keep:
                (out / entries[i]["file"]).unlink(missing_ok=True)
        entries = [entries[i] for i in keep]
        for new_idx, e in enumerate(entries):
            e["index"] = new_idx
        dist = [[dist[i][j] for j in keep] for i in keep]
        n = len(keep)

    flat = [dist[i][j] for i, j in itertools.combinations(range(n), 2)]
    (out / "pool.json").write_text(json.dumps({
        "source": args.source.name,
        "sample_rate": SR,
        "implant_ear": assignment.implant_ear.value,
        "balance_db": args.balance_db,
        "candidates": entries,
        "distances": dist,
    }, indent=2, default=str))

    print(f"\nwrote {out}/pool.json")
    print(f"  distance spread: min {min(flat):.3f}  median "
          f"{sorted(flat)[len(flat) // 2]:.3f}  max {max(flat):.3f}")
    if min(flat) > 0.05:
        print("  every pair is audibly distinct - good")
    else:
        near = sum(1 for d in flat if d < 0.05)
        print(f"  WARNING: {near} pair(s) nearly identical; those trials will "
              f"cost a minute and return nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
