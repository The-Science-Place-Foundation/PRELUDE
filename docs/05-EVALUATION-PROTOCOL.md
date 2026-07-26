# Evaluation Protocol

How anything in PRELUDE gets measured. Two tiers: cheap automated metrics that run on every
change, and scarce human listening sessions that are the actual ground truth.

**The governing constraint:** human listening time is finite, fatiguing, and — and where hearing loss is
progressive, *diminishing*. Every automated metric in Tier 1
exists to ration Tier 2, never to replace it.

---

## Tier 0 — Safety (non-negotiable, runs before any human hears anything)

Enforced in code, in the pipeline, with no bypass flag.

1. **Loudness normalization** to a documented target (default −23 LUFS integrated) across
   *all* stimuli in a comparison. Unmatched levels invalidate subjective comparison —
   loudness differences dominate every other perceptual judgment. The 2022
   `amplitude_comp.png` shows a ~1.6× uncalibrated gain error already happened once in this
   project's history.
2. **True-peak limiting** below a fixed ceiling (default −1 dBTP).
3. **Level verification on the actual playback chain** at session start, at the listener's normal
   listening volume, before any test material is played.
4. **Abort on NaN/Inf or discontinuity** anywhere in the output buffer.

> Rationale: the listener's residual acoustic hearing is irreplaceable and already degenerating. An
> over-level playback is an unacceptable, irreversible risk. This rule overrides
> experimental convenience, schedule, and every other consideration.

---

## Tier 1 — Automated metrics (fast, every change)

These catch breakage and rank candidates before spending listening time. **None of them is
validated against CI percepts.** Treat them as regression signals, not as truth.

### 1.1 Simulator correctness — the regression suite

The highest-value test available, and it costs no human listening time.

Validate against an **external reference simulator** whose parameters are documented.
`tests/test_reference_regression.py` implements this; `tests/fixtures/README.md` explains
how to supply matched source/reference pairs. The tests skip when fixtures are absent, so a
clean checkout passes.

Compare in this order, the later measures mattering more than the earlier:

- **Per-channel envelope correlation** — the primary measure, because envelopes are the
  information a real device transmits
- Long-term average spectrum
- Modulation spectrum

Exact waveform agreement is **not** expected: carrier phase and noise seeds differ by
construction. Reference tools often output at a fixed sample rate regardless of input;
resample before comparing.

**Match a delta, not just an absolute.** If reference outputs exist for the same source
under two different configurations, verify that PRELUDE reproduces the direction and rough
magnitude of the difference between them. That cancels implementation details irrelevant to
the question and is a considerably stronger test.

### 1.2 Enhancement metrics

Computed on the **electrodogram** (channel × time stimulation matrix) rather than the
waveform wherever possible — that is the actual information reaching the nerve.

| Metric | What it measures | Caveat |
|---|---|---|
| Per-channel envelope correlation, `CI(g(x))` vs `x` | how much original structure survives | the headline internal metric |
| Envelope **modulation depth** | the CI's primary surviving cue | maximizing blindly → pumping artifacts |
| Channel selection stability (n-of-m) | how erratic the transmitted channel set is | high instability suggests polyphony overload |
| Spectral contrast (peak-to-valley across channels) | resistance to current-spread smearing | |
| **NCM** (normalized covariance metric) | envelope-based intelligibility | among the better vocoded-speech predictors |
| **ESTOI** | intelligibility | envelope-based, reasonably CI-relevant |
| Onset-detection F1 vs. reference | rhythm preservation | rhythm is the CI's strength — protect it |
| Chroma / melodic contour agreement | melody preservation | pitch is the CI's weakness — the hard target |
| PESQ / POLQA | — | **designed for telephony codecs; poor CI fit. Use with suspicion or not at all.** |

**Known failure mode:** optimizing any of these directly produces audio that scores well
and sounds worse. They rank candidates for human testing; they do not decide anything.

### 1.3 Hygiene checks
Output level within target; no clipping; duration preserved; sample rate and channel count
as declared; config hash recorded in the artifact sidecar.

---

## Tier 2 — Human listening sessions (the ground truth)

### 2.1 Two distinct experiment types — do not mix them

**Type A — Simulator fitting.** *Does our simulation match the listener's implant percept?*
For bimodal listeners: present a candidate simulation to the **acoustic ear only**, and ask
the listener to compare it against what the same source sounds like through the implanted
ear. Where available, this is the only direct instrument for the measurement.

**Type B — Enhancement preference.** *Is `g(x)` better than `x` through the implant?*
Present both through the **implant path**, blinded and level-matched, and ask for preference,
intelligibility, or effort.

