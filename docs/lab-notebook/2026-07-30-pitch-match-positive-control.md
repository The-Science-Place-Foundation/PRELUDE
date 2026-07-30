# Method validation — the pitch match recovers a known answer

**Date:** 2026-07-30
**Type:** Positive control. Investigator, normal hearing in both ears. **Not listener data.**
**Stimuli:** third-octave noise bursts, 400 ms, −26.6 LUFS, eighth-octave probe ladder 125 Hz–8 kHz

A listener with two ordinary ears should match a narrowband burst in one ear to
the same frequency in the other, so the expected shift is zero at every
reference. Any systematic departure would point at the ladder, the estimator or
the ear routing rather than at hearing.

---

## Result

| reference | match | shift | basis | spread | trials |
|---|---|---|---|---|---|
| 500 Hz | **500.0 Hz** | **0.00 st** | equality | 0.0 st | 6 |
| 1500 Hz | 1498.3 Hz | −0.02 st | reversals | 1.5 st | 10 |
| 3000 Hz | 2911.3 Hz | −0.52 st | reversals | 1.5 st | 8 |

Median shift **−0.02 semitones**, direction consistent, worst case 0.52 st —
inside the method's finest rung of 1.5 st. Both estimation paths exercised.

## The 500 Hz trace, which is the informative one

```
250   -> first     reference higher; correct, 250 < 500
500   -> SAME      equality report at the true match
545.3 -> second    probe higher; correct, and shows this is not a blanket
                   "everything sounds alike"
500   -> first     forced guess at the match point
545.3 -> second
500   -> SAME      confirmed; terminates
```

Trial 4 is the whole argument for the equality response. At the match point a
forced choice makes the listener guess, and that guess is noise. The two
equality reports place the estimate on 500.0 exactly, while the intervening
"second" at 545.3 confirms the listener still discriminates a single rung — so
"the same" is a judgement about pitch agreement, not an inability to hear a
difference.

## What this validates, and what it does not

**Validated:** the probe ladder, the geometric averaging, the finest-step rule,
the equality path, ear routing, and the reliability checks. The machinery
recovers a known answer to within half a semitone.

**Not validated: the bimodal task itself.** This says nothing about whether a
cochlear implant user can place an electric percept on an acoustic pitch scale.
That is the open question, and the listener's one attempt so far — a 500 Hz
staircase walking to the ladder floor at 125 Hz and pinning there over seven
trials — is evidence it may not transfer. Two readings remain live:

1. a large downward frequency-place shift, which would be unusual; or
2. the electric percept not lying on a common pitch scale with an acoustic one
   at all, in which case "can't compare these" is the honest answer and the
   test should be abandoned rather than pushed.

The correctly-labelled "Can't compare these at all" response exists to
distinguish those, and a run of them is itself a finding.

## Known limitation of the estimator

The reversal-based estimate averages the last four finest-step reversals. With
an odd number of them, whichever rung appears twice pulls the estimate toward
itself — visible here as −0.52 st at 3000 Hz, where two of three finest
reversals sat on the lower rung. Averaging an even count would balance the
directions, but on a single control run that change would be fitting to noise
and it has deliberately not been made. Worth revisiting only if a real result
turns on half a semitone.

## Faults this run and its predecessors exposed

Recorded because they are the reason the method now works, and all three
produced plausible-looking output rather than failing loudly.

1. **No way to report equality.** The task offered higher/lower, "too different
   to tell" and a skip, so at the match point the only honest move was to
   abandon the reference. Two of three references died that way in an earlier
   run, and the cause was misdiagnosed twice as an interface dead state before
   being heard correctly.
2. **The probe ladder lands exactly on 500 Hz, which is also a reference**, and
   both were generated from one seed — so at the match frequency the listener
   was comparing a waveform to a byte-identical copy of itself. Fixed by
   folding the generator's role into the seed: same pitch, different noise.
3. **Reliability was assumed from completion.** A random-answer run returned
   three "resolved" estimates with shifts of −20, +24 and −31 semitones. A
   staircase always converges; fed noise it converges on noise. Settling is now
   judged by the spread of the reversals or equality reports that the estimate
   rests on, plus a cross-reference direction check.
