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
    """A short synthetic phrase: a repeating figure with clear onsets.

    **Prefer real speech via ``--source`` where possible.** The first
    calibration session with this synthetic figure surfaced two problems that
    are worth recording here rather than rediscovering:

    Sustained tonal stimuli are a poor choice for listeners with hearing loss:
    they can provoke or interact with tinnitus, which contaminates exactly the
    localisation judgement a balance task measures. And a cochlear implant
    renders resonance as buzzing, so a resonant stimulus is both uncomfortable
    and a weak probe.

    Notes here therefore decay fast and carry broadband onsets rather than
    ringing. It remains a fallback: speech is the better stimulus for balance
    work, and it is what listeners find easiest to judge.
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
        # Fast decay and a short noise transient at onset: less ringing, so less
        # resonance for the implant to turn into buzzing.
        env = np.exp(-12.0 * local / note_len) * (1 - np.exp(-400 * local))
        rng = np.random.default_rng(i)
        click = rng.standard_normal(n) * np.exp(-300 * local) * 0.3
        out[start:stop] = tone * env + click
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


def _write_readme(out: Path, assignment: EarAssignment) -> None:
    """Plain-language guide, written into the folder itself.

    The mode_*.wav files deliberately play different audio to each ear, and that
    reads as a fault unless it is stated plainly and where someone will actually
    look. Written for the listener, not the investigator - no jargon.
    """
    implant = assignment.implant_ear.value.upper()
    acoustic = assignment.acoustic_ear.value.upper()
    (out / "READ-ME-FIRST.txt").write_text(f"""CALIBRATION SESSION - what each file is
=======================================

Setup: implant in the {implant} ear, hearing aid in the {acoustic} ear.
So: {implant} channel -> implant.  {acoustic} channel -> hearing aid.


IMPORTANT - THE FILES ARE NOT ALL "SAME SOUND BOTH EARS"
--------------------------------------------------------

Some files deliberately play DIFFERENT audio to each ear. That is not a
fault. It is the entire point of the exercise.


1. channel_check.wav        (5.5s)  -- run this first
   Tests whether your audio path keeps the ears separate at all.

     0.0-1.5s   LEFT ear only  (low tone)
     2.0-3.5s   RIGHT ear only (high tone)
     4.0-5.5s   both ears, different pitch each side

   If both tones arrive in both ears, that audio path mixes to mono and
   cannot be used for anything else here.


2. balance_*.wav            (6s each)  -- SAME sound in both ears
   Seven files, same melody both sides, {implant.lower()} side offset by a set
   amount. Find the one that sits in the middle of your head.
   Play them in a random order, not from lowest to highest.


3. practice_*.wav           -- SAME sound in both ears
   Three files, one per presentation style. Identical audio on both sides.
   These are just to get used to how each style feels:

     practice_simultaneous  both ears at once
     practice_alternating   swaps ear every half second
     practice_sequential    one ear, pause, then the other

   Nothing to judge. Just notice which one feels comfortable.


4. mode_*.wav               -- DIFFERENT sound in each ear, ON PURPOSE
   The real task, in the same three styles.

     {implant} ear (implant)      the ordinary melody
     {acoustic} ear (hearing aid)   our GUESS at what the implant makes it
                                sound like

   The {acoustic.lower()} side is MEANT to sound electronic, buzzy and strange.
   It is a simulation of implant hearing. If it sounded the same as the
   {implant.lower()} side there would be nothing to compare.

   The question is: does the strange {acoustic.lower()}-side sound match what
   the {implant.lower()} side sounds like through the implant?

   And which of the three styles made that easiest to judge?


If anything is uncomfortably loud, stop and turn it down before going on.
You can stop at any point, for any reason. "They sound the same" and
"I don't know" are both real, useful answers.

Full instructions: docs/CALIBRATION-SESSION.md
""")


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

    # Practice files first: the SAME audio in both ears. These separate
    # learning the mechanics - which ear is playing, is the switching
    # comfortable - from the actual task of comparing a source against a
    # simulation. Without them a listener meets an unfamiliar interaction and an
    # unfamiliar judgement at the same moment, and confusion about one reads as
    # difficulty with the other.
    for mode in PresentationMode:
        d = build_dichotic(src, src, SR, assignment, mode=mode, segment_ms=500)
        name = f"practice_{mode.value}.wav"
        save_audio(out / name, Audio(d.samples, SR))
        manifest.setdefault("part2_practice", []).append({
            "file": name, "mode": mode.value,
            "content": "identical audio in both ears - for learning the mechanics",
            "duration_s": round(d.duration_s, 2),
        })
        print(f"  {name}  (practice, identical both ears)")

    for mode in PresentationMode:
        d = build_dichotic(src, sim, SR, assignment, mode=mode, segment_ms=500)
        name = f"mode_{mode.value}.wav"
        save_audio(out / name, Audio(d.samples, SR))
        manifest["part2_modes"].append({
            "file": name, "mode": mode.value,
            "implant_ear_hears": "the clean source",
            "acoustic_ear_hears": "a CI SIMULATION of it - it is MEANT to sound "
                                  "electronic and different. That is the thing "
                                  "being judged.",
            "duration_s": round(d.duration_s, 2),
            "ear_overlap_pct": round(float(np.mean(
                (np.abs(d.samples[0]) > 1e-4) & (np.abs(d.samples[1]) > 1e-4)
            ) * 100), 1),
        })
        print(f"  {name}  ({d.duration_s:.1f}s)")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    _write_readme(out, assignment)
    print(f"\nWrote {out}/ - see docs/CALIBRATION-SESSION.md for how to run it.")
    print("Play these from her phone over her normal Bluetooth stream.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
