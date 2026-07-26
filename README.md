# PRELUDE

**Pre-Rendering for Enhanced Listening Under Degraded Encoding**

An open-source research toolkit for **cochlear implant audio simulation and
pre-processing**.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#project-status)

---

## The problem

A cochlear implant restores hearing by stimulating the auditory nerve directly.
Its sound processor is tuned for **real-time speech**, and it is very good at
that. Recorded music and audiobooks streamed over Bluetooth are a different
problem, and the results are widely reported as thin, harsh, or unrecognisable.
Music perception in particular remains one of the least satisfying aspects of
life with an implant.

The processor itself cannot be changed. Its filterbank, channel selection,
loudness mapping, and stimulation parameters are fixed firmware plus a clinical
program that only an audiologist should touch. The **only available point of
intervention is upstream** — the audio presented to the device.

That makes this a *pre-compensation* problem, of the same shape as pre-emphasis
for a known lossy channel:

> Find a transform `g` such that `CI(g(x))` is perceptually closer to `x`
> than `CI(x)` is.

Note that `g(x)` need not sound good to a normal-hearing listener. It is
optimised for what survives the implant.

## What this provides

**`prelude.ci_sim` — a cochlear implant simulator.**
Models the processor's signal chain stage by stage: analysis filterbank →
envelope extraction → n-of-m channel selection → loudness mapping into the
electrical dynamic range → channel interaction from current spread →
resynthesis. Every intermediate is retained, including the **electrodogram** —
the channel-by-time matrix of stimulation levels, which is what actually reaches
the auditory nerve and the right domain in which to compare two signals.

**`prelude.enhance` — pre-processing transforms.** *(in development)*

