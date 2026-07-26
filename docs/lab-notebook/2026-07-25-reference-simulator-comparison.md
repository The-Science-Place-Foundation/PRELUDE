# 2026-07-25 — First comparison against an external reference simulator

**Type:** Simulator validation (no human listeners involved)
**Status:** ⚠️ **Unresolved.** One real defect found and fixed; the headline
disagreement remains unexplained.

## Goal

Determine whether PRELUDE's simulator performs the same transformation as an
independent implementation. Until now it had only been checked against its own
unit tests, which verify internal consistency but cannot detect a shared
misconception.

## Method

Reference material: two source/output pairs produced by the Universidad de
Granada **CI_SIM v2.0** (2004), each accompanied by a `.par` file recording the
exact settings used.

| Fixture | Content | Reference settings |
|---|---|---|
| `speech_cis7` | 2.55 s male speech | 21 ch, n_on 2, 300–8500 Hz, 1230 pps, interact_decay 0.950605, cutoff 2000 |
| `piano_cis0` | 6.31 s solo piano | as above, 1200 pps |

Fixtures are local only and gitignored — one contains a human voice.

Comparison metric: mean per-band envelope correlation over a common 16-band
analysis. Envelopes rather than waveforms, because noise carriers differ by
construction and a waveform comparison would measure the carrier seed.

## Result: poor agreement

| Fixture | Envelope correlation | Threshold |
|---|---|---|
| `speech_cis7` | **0.653** | 0.70 |
| `piano_cis0` | **0.374** | 0.70 |

## Investigation

**1. Parameter sweeps did not explain it.** Sweeping `interaction_decay_db`
(1–60), `envelope_cutoff_hz` (50–2000), and `n_selected` (2–21) moved speech
between 0.60 and 0.73 and piano between 0.33 and 0.55. No setting approached
agreement, so the discrepancy is structural rather than a mis-set parameter.

**2. Time alignment was not the cause.** The reference lags its source by −6.6 ms
(speech) and −7.6 ms (piano), consistent with causal FIR group delay — PRELUDE
uses zero-phase filtering and has no such lag. Correcting for it by
cross-correlation improved speech only from 0.653 to 0.691 and piano not at all.

**3. Stereo handling was not the cause.** The piano source is genuinely stereo
(mean L/R difference 0.085). Mono mix 0.374, left-only 0.367, right-only 0.425 —
no choice resolves the gap.

**4. Band energy distribution located a real defect.** Broadband envelope
agreement for piano was high (peak cross-correlation 0.886) while per-band
agreement was poor (0.374). Overall temporal shape right, spectral distribution
wrong. Comparing fraction-of-energy per band:

| Band | Source | CI_SIM | PRELUDE (before fix) | ratio |
|---|---|---|---|---|
| 548 Hz | 0.092 | 0.209 | 0.009 | 24× too little |
| 6850 Hz | 0.007 | 0.005 | 0.126 | 25× too much |

A systematic tilt toward high frequencies.

## Defect found and fixed: carriers were not RMS-normalised

`resynthesise()` band-limited each noise carrier but never normalised it.
Band-limited white noise has RMS proportional to √bandwidth, and with Greenwood
spacing over 300–8500 Hz the most basal band is roughly fifty times wider than
the most apical one. Modulating un-normalised carriers therefore weighted each
channel by **how wide it happens to be** rather than by its envelope.

The requirement follows from what an envelope means: for output band *i* to carry
the same energy as input band *i*, we need `rms(env_i · c_i) ≈ rms(band_i)`, and
since `rms(env_i · c_i) ≈ rms(env_i)·rms(c_i)`, carrier RMS must be constant
across bands.

**Measured effect** (speech): energy above 4 kHz fell from 0.375 to 0.070 of the
total — the source itself has 0.163 — and mean absolute log-distance between
output and reference band-energy profiles improved from 0.55 to 0.39. For piano,
0.52 → 0.60 against the source and 1.20 → 1.09 against the reference.

## What the fix did *not* do

**It did not resolve the disagreement.** Per-band envelope correlation went
0.653 → 0.636 (speech) and 0.374 → 0.373 (piano) — unchanged within noise.

The fix is retained because it is correct on first principles and improves
spectral agreement, not because it improved the headline number. Recording this
distinction matters: a change that is right for a reason is worth keeping even
when the metric you hoped it would move does not move.

