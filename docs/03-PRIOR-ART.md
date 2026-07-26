# Prior Art and Inherited Lessons

PRELUDE is a rewrite. It replaces several years of exploratory work that produced useful
ideas alongside some instructive mistakes. This document records both, because the mistakes
are the kind that recur — they are not careless errors but *plausible* ones, which sounded
right and produced output that seemed reasonable.

Several tests in `tests/test_ci_sim.py` exist specifically to prevent their recurrence.

---

## Existing simulators this work draws on

**Cochlear Implant Simulation (CI_SIM) v2.0**, Universidad de Granada, 2004
(de la Torre Vega et al.). A Windows research and teaching tool implementing a
configurable CIS/n-of-m vocoder. Parameters include analysis range, cochlear length,
channel count, inserted electrodes, n-of-m maxima, channel interaction decay, envelope
detection method, and stimulation rate. Notably it writes a `.par` sidecar recording the
exact settings beside every output file — a practice worth copying, and the reason its
decade-old experiments remain interpretable.

**MATLAB CI demonstration**, Amir Rahimzadeh, HTW Berlin, 2013, built on **Malcolm Slaney's
Auditory Toolbox** and implementing Shannon's noise vocoder. A compact and correct
reference: ERB gammatone filterbank, per-channel envelope, envelope-modulated noise
re-filtered through the same band, summed. Two details differ from PRELUDE's choices — it
modulates by a *power* envelope rather than amplitude, and its 1 ms averaging window implies
roughly a 1 kHz envelope bandwidth, considerably wider than a real device's 50–400 Hz.

Neither is redistributed here. PRELUDE is an independent implementation of published
methods.

---

## Defects in the predecessor codebase, and the tests that now prevent them

### The simulator was not a vocoder

The core loop bandpass-filtered each channel, half-wave rectified it, raised it to the 0.7
power, and summed the results:

```python
envelope = np.maximum(filtered_signal, 0) ** 0.7      # not an envelope
simulated = np.sum(processed_bands * speech_weights[:, None], axis=0)
```

Three compounding problems. Rectification alone does not extract an envelope — it produces
a distorted copy of the band signal, rich in harmonics that were not in the input. There is
no carrier, so the fine structure is never discarded and never replaced, which is the
defining operation of a CI simulation. And `** 0.7` applied to a waveform is
waveform-shaping distortion, unrelated to the loudness-growth compression it was standing in
for.

The output sounded degraded and metallic, which is presumably why it was accepted. But the
degradation had the wrong *character*: it added distortion while preserving the temporal
fine structure a real implant destroys. Anything calibrated against it would have been
optimising for a distortion the device does not produce.

Correct envelope-extraction and noise-vocoding functions existed elsewhere in the same file
and were simply never called.

> **Guarded by** `TestEnvelope::test_envelope_discards_fine_structure`, which asserts the
> envelope contains an order of magnitude less high-frequency energy than the band signal
> it came from.

### The filterbank silently discarded half its channels

```python
NUM_CHANNELS  = 21
FREQ_BANDS    = np.linspace(700, 16000, NUM_CHANNELS + 2)
SAMPLING_RATE = 16000
```

At 16 kHz the Nyquist limit is 8 kHz, but the band edges ran to 16 kHz. A guard clause hid
the consequence rather than reporting it:

```python
highcut_norm = min(highcut / (sr / 2), 0.99)
if lowcut_norm >= highcut_norm:
    continue            # silently drops the band
```

**Eleven of twenty-one channels actually ran**, spanning 700–7920 Hz, with the top band
squashed to a 265 Hz sliver. Downstream weighting was computed over the surviving count, so
a "mid-frequency boost" intended for one part of the spectrum landed somewhere else
entirely. Nothing reported this.

Two further problems in the same three lines: the 700 Hz floor discarded F0 for most speech
and nearly all musical bass — content real devices do transmit, and which their own
configuration files placed at 300 Hz — and linear spacing contradicts the cochlea's
approximately logarithmic organisation, over-resolving treble while under-resolving bass.