**`prelude.audio` — I/O and playback safety.** Loudness normalisation and
true-peak limiting are enforced, not optional. See [Safety](#safety).

**`prelude.eval` — objective metrics.** *(in development)*

## Install

```bash
git clone https://github.com/YOUR-ORG/prelude.git
cd prelude
pip install -e ".[dev,viz]"
pytest
```

## Quick start

```python
from prelude.audio import load_audio, prepare_for_playback, save_audio, Audio
from prelude.ci_sim import SimulatorConfig, simulate

audio = load_audio("input.wav", target_rate=20000)

# An ACE-like device: 8 of 22 channels transmitted per frame.
config = SimulatorConfig(n_channels=22, n_selected=8, seed=0)
result = simulate(audio.samples, audio.sample_rate, config)

print(result.diagnostics())
# {'config_hash': 'e3c1f3d2f972', 'n_channels': 22, 'duration_s': 2.555,
#  'selection_stability': 0.5904, 'mean_channels_active': 8.0,
#  'effective_channels': 16.19}

safe, report = prepare_for_playback(result.audio, audio.sample_rate)
print(report.summary())
save_audio("simulated.wav", Audio(safe, audio.sample_rate),
           metadata={"config_hash": config.hash()})
```

Or from the command line:

```bash
prelude-simulate input.wav -o simulated.wav --channels 22 --selected 8
```

The simulator reproduces the field's most robust qualitative result — fidelity
falls as channel count falls:

| Configuration | Envelope correlation with source |
|---|---|
| CIS, 22 channels | 0.84 |
| ACE, 8 of 22 | 0.75 |
| CIS, 4 channels | 0.63 |

## Design principles

**Fail loudly on invalid configurations.** Band edges above Nyquist raise an
error rather than being silently dropped. This is a direct response to a real
defect in this project's predecessor, where a nominally 21-channel filterbank ran
with 11 channels for months without anyone noticing.

**Parameters are data, not code.** Configurations live in YAML and carry a hash
that is recorded in every output artifact. Parameter sweeps performed by editing
source produce results nobody can interpret later.

**Every stage is inspectable.** CI processing is not intuitively predictable.
Being able to look at the electrodogram is how structural mistakes get caught
early rather than after months of tuning against a wrong model.

**Simulator before enhancer.** An enhancer optimised against an inaccurate
simulator will confidently produce worse audio. Simulator fidelity gates
everything downstream.

## Safety

> **Audio produced by this toolkit may be presented to people whose residual
> hearing is irreplaceable and, in progressive conditions, already
> deteriorating. An over-level playback is not a recoverable mistake.**

Every signal that may reach a human ear must pass through
`prelude.audio.loudness.prepare_for_playback`, which normalises integrated
loudness (default −23 LUFS), enforces a true-peak ceiling (default −1 dBTP), and
refuses to process signals containing NaN or infinite values. There is
deliberately no bypass argument.

Level matching is also a methodological requirement. Loudness differences
dominate every other perceptual judgement, so an unmatched comparison measures
level rather than whatever it was intended to measure.

**This is research software, not a medical device.** It is not certified for
clinical use, it must not be used to inform changes to anyone's implant program,
and it does not diagnose or treat anything. Device programming is the exclusive
province of a qualified audiologist.

## Research use

If you are running listening studies with this toolkit, please read
[`docs/05-EVALUATION-PROTOCOL.md`](docs/05-EVALUATION-PROTOCOL.md) first. It
covers blinding, catch trials for estimating response noise, loudness matching,
session length limits for auditory fatigue, and the reasons each matters.

Human-subjects research requires ethics review. Studies involving a small number
of participants — including single-case designs, which are legitimate and
well-established methodology — still require it, and any conflict of interest
between investigator and participant must be disclosed.

## Documentation

| Document | Purpose |
|---|---|
| [Domain primer](docs/01-DOMAIN-PRIMER.md) | CI physiology, audiology, and DSP grounding — **read before writing DSP** |
| [Architecture](docs/04-ARCHITECTURE.md) | System design and stage contracts |
| [Evaluation protocol](docs/05-EVALUATION-PROTOCOL.md) | Metrics and listening-study protocol |
| [Prior art](docs/03-PRIOR-ART.md) | Predecessor work, and the defects this design avoids |
| [Decisions](docs/decisions/) | Architecture Decision Records |

## Project status

**Alpha.** The simulator core is implemented and tested. The enhancement and
evaluation modules are scaffolded but incomplete. APIs will change.

The simulator currently models a *generic* implant. Manufacturer-specific
frequency allocation tables, T/C levels, and front-end processing are supported
by the configuration format but are not bundled — supply your own via
`config/device_profile.yaml`.

## Contributing

Contributions are very welcome, particularly from audiologists, CI users, and
hearing researchers. Domain corrections are as valuable as code. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## About

PRELUDE is developed by **[The Science Place Foundation](https://scienceplacefoundation.org)**,
a 501(c)(3) nonprofit, and released as open source for the audiology and hearing-research
community.

The project began as an attempt to solve a specific problem for one bimodal cochlear
implant user: recorded music and audiobooks, streamed to an implant, sound markedly worse
than the same material heard acoustically. That problem is not specific to one person, and
neither is the approach. The toolkit is built to be useful to any researcher or clinician
working on cochlear implant audio.

If you are working in this area and PRELUDE is missing something you need, please open an
issue — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Acknowledgements

This work builds on the noise-vocoder simulation method introduced by
**Shannon et al. (1995)**, *Speech recognition with primarily temporal cues*,
Science 270(5234).

Development was informed by two existing simulators: the **Cochlear Implant
Simulation** package from the *Universidad de Granada* (de la Torre Vega et al.,
2004), and a MATLAB CI demonstration by **Amir Rahimzadeh** (HTW Berlin, 2013)
built on **Malcolm Slaney's Auditory Toolbox**. Neither is redistributed here;
PRELUDE is an independent implementation of published methods.

## Citation

If PRELUDE contributes to published work, please cite it — see
[CITATION.cff](CITATION.cff), which GitHub renders as a "Cite this repository" link.

## Licence

Apache License 2.0 — see [LICENSE](LICENSE). Apache-2.0 was chosen over a
permissive MIT-style licence for its explicit patent grant, which matters in a
field as patent-dense as hearing devices.

Copyright © The Science Place Foundation and the PRELUDE contributors.