The channel-count sanity result was unaffected (0.83 / 0.75 / 0.63 for 22-ch CIS,
8-of-22 ACE, 4-ch CIS), confirming the fix did not disturb established behaviour.

## Remaining hypotheses, untested

1. **`n_on` semantics.** With n_on = 2 of 21, PRELUDE zeroes 19 channels every 16
   samples. CI_SIM's output retains substantial energy across several *adjacent*
   bands (435, 548, 684 Hz), which strict 2-of-21 selection should not produce.
   Either `n_on` does not mean n-of-m maxima, or selection is followed by enough
   current spread to re-excite neighbours.
2. **`interact_decay = 0.950605` semantics.** Mapped to 9.1 dB/channel by
   assuming an exponential length constant in channel units. This is a guess. If
   CI_SIM applies far heavier spread, that would explain hypothesis 1.
3. **`cutoff_freq = 2000`** was read as the envelope lowpass. 2 kHz is far above
   the 50–400 Hz real devices use, so it may denote something else entirely.
4. **`length_ci = 30`** (cochlear length, mm) has no direct equivalent in
   `SimulatorConfig`; Greenwood spacing over the analysis range is an analogue,
   not a translation.

**All four are downstream of one missing document:** the CI_SIM technical report,
which defines these parameters. Without it we are reverse-engineering a 2004
binary's semantics from a thirteen-line config file. Acquiring that report is now
the highest-value action for simulator validation — higher than any further
sweeping.

## Honest status

**PRELUDE's simulator is not validated against an external reference.** It is
internally consistent, passes 34 behavioural tests, and reproduces the
channel-count/fidelity relationship that defines CI simulation. That is a
necessary condition, not a sufficient one.

A poor match may mean PRELUDE is wrong, or that the parameter translation is
wrong, and the present evidence does not distinguish those. Nothing here should
be cited as evidence that the simulator is accurate, and the regression
thresholds have deliberately **not** been lowered to make the suite green.

## Follow-ups

- [ ] Obtain the CI_SIM technical report (de la Torre Vega et al., Universidad de
      Granada) — blocks hypotheses 1–4
- [ ] Add a second, independently-parameterised reference implementation, so a
      disagreement can be attributed rather than merely observed
- [ ] Test the hypothesis that heavy current spread reproduces CI_SIM's
      multi-band energy under n_on = 2

---

## Addendum — parameter search, and a reference that stopped being usable

**Global search.** 2,432 configurations against the speech target. Best achievable
**0.745**, against 0.636 for the straight `.par` port — so the earlier failure was
parameter translation, not a capability limit. The threshold of 0.70 is reachable.

The top twelve results agreed strikingly: **pulse carrier in all twelve**,
**n-of-m = 2 in all twelve** (confirming `n_on` is maxima selection), 21–22
channels, and **loudness mapping off in all twelve**.

**That last one exposed a defect.** The mapping stage was a no-op: the pipeline
compressed into `[T, C]` and then inverted the map exactly (measured relative
error 2.4e-16), so a 60 dB span emerged at 59.7 dB. The electrodogram carried the
electrical dynamic range constraint; the audio did not. Fixed — see
`levels_to_amplitude`. A 60 dB span now emerges at 24.5 dB.

**And here is the important part.** With the fix in place, agreement with CI_SIM
gets *worse*: 0.745 → 0.598. Making the simulator more faithful to the physiology
moved it **away** from the reference.

Only two readings are possible. Either CI_SIM does not render the electrical
dynamic range constraint into its audio output — plausible, since it may invert
its own mapping exactly as PRELUDE used to — or PRELUDE's compression is
mis-shaped. Nothing available here distinguishes them.

## Conclusion: stop optimising against this reference

The two references now disagree about something fundamental, and no amount of
further sweeping can adjudicate between them. Continuing to fit CI_SIM would mean
choosing to reproduce its behaviour *including wherever it is wrong*, on no
evidence beyond it having come first.

CI_SIM was only ever a proxy. Its value here came from its settings having been
tuned, over at least eight iterations, against one listener's reported perception
— so what carries the validation is **her judgement**, not the tool. That
judgement is directly available and does not need an intermediary.

**Revised status of these fixtures:** demoted from fitting target to regression
guard. They pin simulator behaviour so that unintended changes are noticed. They
are no longer the thing being optimised, and the 0.70 threshold should be read as
"still behaving as it did", not "correct".

The fitting target is now direct perceptual comparison — Type A sessions per
`05-EVALUATION-PROTOCOL.md`.
