# 2026-07-26 — First calibration session: methodological findings

**Type:** Calibration session (single participant, de-identified)
**Raw record:** held privately; not in this repository. Listening-session
responses are health information — see `CONTRIBUTING.md`.

This entry records what the session taught us about **method**. Participant
responses, descriptions of their hearing, and clinical detail are deliberately
excluded.

## The balance stimulus was wrong

Part 1 asks the listener to find the inter-ear level offset at which a sound
sits centred. It used a synthetic resonant, bell-like figure.

**Sorted by offset, the reported position should move monotonically from left to
right. It did not** — six inversions out of 21 orderable pairs, with the single
most confident response pointing the wrong way entirely. The resulting offset is
unsupported.

The cause is the stimulus, and it is a known one. **Sustained tonal stimuli are
a poor choice for listeners with hearing loss** — they can provoke or interact
with tinnitus, which contaminates exactly the localisation judgement a balance
task measures. Separately, a cochlear implant renders **resonance as buzzing**,
so a resonant stimulus is both uncomfortable and a weak probe.

A process point worth keeping: this surfaced because the session asked about
**comfort**, not only about the judgement. The numbers on their own would have
shown it as noise and nothing more.

**Use speech for balance tasks.** `scripts/make_calibration_session.py --source`
accepts any audio file; an audiobook excerpt works well. The synthetic figure
remains only as a fallback.

## Three protocol gaps, now fixed in the template

**No repeated offsets.** Seven offsets, one trial each. With no repeats there is
no way to distinguish a real balance point from a noisy one, and both look
equally confident. The template now calls for at least three unannounced repeats
and includes an explicit monotonicity check before any offset is trusted.

**No catch trials**, so the session has no response-noise floor and no effect
size within it can be calibrated.

**The 1–5 ease scale was unanchored.** Answers were given as 1 = easiest; the
template never said which direction it ran. Unanchored scales are ambiguous both
ways and cannot be compared across sessions. Now stated in the template and
flagged to be spoken aloud before asking.

## Presentation mode: alternating

Alternating was rated easiest and the free-text description supported the rating
rather than merely echoing it. Sequential also scored well. Simultaneous was
rated hardest, and the description suggested a **localisation failure** — the
listener could not tell which ear was carrying which signal.

That is what perceptual fusion looks like from the inside. It is not proof, but
combined with the lowest ease rating it is sufficient to keep simultaneous
presentation out of the fitting protocol. `ALTERNATING` remains the default in
`prelude.study.dichotic`.

## An open question about the simulator's architecture

The session produced a description of implant hearing as **layered** — the
original sound still audible underneath, with an added artifact quality on top of
it, rather than the original being replaced.

If that is a faithful report of the implant percept, it conflicts with the
vocoder model this simulator is built on. A vocoder *substitutes* temporal fine
structure; it cannot produce "original plus overlay", because it does not retain
the original.

**But the observation cannot bear that weight, and the fault is in the protocol.**
The guide specified "both devices in" for the earlier parts and gave Part 3 no
condition at all, so the description was collected bimodally by instruction. In
that condition the acoustic ear supplies an audible "original underneath"
regardless of what the implant does — so the answer was determined before the
question was asked. This says nothing yet about the implant.

The guide now specifies a listening condition for **every** part, and splits the
vocabulary task in two: comparing the halves of a dichotic file (both devices,
where the comparison lives) and describing the implant percept (**implant only**,
which is the only condition that can answer the architecture question).

Recorded here because the failure mode generalises: a protocol that does not
state a condition inherits the previous one silently, and the resulting data
looks entirely normal.

### A second confound, same root cause

The session was played through a **network audio relay** rather than from the
phone. The guide named the phone only in a line of script output and never said
"do not use a relay", so this was a reasonable reading of ambiguous instructions.

Resampling, buffering and packet loss sit on top of the Bluetooth codec, and the
participant remarked on artefacts during the session. A listener cannot separate
"this simulation is wrong" from "this playback is glitching", so every judgement
carries the ambiguity. The mode comparison is partially salvageable — all three
modes went through the same path, so the *relative* ranking is more robust than
any absolute statement — but it should be confirmed on a clean path before being
relied on.

The guide now states the playback requirement up front, with the reason.

## Also worth noting

Playback path was ambiguous in the record — nominally direct from phone, but a
remark about "networked audio playback" suggests a relay may have been in use for
part of the session. If so, network artefacts are a confound on every judgement,
and the participant noticed them. **Confirm and record the playback path
explicitly**; a perceptual measurement should not carry avoidable artefacts.
