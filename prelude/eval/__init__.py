"""Objective metrics — for rationing scarce listening time, not replacing it.

Not yet implemented. Planned measures, computed on the electrodogram rather than
the waveform wherever possible: per-channel envelope correlation, envelope
modulation depth, n-of-m selection stability, spectral contrast, NCM, ESTOI,
onset-detection agreement, and melodic contour agreement.

**None of these are validated against cochlear implant percepts.** Optimising any
of them directly is a known failure mode that produces audio scoring well and
sounding worse. They exist to catch regressions and to rank candidates before
spending human listening time, which remains the ground truth. See
``docs/05-EVALUATION-PROTOCOL.md``.
"""

__all__: list[str] = []
