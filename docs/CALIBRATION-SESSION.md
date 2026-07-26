# Calibration Session — Guide

Three things this session settles, in priority order:

1. **Is the implant percept layered or substituted?** An architectural question
   about the simulator that no amount of parameter tuning can answer.
2. **The loudness balance** between the two ears.
3. **Which presentation mode** lets the listener compare most easily.

**Time:** 25 minutes including breaks. **Equipment:** her phone, both devices,
nothing else.

Ordered so that if she tires partway, the most valuable result is already in
hand. Stopping early is a normal outcome, not a failed session.

---

## Before you start

### Generate the files

```bash
cd /mnt/UNAS/PRELUDE
python3 scripts/make_calibration_session.py --implant-ear right \
    --source /path/to/a/speech/recording.wav -o calibration
```

> ⚠️ **`--implant-ear` must be correct.** Wrong, and the simulation goes to the
> implanted ear and the source to the acoustic ear. The experiment inverts and
> the data still looks entirely normal. Check it twice.

**Use speech, not tones.** Sustained tonal stimuli are a poor probe for listeners
with hearing loss — they can provoke or interact with tinnitus, which contaminates
exactly the localisation judgement Part 2 depends on. An implant also renders
resonance as buzzing, so a resonant figure is uncomfortable and uninformative. An
audiobook excerpt works well. The synthetic fallback is a last resort.

### Copy the folder to her phone and play it from there

> ⚠️ **Do not use SonoBus, AirPlay, or any network relay.**

A relay adds resampling, buffering and packet loss *on top of* the Bluetooth
codec. Those artefacts are audible, and she cannot separate "this simulation is
wrong" from "this playback is glitching" — so every judgement becomes ambiguous.
A relay is fine for listening to music while you work. It is not fine for a
measurement.

### Set the volume once

Play `balance_plus_0dB.wav` at her normal listening level. **Leave the volume
there for the whole session and write the setting down.** Every comparison
assumes a fixed level; changing it mid-session invalidates everything before the
change, and an unrecorded level means the session cannot be reproduced.

### Say this, in your own words

She can stop at any point, for any reason or none. There are no wrong answers.
**"They sound the same"** and **"I don't know"** are real answers and often the
most informative ones — please don't guess to be helpful.

---

## Part 0 — Channel check (2 minutes)

**Condition: BOTH DEVICES.** Needed — the point is to confirm each ear receives
its own channel.

Play `channel_check.wav` and ask which ear each tone is in.

| Time | Should be heard in |
|---|---|
| 0.0–1.5 s | **left** ear only (low tone) |
| 2.0–3.5 s | **right** ear only (high tone) |
| 4.0–5.5 s | both ears, different pitch each side |

**If both tones arrive in both ears, stop.** That path mixes to mono and cannot
carry anything else in this session. Nothing later would mean anything.

---

## Part 1 — What the implant alone sounds like (5 minutes)

> **Condition: IMPLANT ONLY. Take the hearing aid out.**
> Allow about 30 seconds for her hearing to settle before playing anything.

**This is the highest-value part of the session. Do it while she is fresh.**

Play the **plain source file** — the ordinary speech recording, not a dichotic
file. Then ask:

> Describe what this sounds like now, in your own words.

Let her answer fully before asking the second question:

> Is the original sound still there underneath, with something added on top of
> it? Or has it been replaced by something else entirely?

### Why this question is load-bearing

The simulator is built on a **vocoder**, which *replaces* the fine structure of a
sound: the original is gone, substituted by noise or pulses shaped by its
envelope. If her percept is instead the original *plus* an added layer, the
architecture is wrong in a way no parameter fitting can reach — because a vocoder
does not retain the original to layer anything onto.

**It can only be answered with the hearing aid out.** With both devices in, the
acoustic ear supplies an audible "original underneath" regardless of what the
implant does, so the answer is determined before the question is asked. A previous
session made exactly this mistake, and the result was uninterpretable.

### Recording it

Write her **exact wording**, including hedges and self-corrections. Do not
paraphrase into technical language — *"like a wasp in a tin can"* is better data
than *"high-frequency distortion"*. There is no established vocabulary for
electric hearing, so hers becomes the measurement language for this project.

---

> **Put the hearing aid back in now.** Allow ~30 seconds to settle.
> Everything remaining uses both devices.

---

## Part 2 — Loudness balance (10 minutes)

**Condition: BOTH DEVICES.** Correct here — the task is balancing one against
the other.

Electric and acoustic hearing have very different loudness growth, so matching
both channels to the same measured level does **not** make them equally loud to
her. Until this is calibrated, every later judgement is partly a judgement about
which side is louder.

Play the seven `balance_*.wav` files. Each has the same speech in both ears, with
the implant side offset by a known amount. For each, ask:

