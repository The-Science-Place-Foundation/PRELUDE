# PRELUDE Documentation

| Document | Purpose |
|---|---|
| [01 — Domain Primer](01-DOMAIN-PRIMER.md) | Cochlear implant physiology, audiology, and DSP grounding. **Read before writing or reviewing DSP code.** |
| [03 — Prior Art](03-PRIOR-ART.md) | Existing simulators this builds on, and defects in the predecessor codebase that shaped this design |
| [04 — Architecture](04-ARCHITECTURE.md) | System design and stage contracts |
| [05 — Evaluation Protocol](05-EVALUATION-PROTOCOL.md) | Objective metrics and listening-study protocol |

**[decisions/](decisions/)** — Architecture Decision Records
- [ADR-0001](decisions/ADR-0001-learning-formulation.md) — measure the loss after the simulator, not before it

**[lab-notebook/](lab-notebook/)** — dated experiment logs
- [TEMPLATE-session.md](lab-notebook/TEMPLATE-session.md) — copy for each listening session
- [2026-07-25](lab-notebook/2026-07-25-reference-simulator-comparison.md) — first external-reference comparison; one defect found, headline disagreement unresolved

---

## Three things to know before contributing

**1. This domain produces plausible-sounding wrong answers.** A simulation can sound
convincingly "implant-like" while modelling entirely the wrong degradation. Sounding
degraded is not evidence of correctness. Several tests in `tests/test_ci_sim.py` exist
specifically because a predecessor made exactly this mistake and did not notice for months.

**2. Under n-of-m coding, adding energy can delete information.** Only the *n* loudest of
*m* bands are transmitted per frame. Content that fails to win that contest is dropped
entirely, and new content can evict existing content. Enhancement is a competitive
allocation problem, not an additive one — which is why de-cluttering often beats boosting.

**3. Human listening data is the measuring instrument, not the training set.** It is slow,
fatiguing, impossible to parallelise, and in progressive hearing loss its supply diminishes
over time. Any design requiring large quantities of it will fail. See
[ADR-0001](decisions/ADR-0001-learning-formulation.md).
