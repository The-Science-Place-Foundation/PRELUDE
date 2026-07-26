# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Fitting simulator settings to an individual listener.

Listening time is the binding constraint on this whole project, so the fitter
is built to spend as little of it as possible: a Bayesian posterior over a
pre-rendered candidate pool, updated after each forced choice, with the next
comparison chosen by expected information gain rather than at random.

It reports uncertainty honestly, including the common and important case where
the judgements collected so far do not identify anything.

See ``docs/decisions/ADR-0002-fitting-approach.md``.
"""

from .fitter import (
    CONVERGENCE_THRESHOLD,
    DEFAULT_BETA,
    FitSummary,
    Judgement,
    SimulatorFitter,
)
from .perceptual import CandidatePool, build_candidate_pool, envelope_distance

__all__ = [
    "CONVERGENCE_THRESHOLD",
    "DEFAULT_BETA",
    "CandidatePool",
    "FitSummary",
    "Judgement",
    "SimulatorFitter",
    "build_candidate_pool",
    "envelope_distance",
]
