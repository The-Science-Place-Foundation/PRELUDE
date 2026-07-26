# First Calibration Session — Guide

**Purpose:** settle two things that everything else depends on, before any
interface is built.

1. **Loudness balance** between the two ears.
2. **Which presentation mode** lets the listener compare most easily.

**Time:** about 20 minutes, with breaks. **Equipment:** her phone, her normal
Bluetooth stream, both devices.

There is no software to install. Play the files like any other audio.

---

## Before you start

**Generate the files:**

```bash
python scripts/make_calibration_session.py --implant-ear right -o calibration/
```

> ⚠️ **Get `--implant-ear` right.** If it is wrong, the simulation goes to the
> implanted ear and the source to the acoustic ear. The experiment inverts and
> the data still looks completely normal. Check it twice.

Copy the `calibration/` folder to her phone.

**Set the volume before anything else.** Play `balance_plus_0dB.wav` at her
normal listening level and leave the volume there for the whole session. Every
comparison assumes a fixed playback level; changing it mid-session invalidates
everything before the change.

**Say this, in your own words:** you can stop at any point, for any reason or
none. There are no wrong answers, and "they sound the same" and "I don't know"
are both real, useful answers — in fact they're often the most informative ones.

---

## Part 1 — Loudness balance (about 8 minutes)

Electric and acoustic hearing have very different loudness growth. Matching both
channels to the same measured level does **not** make them equally loud to her.
Until this is calibrated, every later judgement is partly a judgement about which
side is louder.

**Condition: both devices in.**

Play the seven `balance_*.wav` files. Each has the same sound in both ears, with
the implant side offset by a known amount.

For each one ask:

> Does the sound feel like it's sitting in the middle of your head, or pulling to
> one side?

Record: **left / centre / right**, and how strongly.

Play them **in a shuffled order**, not from −9 through +9. A monotonic sweep
invites her to track the pattern rather than judge each one.

**What you're looking for:** the offset where it sits centred. If two adjacent
offsets both feel centred, take the midpoint. If none do, note which direction it
always pulls — that itself is a finding, and means we need a wider range.

**Record the winning offset. Every future session uses it.**

---

## Part 2 — Presentation mode (about 10 minutes)

The core comparison plays a source into the implanted ear and a candidate
simulation into the acoustic ear. There are three ways to lay that out in time,
and which one works best is genuinely an open question for each listener.

**Condition: both devices in.**

| File | What it does |
|---|---|
| `mode_simultaneous.wav` | Both ears at once |
| `mode_alternating.wav` | Switches ear every 0.5 s |
| `mode_sequential.wav` | One ear, pause, then the other |

Play each **twice**, in a shuffled order. After each, ask:

> Could you tell the two sounds apart?
>
> Which was easier — comparing them, or did they blur into one thing?

Then, having heard all three:

> Which one made it easiest to say whether the two matched?

**The specific thing to watch for.** The listener's description of her brain "filling
in" when both devices are on is exactly the risk with **simultaneous**. If the
two signals fuse into one natural-seeming percept, she is reporting on the merged
sound rather than comparing its parts — and it may not feel like a problem from
the inside. Ask directly:

> With that one, did it feel like two sounds you were comparing, or one sound?

If she says "one sound", simultaneous mode is unusable for fitting, however
pleasant it is. That is a real result and worth knowing now rather than after a
hundred trials.

---

## Part 3 — Vocabulary (optional, 5 minutes, only if she has energy)

Skip this if Parts 1 and 2 were tiring. It is the least time-critical part.

Play `mode_sequential.wav` and ask her to describe, in her own words, how the
two halves differ. Write down her **exact wording**, including hedges and
self-corrections.

This matters more than it looks. There is no established vocabulary for
describing electric hearing, so hers becomes the measurement language for the
whole project. If she says a simulation is "too buzzy" or "not sparkly enough",
we need to know what those map to in her experience before we can act on them.

Do not paraphrase into technical terms while recording. "Sounds like a wasp in a
tin can" is better data than "high-frequency distortion".

---

## Recording the data

Copy `docs/lab-notebook/TEMPLATE-session.md` to
`docs/lab-notebook/YYYY-MM-DD-calibration.md` and fill it in.

The three things that must be recorded or the session cannot be used:

1. **The balance offset** in dB, and which ear it favours.
2. **The preferred presentation mode**, and whether simultaneous caused fusion.
3. **Playback volume setting** and streaming path, so a later session can
   reproduce the conditions.

Also record, briefly: time of day, her alertness (1–5), when her audiogram was
last done, and anything surprising.

**Record what went wrong too.** If she got tired at file four, if the balance
never centred, if she found a question confusing — that shapes the next session
more than the clean results do.

### Then run

```bash
python scripts/analyse_calibration.py docs/lab-notebook/YYYY-MM-DD-calibration.md
```

...which does not exist yet. It will once we know what the data looks like —
building the analysis before seeing the first session's shape would be guessing.
For now the notebook entry is the record.

---

## What happens next

The balance offset feeds `implant_target_lufs` / `acoustic_target_lufs` in every
subsequent dichotic stimulus. The mode choice sets the default in
`prelude.study.dichotic` and determines the interaction model of the app.

Then the adaptive fitter takes over: roughly 30–40 forced choices, spread across
several short sittings, to fit the simulator to her hearing.

---

## If something goes wrong

**She can't tell any of them apart.** Genuinely possible and not a failure. It
means the candidate simulations are too similar — we widen the parameter pool and
try again with more distinct options.

**Everything pulls to one ear regardless of offset.** The range is too narrow.
Regenerate with `--offsets -18 -15 -12 -9 -6 -3 0`.

**She gets tired quickly.** Stop. Part 1 alone is a useful session. Fatigued
discrimination data is indistinguishable from a null result, so pushing through
produces numbers that look like data and are not.

**Anything is uncomfortably loud.** Stop immediately and re-check the volume
against `balance_plus_0dB.wav`. Do not continue until it is right.
