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

There is a more mundane explanation: the description was collected in the
**bimodal** condition, so the audible "background" may simply be the
contralateral acoustic ear. That would make the layering real but external to the
implant.

**The two readings are distinguishable.** Repeat the description task in
**CI-only**. If layering persists with the contralateral device removed, it is a
property of the implant percept and the simulator's architecture needs revisiting
— which no amount of parameter fitting would reach.

Recorded here because it is the kind of finding that is easy to note, hard to
act on, and expensive to rediscover later.

## Also worth noting

Playback path was ambiguous in the record — nominally direct from phone, but a
remark about "networked audio playback" suggests a relay may have been in use for
part of the session. If so, network artefacts are a confound on every judgement,
and the participant noticed them. **Confirm and record the playback path
explicitly**; a perceptual measurement should not carry avoidable artefacts.