> Does it sit in the middle of your head, or pull to one side?

Record **left / centre / right** and how strongly (1–5).

### Three rules that make the difference

**Shuffle the order.** Not −9 through +9. A monotonic sweep invites her to track
the pattern rather than judge each one.

**Repeat at least three offsets**, unannounced, as trials 8–10. Without repeats
there is no way to tell a real balance point from a noisy one — and both look
equally confident.

**Check monotonicity before trusting the answer.** Sorted by offset, the reported
position should move steadily from left to right. If it jumps around — if a
more-negative offset reads further right than a less-negative one — the result is
not supported, however clear any single trial felt. A previous session produced
six inversions out of 21 orderable pairs, with the *most confident* response
pointing the wrong way.

**What you're looking for:** the offset where it sits centred. If two adjacent
offsets both feel centred, take the midpoint. If none do, note which way it
always pulls — that is a finding, and means the range needs widening
(`--offsets -18 -15 -12 -9 -6 -3 0`).

---

## Part 3 — Presentation mode (8 minutes, skip if tired)

**Condition: BOTH DEVICES.** Correct here — the dichotic comparison needs one
signal in each ear.

Lowest priority. A previous session already indicated **alternating**; this
re-confirms it on a clean playback path. If she is flagging, stop instead — the
existing answer is probably right.

> ⚠️ **The `mode_*.wav` files play different audio to each ear on purpose.**
> The implanted ear gets ordinary speech. The acoustic ear gets a **simulation**
> of it, which is *meant* to sound electronic and strange. That is the thing
> being judged. **Tell her this before pressing play**, or she will reasonably
> assume the file is broken.

### 3a. Practice — identical audio in both ears

Play the three `practice_*.wav` files first. Same sound both sides, nothing to
judge. They let her learn how each style *feels* before meeting the harder
question — otherwise an unfamiliar interaction and an unfamiliar judgement arrive
together, and confusion about one looks exactly like difficulty with the other.

Ask only: **does this way of presenting feel comfortable?**

### 3b. The real comparison

| File | What it does |
|---|---|
| `mode_simultaneous.wav` | Both ears at once |
| `mode_alternating.wav` | Switches ear every 0.5 s |
| `mode_sequential.wav` | One ear, pause, then the other |

Play each **twice**, shuffled. After each:

> Could you tell the two sounds apart?
>
> Was it two sounds you were comparing, or did they blur into one?

Then, having heard all three:

> Which made it easiest to say whether the two matched?

**Anchor the scale out loud before asking: 1 means easiest, 5 means hardest.** An
unanchored 1–5 is ambiguous in both directions and cannot be compared across
sessions.

**The specific thing to watch for.** If the two signals fuse into one
natural-seeming percept under **simultaneous**, she is reporting on the merged
sound rather than comparing its parts — and it may not feel like a problem from
the inside. A previous session showed the tell: she could not say which ear was
carrying which signal. If that recurs, simultaneous is unusable for fitting
however pleasant it is.

---

## Recording the data

Copy `docs/lab-notebook/TEMPLATE-session.md` to
`private/sessions/YYYY-MM-DD-calibration.md`.

> ⚠️ **`private/` — not `docs/lab-notebook/`.** Raw session records contain
> health information and are gitignored. Anything going into the public notebook
> must be de-identified and about *method*, not about her.

Must be recorded or the session cannot be used:

1. **Her exact words from Part 1**, and whether she said layered or replaced.
2. **The balance offset**, plus the repeat trials, so monotonicity can be checked.
3. **Playback volume setting**, and confirmation it was played **locally from the
   phone**.
4. **Which condition each part was run in.**

Also, briefly: time of day, alertness at start and end (1–5), audiogram date, and
anything surprising.

**Record what went wrong.** If she tired at file four, if the balance never
centred, if a question confused her — that shapes the next session more than the
clean results do.

---

## If something goes wrong

**Both tones in both ears at Part 0.** Stop. The path is mono. Fix that first;
nothing else in the session can mean anything.

**She can't tell any of the modes apart.** Genuinely possible and not a failure.
It means the candidates are too similar — we widen the parameter pool and retry
with more distinct options.

**Everything pulls one way regardless of offset.** The range is too narrow.
Regenerate with wider offsets.

**She gets tired.** Stop. Part 1 alone is a successful session. Fatigued
discrimination data is indistinguishable from a null result, so pushing on
produces numbers that look like data and are not.

**Anything is uncomfortably loud.** Stop immediately, re-check against
`balance_plus_0dB.wav`, and do not continue until it is right.

**Any part gets run in the wrong condition.** Note it and discard that part. Do
not analyse it — a condition error produces data that looks completely normal and
means something different from what you think it means.
