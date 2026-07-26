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

## A retracted observation

The session produced a description of implant hearing that was, at the time,
read as evidence about the simulator's architecture. **It is retracted.**

It was collected in the **bimodal** condition, because the guide specified "both
devices in" for the earlier parts and gave this task no condition at all. In
that condition the contralateral ear contributes to whatever is described, so
the description was determined by the protocol before the question was asked.
The session also ran through a network audio relay whose artefacts the
participant remarked on.

Recorded here only so the retraction travels with the claim. It should not be
cited, and no design decision should rest on it.

## Also worth noting

Playback path was ambiguous in the record — nominally direct from phone, but a
remark about "networked audio playback" suggests a relay may have been in use for
part of the session. If so, network artefacts are a confound on every judgement,
and the participant noticed them. **Confirm and record the playback path
explicitly**; a perceptual measurement should not carry avoidable artefacts.
