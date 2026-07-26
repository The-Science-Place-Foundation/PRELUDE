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
import hashlib
import itertools
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from prelude.audio import Audio, load_audio, save_audio
from prelude.ci_sim import SimulatorConfig, simulate
from prelude.fitting import envelope_distance
from prelude.study import Ear, EarAssignment, PresentationMode, build_dichotic

SR = 20000


def candidate_configs() -> list[tuple[str, SimulatorConfig]]:
    """A spread of plausible devices, chosen to be audibly distinct.

    **A broad sweep is the wrong shape once an anchor is known.** An
    information-maximising sampler asks whichever comparison best separates its
    hypotheses, not whichever sounds best - so over a pool that spans the whole
    space, most trials compare two configurations that are both wrong. A
    listener experiences that as the simulations getting steadily worse, which
    is exactly what was reported after the first real session.

    Once a configuration is known to be close, the pool should cluster around
    it: fine variation near the anchor, with a few distant options retained so
    the fit can still be pulled away if the anchor is wrong.

    Spread matters more than realism at this stage. If two candidates differ
    only in a way the listener cannot hear, the trial comparing them costs a
    minute and returns nothing. These vary the parameters that dominate the
    percept - channel count, how many channels survive peak picking, carrier,
    envelope bandwidth, and current spread.

    Defaults elsewhere follow a Cochlear Nucleus platform: 22 electrodes,
    ACE-style peak picking, 900 pps.
    """
    base = dict(low_freq=300.0, high_freq=8500.0, seed=0)
    out: list[tuple[str, SimulatorConfig]] = []

    # ANCHOR: a Cochlear Nucleus platform running ACE - 22 electrodes, 8
    # maxima, 900 pps. The listener independently picked this configuration as
    # the most accurate of everything played, without knowing what any of them
    # were, which is the strongest signal available so far.
    anchor = dict(n_channels=22, n_selected=8, carrier="noise",
                  envelope_cutoff_hz=300.0, interaction_decay_db=8.0,
                  stimulation_rate_hz=900.0, **base)
    out.append(("anchor", SimulatorConfig(**anchor)))

    # Fine variation around the anchor: one parameter moved at a time, so a
    # preference points at a parameter rather than at an unattributable blend.
    for n_sel in (6, 10, 12):
        out.append((f"maxima{n_sel}", SimulatorConfig(**{**anchor, "n_selected": n_sel})))
    for rate in (500.0, 1800.0):
        out.append((f"rate{int(rate)}", SimulatorConfig(**{**anchor, "stimulation_rate_hz": rate})))
    for db in (4.0, 16.0):
        out.append((f"spread{int(db)}", SimulatorConfig(**{**anchor, "interaction_decay_db": db})))
    for cut in (80.0, 900.0):
        out.append((f"env{int(cut)}", SimulatorConfig(**{**anchor, "envelope_cutoff_hz": cut})))
    for carrier in ("pulse", "tone"):
        out.append((f"carrier_{carrier}", SimulatorConfig(**{**anchor, "carrier": carrier})))

    # A few distant options kept deliberately, so the fit can still be pulled
    # away if the anchor turns out to be wrong. Without these the pool could
    # only ever confirm its own starting point.
    for n in (6, 8, 12, 16):
        out.append((f"ch{n:02d}", SimulatorConfig(**{**anchor, "n_channels": n, "n_selected": n})))

    # Retained because the listener has already been asked about them.
    # Dropping a configuration that appears in a recorded judgement orphans
    # that judgement: it can no longer be scored against the pool, and the
    # listening time that produced it is simply lost. Candidates may be added
    # freely; removing one has a cost paid in someone else's evenings.
    out.append(("maxima4", SimulatorConfig(**{**anchor, "n_selected": 4})))
    out.append(("carrier_pulse_loose",
                SimulatorConfig(**{**anchor, "carrier": "pulse", "synchronization": 0.5})))

    return out


def _archive_existing(out: Path) -> None:
    """Move any existing pool aside instead of overwriting it.

    **A pool is not scratch output.** It is the reference every recorded
    judgement points at: a session stores which candidates were compared, so
    discarding the pool discards the meaning of the sessions scored against it.
    Regenerating over the top of one already orphaned four of five real
    judgements from a listener who does not have unlimited evenings.

    Archives are never pruned. They are small next to what they protect.
    """
    if not out.exists() or not any(out.iterdir()):
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = out.parent / "archive" / f"{out.name}-{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(out), str(dest))
    print(f"archived the previous pool to {dest}")


def _config_id(cfg: SimulatorConfig) -> str:
    """Short stable hash of the parameters that determine what is heard.

    Two candidates with the same id are the same sound regardless of what
    either pool called them, which is what lets a judgement recorded against
    one pool be scored against another.
    """
    keys = ("n_channels", "n_selected", "carrier", "stimulation_rate_hz",
            "envelope_cutoff_hz", "interaction_decay_db", "synchronization",
            "low_freq", "high_freq", "spacing")
    g = vars(cfg)
    blob = json.dumps({k: g.get(k) for k in keys}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


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
    ap.add_argument("--min-distance", type=float, default=0.02,
                    help="drop candidates closer than this to one already kept. "
                         "Deliberately low: it should catch near-duplicates, not "
                         "decide which parameters matter. See the note below.")
    args = ap.parse_args()

    out = args.output
    _archive_existing(out)
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
            # Identity follows the configuration, not the label. Names are for
            # humans and get edited; a recorded judgement has to stay
            # resolvable when they do.
            "config_id": _config_id(cfg),
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

    # Greedily drop near-duplicates only.
    #
    # The threshold is deliberately low. An earlier run pruned at 0.08 and
    # discarded stimulation rate, interaction decay and envelope bandwidth as
    # "indistinguishable" - but the measure could not resolve those parameters
    # in the first place, so the result said nothing about whether a listener
    # could hear them. A distance below threshold means the metric cannot
    # separate two candidates; it does not mean a person cannot. Deciding on
    # the listener's behalf, using an instrument known to be blind in that
    # range, removes exactly the comparisons that would have settled the
    # question.
    #
    # Pruning is for genuine duplicates. Which parameters matter is for the
    # listener to answer.
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
