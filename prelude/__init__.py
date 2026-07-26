"""PRELUDE - Pre-Rendering for Enhanced Listening Under Degraded Encoding.

An open-source toolkit for cochlear implant audio simulation and pre-processing
research.

A cochlear implant's sound processor cannot be modified: its filterbank, channel
selection, loudness mapping and stimulation are fixed firmware plus a clinical
program. The only available point of intervention is *upstream* - the audio
presented to the device. PRELUDE provides the two pieces that requires:

``prelude.ci_sim``
    A simulator that models what a given implant does to audio, so that
    processing can be evaluated without occupying a human listener for every
    iteration.

``prelude.enhance``
    Pre-processing transforms intended to make more of the original survive that
    transformation.

Formally, the goal is to find ``g`` minimising ``d(CI(g(x)), x)`` - note that the
distance is measured *after* the implant's processing, not before it. See
``docs/decisions/ADR-0003-learning-formulation.md`` for why that placement is the
whole problem.

Safety: any signal that may reach a human ear must pass through
:func:`prelude.audio.loudness.prepare_for_playback` first.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
