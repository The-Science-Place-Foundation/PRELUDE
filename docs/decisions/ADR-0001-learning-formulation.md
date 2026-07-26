# ADR-0001 — Measure the loss after the simulator, not before it

- **Date:** 2026-07-25
- **Status:** Accepted

## Context

The natural way to frame pre-processing for a cochlear implant is to learn the inverse of
the device's transform. If `h ≈ CI⁻¹`, then applying `h` upstream gives `CI(h(x)) ≈ x` —
the same strategy as pre-emphasis for a known lossy channel. This framing is correct as far
as it goes, and a predecessor project pursued it directly by fitting regressors from
simulated audio back to natural audio.

It failed, and the failure is instructive (see [`../03-PRIOR-ART.md`](../03-PRIOR-ART.md)
for the measured results). Two problems are fundamental rather than incidental:

**`CI⁻¹` does not exist.** A cochlear implant discards temporal fine structure. That is not
a side effect to be undone; it is the defining operation. Information destroyed cannot be
recovered, so there is no inverse function to learn. A model asked to produce one is being
asked to hallucinate, and will.

**Training data is intrinsically scarce under this framing.** Learning `sim → act` requires
paired examples. Where the pairing must be validated perceptually, examples come from human
listening sessions, which are slow, fatiguing, and impossible to parallelise. The
predecessor had roughly 36 training examples of 1024 features each; a later proposal in the
same lineage planned to train a neural network on 50–100 samples. Three occurrences of the
same `p ≫ n` failure across four years is a structural problem, not bad luck.

## Decision

**Keep the inverse framing. Move the loss downstream of the simulator.**

Do not train `g` against `d(g(sim), act)`. Train against

```
    L = d( CI( g(x) ), x )
```

where `CI(·)` is the simulator in `prelude.ci_sim` and `d` is a perceptual distance.

Three consequences follow, and each of them is the point:

**1. The model is never asked to recover destroyed information.** It is asked to arrange
the signal so that less is destroyed — a well-posed problem with an achievable optimum. It
also correctly declines to reward changes the implant will discard anyway, which the
upstream formulation cannot distinguish from useful ones.

**2. The problem becomes self-supervised.** `CI(·)` generates its own targets from any
audio whatsoever. No human labels are required, and the data starvation disappears entirely
— training data is limited only by available audio and compute.

**3. Human judgement is repositioned.** Listening sessions no longer supply training data.
They validate the simulator (does `CI(·)` resemble what the listener actually hears?) and
rank a small number of finalists. This is the correct use of a scarce, high-quality
measuring instrument.

**Compute `d` in a perceptual domain, not on raw waveforms.** Per-channel envelope
correlation on the electrodogram is the primary candidate: envelopes are what the device
transmits, and they are insensitive to the sample-level phase shifts that make waveform
distances punish inaudible differences.

## Consequences

**The simulator becomes the loss function, not merely an evaluation tool.** This
substantially raises the stakes on its correctness. A learned `g` will exploit any
inaccuracy in `CI(·)` ruthlessly, producing audio that scores beautifully and sounds worse.
Simulator fidelity now gates the learned approach twice over — once for evaluation, once
for training.

**A differentiable simulator becomes a requirement** for gradient-based training. The
current NumPy/SciPy implementation is not differentiable. Options, in increasing order of
effort: fit a differentiable surrogate; reimplement the chain in a framework with autograd;
or use gradient-free optimisation over a small parameter set. This should influence
implementation choices as the simulator matures — prefer formulations that port cleanly.

**Exhaust parameter search before training anything.** Given a hand-built enhancement chain
with a modest number of parameters, direct search scored by objective metrics and confirmed
by occasional listening tests will capture most of the available benefit at a fraction of
the risk. Learned enhancement is the endgame, not the opening move.

## Alternatives considered

**Train `sim → act` directly, with more data.** Rejected. Additional data does not create an
inverse that does not exist, and the perceptual pairing required cannot be scaled.

**Train against human preference ratings directly.** Rejected as a primary objective for the
same scarcity reason, and because preference ratings are noisy enough that thousands would
be needed. Retained as a *validation* signal.

**Skip learning entirely.** Not rejected, merely deferred. A well-tuned hand-built chain may
prove sufficient, and it is what the roadmap pursues first.