Type A calibrates the model. Type B tests the product. Conflating them produces
uninterpretable data.

### 2.2 Session design rules

Derived from the elicitation caveats in `01-DOMAIN-PRIMER.md` §4.1:

1. **Forced choice over free description.** "Which of these two is closer to your CI?" beats
   "describe your CI." Free description is valuable for *generating* hypotheses, useless for
   *testing* them.
2. **Blind and randomise** presentation order, by script rather than by hand. Investigators
   are typically invested in a positive result; where investigator and participant have a
   personal relationship, that investment is stronger and the bias is not hypothetical.
3. **Catch trials.** Include identical A/A pairs to estimate response noise. Without a noise
   floor, a 60% preference is uninterpretable.
4. **Level-match everything** (Tier 0).
5. **Short sessions.** 15–20 minutes of active comparison. Auditory fatigue degrades
   discrimination, and the degraded data is indistinguishable from a null result.
6. **Fixed stimulus set** across sessions for longitudinal comparability, plus a small
   rotating novel set to detect learning effects.
7. **Record the audiogram date** alongside every session. In progressive loss the acoustic
   ear is a moving target, and a result from six months ago was measured on a different
   instrument.
8. **The participant may stop at any time, for any reason or none.** Consent is ongoing
   and revocable, and this must be stated at the start of every session.

### 2.3 Stimulus ladder

Adopted from an earlier internal study design. The principle: **isolate single perceptual dimensions before
combining them**, so that a failure can be localized rather than merely observed.

| Tier | Count | Content | Isolates |
|---|---|---|---|
| 1 | 20–30 | Pure tones across frequencies | place/pitch coding, frequency resolution |
| 2 | 20–30 | Single instruments, diverse timbres | spectral envelope, harmonic structure |
| 3 | 10–20 | Short passages, simple melodies | melodic contour, F0 tracking over time |
| 4 | 5–10 | Complex polyphonic music | n-of-m competition, source separation |

Add a **Tier 0: speech** (audiobook excerpts) — the easiest CI case, the most likely daily
use, and the tier where an early win is most achievable.

Ready-made resources worth seeking out:
- Some published CI demonstrations ship `speech`/`music`/`noise` pre-rendered at **1, 4, and
  16 channels** — a channel-count ladder useful for establishing how many effective channels
  the listener has, independent of our own code.
- the reference fixtures holds the parameter-documented `act_`/`sim_` speech pair.


Rating dimensions: **clarity, timbre accuracy, pitch
perception, instrument separation, overall enjoyment.** Sound decomposition — but collect
them via forced-choice comparison rather than absolute 1–10 scales wherever the question
permits (§2.2 rule 1).

### 2.4 What to capture per session

Logged in `docs/lab-notebook/YYYY-MM-DD-session.md`:

- Date, time of day, the listener's subjective alertness/fatigue
- Equipment: device, program/MAP slot, streaming path, playback volume setting
- Any recent MAP change or audiogram change
- Stimulus list with config hashes
- Raw per-trial responses (not just summaries — the summary can be recomputed, the raw
  cannot be recovered)
- Verbatim descriptive quotes — **especially the vocabulary the listener uses for CI percepts.**
  This is genuinely valuable primary data. There is no established vocabulary for
  describing electric hearing; theirs, accumulated over time, becomes the project's
  measurement language.
- Anything surprising, including results that contradict the hypothesis

### 2.5 Priority: capture calibration data early

Type A experiments depend on residual acoustic hearing. Where that hearing is progressive,
the window for collecting this data is finite and closing, whereas engineering work can be
done at any time.

This inverts the intuitive ordering. It is worth running Type A sessions with whatever
parameter-documented reference material is already available, before the software is
finished, because those sessions cannot be run later. Software can wait; the measurement
cannot.

---

## Tier 3 — Longitudinal

- **Listening effort / fatigue** over a long session (e.g. a full audiobook chapter) —
  arguably the most meaningful real-world outcome, and easier to detect than moment-to-moment
  preference.
- Self-reported enjoyment over weeks of ordinary use.
- Re-measure a fixed reference stimulus set at every audiogram change, to track the
  acoustic ear's decline and re-fit the bimodal crossover.

---

## Reporting standard

Every experiment writes a lab-notebook entry stating: hypothesis, method, **N**, result,
and an honest interpretation including negative results.

A negative result honestly recorded is a contribution. An overstated one is a harm to
someone with a real personal stake in the outcome. Do not round a null result up.
