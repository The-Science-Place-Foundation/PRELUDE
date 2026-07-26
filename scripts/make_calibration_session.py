#!/usr/bin/env python3
# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Generate the audio for a first calibration session.

Produces two things:

**Part 1 - balance.** Identical signal to both ears at several offsets. The
listener finds the offset at which the sound sits centred. Electric and acoustic
loudness growth differ so much that equal measured levels are not equally loud,
so without this every later judgement is partly a judgement about level.

**Part 2 - presentation mode.** The same source/simulation pair rendered
simultaneously, alternating, and sequentially. The listener says which lets them
compare most easily. This decides the interaction model for everything built
afterwards, so it is worth settling before writing an interface.

All stimuli are synthetic or drawn from the listener's own material - nothing
here contains anyone else's voice.

Usage
-----
    python scripts/make_calibration_session.py --implant-ear right -o calib/
    python scripts/make_calibration_session.py --implant-ear right \
        --source path/to/music.wav -o calib/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from prelude.audio import Audio, load_audio, save_audio
from prelude.ci_sim import SimulatorConfig, simulate
from prelude.study import Ear, EarAssignment, PresentationMode, build_dichotic

SR = 20000


def synth_source(seconds: float = 6.0, sample_rate: int = SR) -> np.ndarray:
    """A short synthetic phrase: a repeating melodic figure with clear onsets.

    Chosen over speech deliberately - it has unambiguous pitch and rhythm, so a
    listener can describe what changed without needing words for phonetics, and
    it contains no one's voice.
    """
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    notes = [262, 330, 392, 523, 392, 330]  # C E G C G E
    note_len = seconds / len(notes)
    out = np.zeros_like(t)
    for i, f in enumerate(notes):
        start, stop = int(i * note_len * sample_rate), int((i + 1) * note_len * sample_rate)
        n = stop - start
        local = np.arange(n) / sample_rate
        tone = sum(np.sin(2 * np.pi * f * k * local) / k for k in (1, 2, 3, 4))
        env = np.exp(-3.0 * local / note_len) * (1 - np.exp(-200 * local))
        out[start:stop] = tone * env
    return out / (np.abs(out).max() + 1e-12) * 0.5


