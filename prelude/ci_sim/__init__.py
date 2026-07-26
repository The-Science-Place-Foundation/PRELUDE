"""Cochlear implant simulation.

Models the signal chain of a CI sound processor so that the perceptual effect of
audio processing can be evaluated without occupying a human listener for every
iteration.

The stages mirror a real device: an analysis filterbank splits the input into
channels, an envelope is extracted per channel, a selection stage keeps only the
strongest channels (n-of-m), a loudness map compresses into the narrow electrical
dynamic range, current spread smears across neighbouring channels, and
resynthesis makes the result audible.

See ``docs/01-DOMAIN-PRIMER.md`` for the underlying physiology and
``docs/04-ARCHITECTURE.md`` for how these fit together.
"""

from .envelope import envelope_modulation_depth, extract_envelope
from .filterbank import (
    Filterbank,
    design_filterbank,
    erb_space,
    greenwood_frequency,
    greenwood_position,
    greenwood_space,
)
from .interaction import apply_interaction, effective_channels, spread_matrix
from .mapping import LoudnessMap, apply_loudness_map, invert_loudness_map
from .pipeline import SimulationResult, SimulatorConfig, simulate
from .resynthesis import resynthesise
from .selection import select_n_of_m, selection_stability

__all__ = [
    "Filterbank",
    "LoudnessMap",
    "SimulationResult",
    "SimulatorConfig",
    "apply_interaction",
    "apply_loudness_map",
    "design_filterbank",
    "effective_channels",
    "envelope_modulation_depth",
    "erb_space",
    "extract_envelope",
    "greenwood_frequency",
    "greenwood_position",
    "greenwood_space",
    "invert_loudness_map",
    "resynthesise",
    "select_n_of_m",
    "selection_stability",
    "simulate",
    "spread_matrix",
]
