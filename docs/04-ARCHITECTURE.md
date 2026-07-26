# Architecture

How PRELUDE is organised and why. Stage-by-stage physiology lives in
[`01-DOMAIN-PRIMER.md`](01-DOMAIN-PRIMER.md); this document covers software structure and
the contracts between components.

---

## Guiding principles

**Simulator before enhancer.** The enhancer is optimised against the simulator. An enhancer
built on an inaccurate simulator will confidently produce worse audio, and will do so while
reporting improved metrics. Simulator fidelity gates everything downstream.

**Every stage is independently inspectable.** Cochlear implant processing is not intuitively
predictable. Any stage can dump its intermediate signal and internal state, and the
electrodogram is a first-class output rather than a debugging afterthought. Being able to
*look* at what reaches the nerve is how structural mistakes get caught in days rather than
months.

**Parameters are data, not code.** All device and processing parameters live in versioned
YAML carrying a hash recorded in every output artifact. Sweeps performed by editing
constants produce results nobody can interpret later — see
[`03-PRIOR-ART.md`](03-PRIOR-ART.md).

**Fail loudly on invalid configurations.** Out-of-range parameters raise rather than being
clamped or skipped. Silent degradation is worse than a crash, because it produces
plausible-looking output that is quietly wrong.

**Safety is a pipeline stage, not a convention.** Loudness normalisation and peak limiting
are enforced in code on every path that can reach a human ear, with no bypass argument.

**Degrade gracefully to implant-only.** Nothing may structurally depend on residual acoustic
hearing, which in progressive loss is a diminishing resource.

---

## Package layout

```
prelude/
├── audio/          I/O, resampling, loudness, playback safety
│   ├── io.py       Audio dataclass; all file access goes through here
│   └── loudness.py BS.1770 loudness, true-peak, prepare_for_playback  [safety boundary]
├── ci_sim/         Pillar 1 — the simulator
│   ├── filterbank.py    Greenwood / ERB / explicit-table band design
│   ├── envelope.py      Hilbert or rectify+lowpass extraction
│   ├── selection.py     n-of-m peak picking
│   ├── mapping.py       acoustic amplitude to electrical stimulation level
│   ├── interaction.py   current spread across channels
│   ├── resynthesis.py   envelope-modulated carriers, summed
│   └── pipeline.py      SimulatorConfig, simulate(), SimulationResult
├── enhance/        Pillar 2 — pre-processing transforms          [in development]
├── eval/           objective metrics, electrodogram comparison   [in development]
├── viz/            spectrograms, electrodograms, A/B plots       [in development]
├── config.py       YAML loading; unknown keys are errors
└── cli.py          prelude-simulate
```

Audio I/O is centralised deliberately. Ad-hoc conversion at call sites is how an
integer-versus-float units mismatch went unnoticed in the predecessor long enough to be
nearly reported as a result.

---

## Pillar 1 — the simulator

Stages mirror a real device one for one, so each can be validated in isolation:

```
x(t)
 ├─ 1. filterbank      m log-spaced bands (Greenwood or ERB), low..high Hz
 ├─ 2. envelope        |hilbert(·)| or rectify+lowpass, 50-400 Hz cutoff
 ├─ 3. selection       n-of-m peak picking per frame  [ACE] or pass-through [CIS]
 ├─ 4. loudness_map    acoustic amplitude ──► electrical units, log compression into T..C
 ├─ 5. interaction     exponential current spread across channels
 └─ 6. resynthesis     Σ envelopeᵢ · carrierᵢ  (noise or tone)
 ▼
 x̂(t) + electrodogram
```

Stages 3, 4 and 5 are individually switchable via `SimulatorConfig`, which matters for
attribution: turning off selection isolates whether an enhancement helps the signal itself
or merely wins the peak-picking contest.

### The electrodogram

Beyond audio, the pipeline emits a channel × time matrix of stimulation levels. **This is
the right domain for comparing two signals.** Two signals with quite different waveforms can
produce near-identical electrodograms and sound the same through an implant; two that look
similar can differ substantially in what reaches the nerve. Objective metrics should
therefore be computed here rather than on waveforms wherever possible.

### Front-end processing — a known gap

Real processors apply pre-emphasis, automatic gain control, and noise reduction before the
filterbank. PRELUDE does not model these yet. They matter for microphone input; for the
streamed-audio case that motivates this project, some are bypassed, though *which* ones
depends on the streaming path and is often undocumented. Recorded here so the omission is
explicit rather than forgotten.

---

## Pillar 2 — the enhancer

Formally: find `g` minimising `d(CI(g(x)), x)`, with the distance measured **after** the
simulator. See [ADR-0001](decisions/ADR-0001-learning-formulation.md) — that placement is
the whole problem.

Architecture: a chain of independently switchable, independently evaluable blocks. Not a
monolith, and not initially a learned end-to-end model.

```
x ──► [separate] ──► per-source chains ──► [remix] ──► [master] ──► [safety] ──► g(x)
```

Candidate blocks, ranked by expected value (see `01-DOMAIN-PRIMER.md` §5):

| Block | Rationale |
|---|---|
| Dereverberation | Reverb fills envelope valleys, and envelopes are all that survive |
| Source separation | Fewer competing sources means cleaner n-of-m allocation |
| Spectral contrast enhancement | Pre-compensates the smearing that current spread will cause |
| Dynamic range compression | Fits the source into the ~10 dB electrical window deliberately |
| Onset / transient sharpening | Rhythm is the best-preserved dimension; play to it |
| F0 / harmonic emphasis | Supports the weak periodicity pitch cue |
| Masker removal | Under n-of-m, removing a loud irrelevant band promotes a useful one |
| Frequency remapping | Folds content into the transmitted range — **validate perceptually first**; an acclimatised listener has adapted to their existing map |

**Anti-lever:** naive loudness maximisation and brickwall limiting. Both destroy the
envelope modulation depth that is the implant's only real information channel.

**Evaluate one lever at a time.** The predecessor applied several simultaneously and could
not attribute the outcome to any of them.

### On machine learning

There is deliberately no learned component yet. The path, when justified, is to make the
simulator differentiable and train `g` against the downstream loss. That is gated on
simulator fidelity, because a learned `g` will exploit any inaccuracy ruthlessly.

A cheaper intermediate should be exhausted first: parameter search over the hand-built
chain, scored by objective metrics, with the top candidates confirmed by listening tests.

---

## Bimodal path handling

Where a listener uses an implant on one side and acoustic hearing on the other, the two ears
are treated as two outputs of one process with an explicit crossover:

```
                    ┌──► implant-path processing ──► implanted ear
x ──► analysis ──►  │
                    └──► acoustic-path processing ──► aided ear
                              ▲
                    crossover, blend and per-path gain from device_profile.yaml
```

Setting the acoustic path's contribution to zero collapses the system to implant-only. This
satisfies the graceful-degradation requirement structurally rather than by convention: when
the transition comes, it is a configuration change rather than a rewrite.

---

## Conventions

- One configuration file per experiment, hashed into every output artifact.
- Every artifact gets a JSON sidecar recording input hash, config hash, and diagnostics.
- Audio is float64 in [-1, 1], mono unless explicitly stated, sample rate always attached.
- Default working rate is 20 kHz, which accommodates a 300–8500 Hz analysis range.
- Channel 0 is always the most apical (lowest frequency).

---

## Deferred

**Real-time implementation.** Offline batch processing is the target; latency is free.
Open hardware platforms exist for a real-time embodiment should the offline engine prove
out, but that is a separate project.

**Generalisation across listeners.** Personalisation is the point. The *methodology* may
generalise even where tuned parameters do not.