def _channel_check(sample_rate: int) -> np.ndarray:
    """Left-only, then right-only, then both with a different pitch per side.

    Left channel is index 0 and right is index 1, matching
    :meth:`prelude.study.dichotic.Ear.channel_index`.
    """
    def tone(freq: float, dur: float) -> np.ndarray:
        t = np.arange(int(dur * sample_rate)) / sample_rate
        fade = np.minimum(1.0, np.minimum(t * 20, (dur - t) * 20))
        return 0.25 * np.sin(2 * np.pi * freq * t) * fade

    gap = np.zeros(int(0.5 * sample_rate))
    silent = np.zeros(int(1.5 * sample_rate))
    left = np.concatenate([tone(440, 1.5), gap, silent, gap, tone(440, 1.5)])
    right = np.concatenate([silent, gap, tone(880, 1.5), gap, tone(880, 1.5)])
    return np.stack([left, right])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--implant-ear", choices=["left", "right"], required=True,
                    help="which ear has the implant. Getting this wrong inverts "
                         "the experiment silently.")
    ap.add_argument("-o", "--output", type=Path, default=Path("calibration"))
    ap.add_argument("--source", type=Path,
                    help="optional real audio to use instead of the synthetic figure")
    ap.add_argument("--offsets", type=float, nargs="+",
                    default=[-9.0, -6.0, -3.0, 0.0, 3.0, 6.0, 9.0],
                    help="balance offsets in dB applied to the implant ear")
    args = ap.parse_args()

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    assignment = EarAssignment(implant_ear=Ear(args.implant_ear))

    if args.source:
        src = load_audio(args.source, target_rate=SR, mono=True).samples[: SR * 8]
        source_name = args.source.name
    else:
        src = synth_source()
        source_name = "synthetic melodic figure"

    manifest: dict = {
        "how_to_use": "See docs/CALIBRATION-SESSION.md. Copy this whole folder "
                      "to her phone and play the files from it.",
        "assignment": assignment.describe(),
        "implant_ear": assignment.implant_ear.value,
        "acoustic_ear": assignment.acoustic_ear.value,
        "source": source_name,
        "sample_rate": SR,
        "part1_balance": [],
        "part2_modes": [],
    }

    # -- Part 0: channel check ---------------------------------------------
    # Verifies that whatever audio path is in use actually keeps the ears
    # separate. Some streaming accessories downmix to mono, in which case both
    # ears receive the same blend while everything still sounds plausible, and
    # every dichotic comparison silently becomes meaningless. Thirty seconds
    # here prevents a whole category of invisible failure.
    print("Part 0 - channel check")
    check = _channel_check(SR)
    save_audio(out / "channel_check.wav", Audio(check, SR))
    manifest["part0_channel_check"] = {
        "file": "channel_check.wav",
        "0.0-1.5s": f"{assignment.acoustic_ear.value} ear only (440 Hz)",
        "2.0-3.5s": f"{assignment.implant_ear.value} ear only (880 Hz)",
        "4.0-5.5s": "both ears, different pitch each side",
    }
    print("  channel_check.wav")

    # -- Part 1: balance ----------------------------------------------------
    # The same signal both ears, implant side offset by a known amount. The
    # listener picks the file that sits centred; that offset then becomes the
    # per-ear level difference for every later session.
    print("Part 1 - balance")
    for db in args.offsets:
        d = build_dichotic(
            src, src, SR, assignment,
            mode=PresentationMode.SIMULTANEOUS,
            implant_target_lufs=-23.0 + db,
            acoustic_target_lufs=-23.0,
        )
        name = f"balance_{db:+.0f}dB.wav".replace("+", "plus_").replace("-", "minus_")
        save_audio(out / name, Audio(d.samples, SR))
        manifest["part1_balance"].append({"file": name, "implant_offset_db": db})
        print(f"  {name}")

    # -- Part 2: presentation mode -----------------------------------------
    # Source to the implant ear, a simulation of it to the acoustic ear, in each
    # of the three modes. Same content throughout, so the only variable is how
    # the two are laid out in time.
    print("\nPart 2 - presentation mode")
    # Noise carrier, not pulse, for listening material.
    #
    # The pulse carrier models the stimulation pattern faithfully and scores
    # better on envelope correlation, but its crest factor is around 33 dB
    # against 16 dB for noise. That much peakiness cannot reach a normal
    # loudness target without breaching the true-peak ceiling, so the result
    # arrives roughly 12 dB quiet and sounds clicky. A listener does not
    # perceive individual pulses at 900 pps either - they integrate.
    #
    # The pulsatile structure is preserved where it belongs, in the
    # electrodogram. Resynthesis exists to render the percept audibly, which is
    # a different job.
    #
    # Defaults here match a Cochlear Nucleus platform: 22 electrodes, ACE-style
    # 8-of-22 peak picking, 900 pps.
    sim = simulate(src, SR, SimulatorConfig(
        n_channels=22, n_selected=8, carrier="noise",
        stimulation_rate_hz=900.0, seed=0,
    )).audio

    for mode in PresentationMode:
        d = build_dichotic(src, sim, SR, assignment, mode=mode, segment_ms=500)
        name = f"mode_{mode.value}.wav"
        save_audio(out / name, Audio(d.samples, SR))
        manifest["part2_modes"].append({
            "file": name, "mode": mode.value,
            "duration_s": round(d.duration_s, 2),
            "ear_overlap_pct": round(float(np.mean(
                (np.abs(d.samples[0]) > 1e-4) & (np.abs(d.samples[1]) > 1e-4)
            ) * 100), 1),
        })
        print(f"  {name}  ({d.duration_s:.1f}s)")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {out}/ - see docs/CALIBRATION-SESSION.md for how to run it.")
    print("Play these from her phone over her normal Bluetooth stream.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
