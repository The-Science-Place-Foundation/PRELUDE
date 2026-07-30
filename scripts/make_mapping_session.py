#!/usr/bin/env python3
# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Stimuli for measuring the implant's frequency-place map, and the reference
ear's audibility, without a clinic.

Two things are unobtainable here: the device's frequency allocation table and
any audiogram. Both can be approximated behaviourally, and the approximations
are arguably better suited to this study than the clinical originals.

**Part 1 - band detection in the acoustic ear.** Narrowband bursts to the
acoustic ear alone, at the level the study actually presents. This answers a
question a sound-booth audiogram does not: which bands reach *this ear, through
the hearing aid, over the MFi stream, at the volume in use*. That is the path
every simulation travels, so it is the relevant audibility. It also gates
part 2, since a pitch match needs a probe the reference ear can hear.

**Part 2 - interaural pitch matching.** A narrowband burst to the IMPLANT ear,
then a probe to the acoustic ear, with the listener judging which sounded
higher. A staircase on the probe converges on the frequency the implant percept
matches.

Note what part 2 does *not* involve: the simulator. The burst is plain audio
sent to the implant ear, so the listener's own device performs its own
allocation. That is the point - it measures the real implant rather than our
model of it. If the allocation were tonotopically faithful the match would sit
near the input frequency; a systematic shift is the frequency-place mismatch,
and it constrains ``low_freq``, ``high_freq`` and ``band_edges`` directly.

Stimulus choice, and why not pure tones
---------------------------------------
**Narrowband noise bursts, not sustained pure tones.** This is a deliberate
departure from the obvious design. Sustained tonal stimuli provoke tinnitus in
listeners with hearing loss, and an implant renders resonance as buzzing - both
were observed in the first calibration session here, and they made a fixed
sweep of tones unusable. A third-octave noise burst is nearly as
place-specific, far less provocative, and short.

Everything is brief (400 ms), raised-cosine ramped to avoid spectral splatter
from hard edges, and separated by silence. Every file passes through
``prepare_for_playback``.

Usage
-----
    python scripts/make_mapping_session.py --implant-ear right -o pool_new
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

from prelude.audio import Audio, prepare_for_playback, save_audio
from prelude.study import Ear, EarAssignment

SR = 20000

#: Centre frequencies for the audibility screen, third-octave spaced over the
#: range the simulator uses. Seven points is enough to see the shape of a loss
#: without turning a one-minute screen into a chore.
DETECT_HZ = (250.0, 500.0, 1000.0, 2000.0, 3000.0, 4500.0, 6500.0)

#: Frequencies presented to the IMPLANT ear in the pitch match. Kept few and
#: spread: each one costs a staircase, and the shape of the map is what matters
#: rather than fine resolution.
#:
#: The top point is 3 kHz rather than 4 kHz so the ladder has headroom above it.
#: CI frequency-place mismatches are usually *upward* - the array does not reach
#: the apex - so a reference near the top of the probe range pins the staircase
#: against its ceiling. Simulated at 4 kHz with a 12-semitone shift, 198 of 200
#: runs failed to resolve for exactly that reason.
MATCH_HZ = (500.0, 1500.0, 3000.0)

#: Probe frequencies offered to the acoustic ear, **eighth-octave** steps. The
#: staircase walks this ladder rather than a continuous scale, so every probe is
#: a pre-rendered file and the phone never synthesises anything.
#:
#: Eighth rather than quarter octave because a quarter-octave ladder has a
#: 3-semitone floor, and simulation showed 3 semitones of median error even when
#: the true match sat exactly on a rung - enough to blur the size of a mismatch
#: this is meant to measure. The extra files cost disk, which is free here.
#:
#: Top end bounded by Nyquist: a third-octave band around 8 kHz reaches 8977 Hz,
#: inside the 9800 Hz usable limit at this sample rate.
PROBE_HZ = tuple(round(125.0 * (2 ** (k / 8)), 1) for k in range(49))

BURST_MS = 400
RAMP_MS = 25
GAP_MS = 350


def _burst(center_hz: float, sample_rate: int = SR, ms: int = BURST_MS,
           seed: int = 0) -> np.ndarray:
    """One third-octave noise burst, ramped.

    Ramps matter more than they look: a hard-gated burst splatters energy across
    the spectrum, which would defeat the whole purpose of a place-specific
    stimulus.
    """
    n = int(sample_rate * ms / 1000)
    rng = np.random.default_rng(int(center_hz) * 1000 + seed)
    x = rng.standard_normal(n)

    lo = center_hz / (2 ** (1 / 6))
    hi = center_hz * (2 ** (1 / 6))
    nyq = sample_rate / 2
    if hi >= nyq * 0.98:
        hi = nyq * 0.98
    if lo >= hi:
        raise ValueError(f"band around {center_hz} Hz does not fit below Nyquist")
    sos = butter(4, [lo / nyq, hi / nyq], btype="band", output="sos")
    x = sosfiltfilt(sos, x)

    ramp = int(sample_rate * RAMP_MS / 1000)
    win = np.ones(n)
    edge = 0.5 * (1 - np.cos(np.pi * np.arange(ramp) / ramp))
    win[:ramp] = edge
    win[-ramp:] = edge[::-1]
    x = x * win
    peak = np.abs(x).max()
    return x / peak * 0.5 if peak > 0 else x


