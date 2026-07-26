# Listening Session — YYYY-MM-DD

> Copy to `YYYY-MM-DD-session.md`. One file per session. Record raw responses, not just
> summaries — summaries can be recomputed, raw data cannot be recovered.
> Session design rules: `docs/05-EVALUATION-PROTOCOL.md` §2.2.

## Session type

- [ ] **Type A — Simulator fitting** (does the simulation match the listener's implant percept?)
- [ ] **Type B — Enhancement preference** (is `g(x)` better than `x` through the CI?)
- [ ] **Exploratory / vocabulary building** (no hypothesis, generating them)

Do not mix Type A and Type B in one session.

## Pre-flight (Tier 0 safety — all must be checked before any audio is played)

- [ ] All stimuli loudness-normalized to the target (default −23 LUFS integrated)
- [ ] True-peak ceiling verified (default −1 dBTP)
- [ ] Playback level verified on the actual chain, at the listener's normal listening volume
- [ ] Presentation order randomized **by script**, not by hand
- [ ] Catch trials (identical A/A pairs) included in the sequence
- [ ] The listener knows the listener can stop at any time, for any reason or none

## Context

| Field | Value |
|---|---|
| Date / time of day | |
| Self-reported alertness / fatigue (1–5) | |
| Device + processor model | |
| Program / MAP slot used | |
| Any MAP change since last session? | |
| Hearing aid + settings (if in use) | |
| Most recent audiogram date | |
| Playback path (BLE/ASHA, accessory, phone, speakers) | |
| Playback volume setting | |
| Which ear(s) receiving stimulus | |
| Ambient environment / noise | |

## Hypothesis

> What specifically are we testing, and what result would falsify it?
> "Exploratory" is a valid answer — say so rather than inventing a hypothesis afterward.

## Stimuli

| # | File | Config hash | Source | Notes |
|---|---|---|---|---|
| | | | | |

## Raw trial log

| Trial | Presented (blinded label) | Actual condition | Their response | Confidence (1–5) | Verbatim comment |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |

## Catch-trial performance

> How many A/A pairs were correctly identified as identical / how many total.
> **This is the response-noise floor. Every other result is interpreted against it.**

## Verbatim descriptive quotes

> Especially the listener's vocabulary for CI percepts. There is no established language for describing
> electric hearing; theirs becomes this project's measurement language. Record exact wording,
> including hedges and self-corrections.

## Results

> Counts and proportions. State N explicitly.

## Interpretation

> Honest reading, **including negative results**. If the data is null, say so. If the catch
> trials show high response noise, say the session is uninterpretable and why.
> Do not round a null result up — a participant with a real personal stake is relying on
> this being accurate.

## Follow-ups

- [ ]

---

# Calibration session addendum

> Extra fields for a **first calibration session** — see
> `docs/CALIBRATION-SESSION.md`. Delete this block for ordinary sessions.

## Ear assignment

| Field | Value |
|---|---|
| Implant ear | left / right |
| Hearing aid ear | left / right |
| Verified against the generated files? | yes / no |

⚠️ If this is wrong the experiment is inverted and the data will still look
normal. Confirm before analysing anything.

## Part 1 — Loudness balance

Present in shuffled order, not as a sweep.

| Order played | File (offset dB) | Centred / pulls left / pulls right | How strongly (1–5) |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 (repeat of #2) | | | |
| 9 (repeat of #5) | | | |
| 10 (repeat of #7) | | | |

> **Repeat at least three offsets**, unannounced, as trials 8-10. Without repeats
> there is no way to tell a real balance point from a noisy one, and the answers
> will look equally confident either way.
>
> **Sanity check before trusting the result:** sorted by offset, the reported
> position should move steadily from left to right. If it jumps around - if a
> more-negative offset is reported further right than a less-negative one - the
> stimulus or the listener's state is fighting the task, and the chosen offset is
> not supported however clear any single answer felt.

**Balance offset chosen:** ______ dB on the implant side

**Confidence in it:** clear / approximate / never centred

> If it never centred, say which way it always pulled. That is a finding, not a
> failed session — it means the offset range needs widening.

## Part 2 — Presentation mode

| Mode | Could tell them apart? | Felt like two sounds or one? | Ease (1 = easiest, 5 = hardest) |
|---|---|---|---|
| Simultaneous | | | |
| Alternating | | | |
| Sequential | | | |

> Anchor the scale out loud before asking: **1 means easiest, 5 means hardest.**
> An unanchored 1–5 is ambiguous in both directions and the answers cannot be
> compared across sessions afterwards.

**Preferred mode:** ______

**Did simultaneous cause fusion — "one sound" rather than two?** yes / no / unsure

> This is the key question of the session. If yes, simultaneous presentation
> cannot be used for fitting no matter how pleasant it is, because they would be
> reporting on a merged percept rather than comparing its parts.

## Part 3 — Vocabulary (optional)

Verbatim quotes describing how the two halves differed. Exact wording, including
hedges and self-corrections. Do not translate into technical terms.

>
>

## Session conditions

| Field | Value |
|---|---|
| Playback volume setting | |
| Streaming path | Bluetooth from phone |
| Both devices paired and synchronised? | yes / no |
| Audiogram last done | |
| Alertness at start (1–5) | |
| Alertness at end (1–5) | |
| Stopped early? Why? | |

## What went wrong

> Confusing questions, fatigue points, anything unexpected. This shapes the next
> session more than the clean results do.

>
