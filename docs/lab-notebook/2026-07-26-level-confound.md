# Analysis note — the first fitting session is confounded by level

**Date:** 2026-07-26
**Type:** Analysis of an existing session; no listening took place.
**Sessions examined:** `36d1cb492fae` (9 responses), `74f80f3dce31` (6 responses)

This is a negative result about our own instrument, not about the listener.

---

## What the session appeared to show

In session `36d1cb492fae` the listener chose the pulse-carrier candidate in
**6 of 6 trials in which it was presented** — 7 scored judgements in total. The
posterior put ~83% on that candidate, and it read as a clear preference for
pulse over tone carriers.

## Why that reading does not survive

The candidate pool was normalised **per file**. Each stimulus was independently
brought to the loudness target, and the true-peak limiter then pulled down
whichever files had the highest crest factor. Pulse carriers have a high crest
factor. The result:

| candidate | integrated loudness |
|---|---|
| `carrier_pulse` | **−27.94 LUFS** |
| all sixteen others | −24.75 to −24.95 (a 0.20 dB spread) |

The preferred candidate was **3.09 dB quieter than everything it was compared
against**, and every other candidate sat within 0.2 dB of its neighbours. Three
decibels is roughly three times a level just-noticeable-difference.

"Prefers the pulse carrier" and "prefers the quieter interval" predict exactly
the same data here. The session cannot separate them, so it does not establish
either.

Measured per ear, the offset was present on both sides — 3.03 dB on the implant
channel and 3.08 dB on the acoustic channel — so this is a whole-stimulus level
difference, not a balance artefact.

### A second mechanism made it worse

Trials are selected by expected information gain, which concentrates on
candidates the posterior currently favours. Once the quieter candidate started
winning, the selector kept re-offering it. It was presented in 6 of the 7
scored trials and won all 6. A level advantage and a selector that chases the
leader reinforce each other, which is why a confound this size produced a
result that looked so clean.

## What the data still supports

- **The listener discriminates these stimuli and answers consistently.** They
  tracked the same candidate across both screen positions — the display order
  was `[1,0]` on three trials and `[0,1]` on three — which is the signature of
  a judgement about the sound rather than about the slot. That is a real and
  useful finding about the *method*.
- **Nothing about carrier type.** n = 7 scored judgements, fully confounded.
- Session `74f80f3dce31` shows no consistent preference (2/3, 1/1, 1/1, 1/1
  across four candidates) and was in any case exploratory.

## What was changed as a result

1. **Pool-wide levelling.** All candidates are now normalised to a common
   *achievable* level — the worst case across the pool after limiting — rather
   than each to the same target independently. Verified: spread fell from
   3.09 dB to **0.234 dB**, and the outlier is gone.
2. **A level control pair.** The anchor against a 3 dB attenuated copy of
   *itself*: identical content, level the only difference. It runs as the first
   three trials of every session, because sessions end early by design and a
   control at the end never runs. If the listener reliably picks the quieter
   interval, any preference correlated with level explains itself.
3. **Session records now name their pool** (`pool_id`), because rebuilding the
   pool renumbers candidates — see below.

## An incidental finding: the sessions nearly became unreadable

Rebuilding the pool re-derived every candidate and shifted eight indices.
Index 9 stopped being the pulse carrier and became a candidate that had not
existed when the listener sat down. Session records store bare integers, so
rescoring against the new pool would have silently reattributed six of seven
judgements — reporting "chose `env900` 6/6" with no error raised.

`archive/pool-v1-as-she-heard-it/` is **misnamed**: it holds the right set of
stimuli in a different order and cannot be the referent for either session.
See the README in that directory.

Both sessions turned out to be **fully recoverable from their own records** —
every trial stores the index *and* the filename served, so the mapping needs no
external pool:

```bash
python scripts/resolve_session.py --check private/sessions/*.json
```

Both resolve completely and self-consistently. No judgements were lost.

## The lesson worth keeping

Level dominates every other perceptual judgement. Per-file normalisation looks
like the careful thing to do and is exactly what introduced the confound,
because a peak limiter makes the *achieved* level depend on the crest factor of
the content — which is precisely the parameter under test. Normalise a pool to
a common achievable level, and carry a level control so the question can be
answered rather than argued about.