def _one_ear(mono: np.ndarray, ear: Ear) -> np.ndarray:
    """Place a mono signal in one channel, silence in the other.

    Stereo is preserved end to end elsewhere in this project for exactly this
    reason: a stimulus meant for one ear must not leak into the other, or the
    measurement is of both ears together.
    """
    out = np.zeros((2, mono.shape[0]))
    out[ear.channel_index] = mono
    return out


def _silence(ms: int) -> np.ndarray:
    return np.zeros(int(SR * ms / 1000))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--implant-ear", choices=["left", "right"], required=True)
    ap.add_argument("-o", "--output", type=Path, default=Path("pool_new"))
    ap.add_argument("--target-lufs", type=float, default=-26.6,
                    help="presentation level. Default matches the candidate pool, "
                         "because the point is to measure audibility at the level "
                         "the study actually uses.")
    args = ap.parse_args()

    implant = Ear(args.implant_ear)
    assignment = EarAssignment(implant_ear=implant)
    acoustic = assignment.acoustic_ear
    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "sample_rate": SR,
        "implant_ear": implant.value,
        "acoustic_ear": acoustic.value,
        "target_lufs": args.target_lufs,
        "burst_ms": BURST_MS,
        "stimulus": "third-octave noise burst",
        "why_not_tones": (
            "sustained tonal stimuli provoke tinnitus in listeners with hearing "
            "loss, and an implant renders resonance as buzzing; both were seen "
            "in the first calibration session here"
        ),
        "detect": [],
        "match": [],
        "probe": [],
    }

    def write(name: str, stereo: np.ndarray) -> dict:
        audio, report = prepare_for_playback(stereo, SR, target_lufs=args.target_lufs)
        save_audio(out / name, Audio(audio, SR))
        return {"file": name,
                "output_lufs": round(report.output_lufs, 2),
                "limited": bool(report.limited)}

    print(f"level: {args.target_lufs} LUFS   implant={implant.value} "
          f"acoustic={acoustic.value}")

    # ---- part 1: audibility of the acoustic ear ------------------------
    print(f"\ndetection screen, {len(DETECT_HZ)} bands to the "
          f"{acoustic.value} (acoustic) ear:")
    for f in DETECT_HZ:
        # Two bursts, so a momentary distraction does not read as absence.
        mono = np.concatenate([_burst(f), _silence(GAP_MS), _burst(f, seed=1)])
        rec = write(f"map_detect_{int(f)}.wav", _one_ear(mono, acoustic))
        rec["center_hz"] = f
        manifest["detect"].append(rec)
        print(f"  {rec['file']:26s} {f:7.0f} Hz  {rec['output_lufs']:.2f} LUFS")

    # ---- part 2a: implant-ear references -------------------------------
    print(f"\npitch-match references, to the {implant.value} (implant) ear:")
    for f in MATCH_HZ:
        mono = np.concatenate([_burst(f), _silence(GAP_MS), _burst(f, seed=1)])
        rec = write(f"map_ci_{int(f)}.wav", _one_ear(mono, implant))
        rec["center_hz"] = f
        manifest["match"].append(rec)
        print(f"  {rec['file']:26s} {f:7.0f} Hz  {rec['output_lufs']:.2f} LUFS")

    # ---- part 2b: acoustic-ear probe ladder ----------------------------
    print(f"\nprobe ladder, to the {acoustic.value} (acoustic) ear, "
          f"{len(PROBE_HZ)} quarter-octave steps:")
    for f in PROBE_HZ:
        if f * (2 ** (1 / 6)) >= SR / 2 * 0.98:
            print(f"  skipped {f:.0f} Hz - band would cross Nyquist")
            continue
        mono = np.concatenate([_burst(f), _silence(GAP_MS), _burst(f, seed=1)])
        rec = write(f"map_probe_{int(round(f))}.wav", _one_ear(mono, acoustic))
        rec["center_hz"] = f
        manifest["probe"].append(rec)
    print(f"  wrote {len(manifest['probe'])} probes "
          f"({manifest['probe'][0]['center_hz']:.0f} - "
          f"{manifest['probe'][-1]['center_hz']:.0f} Hz)")

    (out / "mapping.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nwrote {out}/mapping.json")

    peaks = [r for r in manifest["detect"] + manifest["match"] + manifest["probe"]
             if r["limited"]]
    if peaks:
        print(f"  note: {len(peaks)} file(s) engaged the true-peak limiter. Their "
              f"level is at the ceiling, not the target - check before "
              f"interpreting thresholds.")
    else:
        print("  no file needed peak limiting, so every level is the requested one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