> **Guarded by** `TestFilterbank::test_rejects_band_above_nyquist` (an out-of-range edge is
> now a fatal error, never a skipped band), `test_all_channels_survive`, and
> `test_greenwood_spacing_is_logarithmic`.

### Feature vectors compared across incompatible units

Raw-signal features were computed on an integer sample array while processed-signal features
were computed on floating-point audio in [-1, 1]. Two of the four stored metrics therefore
differed by a factor of roughly 32,768 — an artifact of units, not an effect of processing.
The numbers were nearly reported as a result.

> **Guarded by** centralising all file access in `prelude.audio.io`, which returns float64
> in [-1, 1] and keeps the sample rate attached to the signal.

### Parameter sweeps were unattributable

Three output files exist from a sweep performed by editing constants between runs. Which
settings produced which file cannot now be determined. The 2004 reference tool, by contrast,
wrote a parameter sidecar beside every output, and its experiments remain readable twenty
years later.

> **Guarded by** `SimulatorConfig.hash()`, YAML configuration files, and provenance
> sidecars written by `prelude.audio.io.save_audio`.

---

## The learning formulation — a good idea, starved of data

An earlier attempt fitted regressors mapping simulated audio back to natural audio,
attempting to learn the inverse of the CI transform. **The framing was sound**: if
`h ≈ CI⁻¹`, then applying `h` upstream yields `CI(h(x)) ≈ x`, which is exactly the
pre-emphasis strategy. It is not a category error, unlike the simulator above.

Every model nonetheless scored negative test R², worse than predicting the mean:

| Model | Train R² | Test R² |
|---|---|---|
| k-nearest neighbours (k=2) | 0.73 | −0.11 |
| Linear regression | 1.00 | −0.82 |
| Gaussian process | 0.14 | −0.11 |

The causes are diagnosable and mostly not about audio:

- **`p ≫ n`.** 2.55 seconds of audio in 1024-sample blocks yields roughly 36 training
  examples, each with 1024 features. Ordinary least squares fits such a system exactly and
  generalises not at all; the 1.00/−0.82 pair is the textbook signature.
- **Raw waveform regression is phase-sensitive.** A one-sample shift destroys the
  correlation while being perceptually inaudible, so the loss punishes differences nobody
  can hear.
- **Non-overlapping blocks** produce a discontinuity at every block boundary.
- **A temporal rather than content-stratified split** put different phonetic content in the
  test set.
- **Most fundamentally, `CI⁻¹` does not exist.** The transform discards temporal fine
  structure by design. Information destroyed cannot be recovered, so no model can learn the
  inverse — only a pseudo-inverse that pre-emphasises whatever survives.

The correction is recorded in
[`decisions/ADR-0001-learning-formulation.md`](decisions/ADR-0001-learning-formulation.md):
measure the loss **after** the simulator rather than before it. That never asks a model to
recover destroyed information; it asks it to arrange the signal so that less is destroyed.
It is also self-supervised, since the simulator generates its own targets — which removes
the data starvation entirely.

**These negative results should not be read as evidence that learning is unpromising here.**
The approach was starved, not disproven.

---

## The recurring pattern worth naming

Across two independent attempts, four years apart, the same failure appeared: a model was
asked to learn from a few dozen examples with a thousand features each. A later research
proposal from the same lineage planned to train a neural network on 50–100 samples.

Three occurrences of one mistake is a pattern, not an accident. It is worth stating plainly:
**perceptual data from human listeners will always be scarce**, because listening sessions
are slow, fatiguing, and cannot be parallelised. Any design that requires large quantities
of it will fail.

The resolution is architectural rather than logistical. Use the simulator to generate
unlimited training data, and reserve scarce human judgement for **validating** the
simulator and **ranking** a small number of finalists. Human data is the measuring
instrument, not the training set.
