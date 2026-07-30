#!/usr/bin/env python3
# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.

"""Where does a candidate pool's discriminative information live, and can the
listener's acoustic ear receive it?

**Why this matters more here than in an ordinary study.** In the dichotic
design the implanted ear hears the unmodified source and the *acoustic* ear
hears the simulation. So every judgement about a simulation is made through
the acoustic ear alone. In any frequency region where that ear has no usable
hearing, no candidate can be distinguished from any other however faithful the
simulation is - and the fit will read that as "these are the same", which is
indistinguishable from "the simulator cannot tell them apart".

That is not hypothetical here. Simulation against the previous pool showed
several candidates were unrecoverable, and the open question was whether the
distance metric was too blunt or the parameters genuinely did not matter. This
adds a third possibility that has to be excluded first: **she may not be able
to hear the region where they differ.**

What this can and cannot tell you
---------------------------------
It CAN show the *shape* of the problem: which analysis bands sit in regions of
severe loss, and what share of each candidate pair's difference lives there.

It CANNOT tell you absolute audibility. That needs the presentation level in
dB SPL at the eardrum, which depends on device volume, the streaming path and
the hearing aid's own gain - none of which are known. Treat "inaudible" here
as "at risk", not as measured fact. The honest test is behavioural: if she
cannot discriminate a pair whose difference lives entirely in a dead region,
that is consistent; if she *can*, the audiogram is not the explanation.

Usage
-----
    python scripts/audibility_check.py --pool pool_new
    python scripts/audibility_check.py --pool pool_new --profile config/device_profile.yaml
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from prelude.audio import load_audio
from prelude.ci_sim import SimulatorConfig, simulate
from prelude.ci_sim.filterbank import design_filterbank

#: Audiometric thresholds above which a frequency is conventionally described
#: as profoundly impaired. Not a cliff - loudness grows above threshold - but a
#: usable line for "at risk of contributing nothing".
PROFOUND_DB_HL = 90.0
SEVERE_DB_HL = 70.0


def _load_audiogram(profile: Path) -> dict[float, float] | None:
    """Thresholds in dB HL for the acoustic ear, if the profile has them.

    Parsed without a YAML dependency: the profile is a flat block of
    ``frequency: threshold`` under ``audiogram_db_hl``.
    """
    if not profile.is_file():
        return None
    out: dict[float, float] = {}
    inside = False
    for line in profile.read_text().splitlines():
        if line.strip().startswith("audiogram_db_hl:"):
            inside = True
            continue
        if inside:
            stripped = line.strip()
            if not line.startswith("    ") or not stripped:
                if stripped and not line.startswith("    "):
                    break
                continue
            if ":" not in stripped:
                break
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if not key.replace(".", "").isdigit():
                break
            if value:
                try:
                    out[float(key)] = float(value)
                except ValueError:
                    pass
    return out or None


def _interp_threshold(audiogram: dict[float, float], freqs: np.ndarray) -> np.ndarray:
    """Thresholds at arbitrary frequencies, log-interpolated between octaves.

    Held flat beyond the measured range rather than extrapolated: an audiogram
    stops at 8 kHz because that is where testing stops, not because hearing
    improves past it.
    """
    known = np.array(sorted(audiogram))
    values = np.array([audiogram[f] for f in known])
    return np.interp(np.log2(freqs), np.log2(known), values)


def band_difference_profile(pool_dir: Path, source: Path, sample_rate: int = 20000,
                            seconds: float = 6.0) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Per-band RMS envelope difference for every candidate pair.

    Returns candidate names, band centre frequencies, and an array of shape
    ``(n_pairs, n_bands)`` holding where each pair's difference lives.
    """
    pool = json.loads((pool_dir / "pool.json").read_text())
    names = [c["name"] for c in pool["candidates"]]
    x = load_audio(source, target_rate=sample_rate).samples[: int(sample_rate * seconds)]

    envs = []
    for cand in pool["candidates"]:
        cfg_dict = {k: v for k, v in cand["config"].items()
                    if k in SimulatorConfig.__dataclass_fields__}
        if isinstance(cfg_dict.get("deactivated_electrodes"), list):
            cfg_dict["deactivated_electrodes"] = tuple(cfg_dict["deactivated_electrodes"])
        if isinstance(cfg_dict.get("band_edges"), list):
            cfg_dict["band_edges"] = cfg_dict["band_edges"]
        result = simulate(x, sample_rate, SimulatorConfig(**cfg_dict))
        envs.append(result.audio)

    # Analyse every candidate through one common bank, so the bands are
    # comparable across candidates with different channel counts.
    n_bands = 24
    fb = design_filterbank(sample_rate=sample_rate, n_channels=n_bands,
                           low_freq=250.0, high_freq=min(8000.0, sample_rate / 2 - 500))
    banded = [np.sqrt((fb.apply(e) ** 2).mean(axis=1)) for e in envs]

    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = banded[i], banded[j]
            denom = np.maximum(a, b)
            denom[denom == 0] = 1.0
            pairs.append(np.abs(a - b) / denom)
    return names, fb.center_freqs, np.array(pairs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", type=Path, default=Path("pool_new"))
    ap.add_argument("--source", type=Path, default=Path("private/stimuli/speech_clip.wav"))
    ap.add_argument("--profile", type=Path, default=Path("config/device_profile.yaml"))
    args = ap.parse_args()

    audiogram = _load_audiogram(args.profile)
    names, freqs, pairs = band_difference_profile(args.pool, args.source)

    share = pairs.mean(axis=0)
    share = share / share.sum()

    print(f"\nWhere the pool's discriminative information lives "
          f"({len(names)} candidates, {pairs.shape[0]} pairs)\n")
    print(f"  {'band (Hz)':>12}  {'share of difference':>20}   {'threshold':>10}")
    thresholds = _interp_threshold(audiogram, freqs) if audiogram else None
    for k, f in enumerate(freqs):
        bar = "#" * int(round(share[k] * 200))
        thr = f"{thresholds[k]:6.0f} dB" if thresholds is not None else "     -"
        flag = ""
        if thresholds is not None:
            if thresholds[k] >= PROFOUND_DB_HL:
                flag = "  <- profound"
            elif thresholds[k] >= SEVERE_DB_HL:
                flag = "  <- severe"
        print(f"  {f:12.0f}  {share[k]:8.3f} {bar:<12}  {thr}{flag}")

    if thresholds is None:
        print("\n  No audiogram in the profile, so nothing can be said about")
        print("  audibility. Fill in `audiogram_db_hl` in "
              f"{args.profile} and re-run.")
        print("  Until then, treat every 'these sound the same' result as")
        print("  having an unexcluded explanation.")
        return 0

    at_risk = share[thresholds >= SEVERE_DB_HL].sum()
    profound = share[thresholds >= PROFOUND_DB_HL].sum()
    print("\n  Share of the pool's discriminative information sitting in")
    print(f"    severe-or-worse regions (>={SEVERE_DB_HL:.0f} dB HL): {at_risk:.1%}")
    print(f"    profound regions        (>={PROFOUND_DB_HL:.0f} dB HL): {profound:.1%}")

    if at_risk > 0.5:
        print("\n  MOST of what separates these candidates sits where this ear")
        print("  hears poorly. The pool is asking questions the listener may")
        print("  not be able to answer, and a null result would not mean the")
        print("  candidates are alike. Consider restricting the simulation's")
        print("  range, or weighting the distance metric by audibility.")
    elif at_risk > 0.25:
        print("\n  A substantial minority of the discriminative information is")
        print("  at risk. Worth weighting the distance metric by audibility")
        print("  before concluding anything from a null.")
    else:
        print("\n  Most of the discriminative information is in regions this ear")
        print("  can receive. Audibility is unlikely to be the explanation for")
        print("  a null result.")

    print("\n  Caveat that does not go away: this is a *relative* picture. The")
    print("  absolute presentation level at the eardrum is unknown, and the")
    print("  hearing aid applies its own gain. This bounds the problem; it")
    print("  does not measure it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
