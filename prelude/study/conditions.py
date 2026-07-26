# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Listening conditions for bimodal participants.

A bimodal listener - cochlear implant on one side, acoustic hearing aid on the
other - can remove either device, giving three distinct listening conditions.
That is methodologically valuable, because it lets the same person report on
electric and acoustic hearing separately and in combination.

It also introduces a trap. Participants commonly report that in the combined
condition the percept feels *natural*, as though the brain fills in what each
device alone is missing. The bimodal-benefit literature documents the
performance advantage; what participants describe subjectively is the perceptual
fusion behind it.

The consequence for study design is direct: **a judgement made in the combined
condition is not a clean readout of what the implant delivers.** Anything
intended to characterise the electric percept must be collected with the
contralateral device removed. Conversely, anything intended to predict
real-world benefit should be collected in the combined condition, because that
is how the person actually listens.

Those two purposes pull in opposite directions and must not be mixed within a
block. See :class:`ListeningCondition` for which to use when.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ListeningCondition(str, Enum):
    """Which devices the participant is wearing for a block of trials."""

    #: Both devices. How the person actually listens day to day, and therefore
    #: the right condition for judging whether processing helps in real use.
    #: **Not** a clean readout of the implant - perceptual fusion with the
    #: acoustic ear masks what the implant alone conveys.
    BIMODAL = "bimodal"

    #: Implant only, contralateral device removed. The clean electric percept,
    #: and the only condition in which the simulator can be fitted.
    CI_ONLY = "ci_only"

    #: Acoustic device only, implant removed. Used to *present* candidate
    #: simulations: a simulation is an acoustic signal, so it must be heard
    #: acoustically to be compared against a remembered electric percept.
    HA_ONLY = "ha_only"

    @property
    def label(self) -> str:
        return {
            "bimodal": "Both devices",
            "ci_only": "Implant only",
            "ha_only": "Hearing aid only",
        }[self.value]

    @property
    def instruction(self) -> str:
        """Plain-language instruction shown to the participant."""
        return {
            "bimodal": "Wear both devices as you normally would.",
            "ci_only": "Please take out your hearing aid. Keep your implant on.",
            "ha_only": "Please take off your implant. Keep your hearing aid in.",
        }[self.value]

    @property
    def isolates_electric(self) -> bool:
        """True when this condition reads the implant without acoustic fill-in."""
        return self is ListeningCondition.CI_ONLY


@dataclass(frozen=True)
class ConditionChange:
    """A device change the participant must make between blocks.

    Device swaps are the most disruptive part of a session - they take time,
    they break concentration, and each one is an opportunity to abandon the
    session. Sessions should therefore be **blocked by condition** rather than
    interleaving conditions trial by trial.

    ``settle_seconds`` exists because loudness perception shifts for a short
    period after a device is reinserted, and a judgement made during that window
    measures the adaptation rather than the stimulus.
    """

    from_condition: ListeningCondition | None
    to_condition: ListeningCondition
    settle_seconds: int = 30

    @property
    def is_required(self) -> bool:
        return self.from_condition is not self.to_condition

    @property
    def prompt(self) -> str:
        if not self.is_required:
            return ""
        return (
            f"{self.to_condition.instruction}\n\n"
            f"Take a moment to let your hearing settle - about "
            f"{self.settle_seconds} seconds - before continuing."
        )


#: Which condition each experiment type must be run in, and why.
CONDITION_FOR_PURPOSE: dict[str, tuple[ListeningCondition, str]] = {
    "simulator_fitting_target": (
        ListeningCondition.CI_ONLY,
        "Establishing what the implant actually sounds like. Acoustic fill-in "
        "from the contralateral device would contaminate the reading.",
    ),
    "simulator_fitting_candidate": (
        ListeningCondition.HA_ONLY,
        "A candidate simulation is an acoustic signal and must be heard "
        "acoustically, so it can be compared against the remembered electric "
        "percept.",
    ),
    "enhancement_preference": (
        ListeningCondition.BIMODAL,
        "Predicting real-world benefit, so the condition should match how the "
        "person actually listens.",
    ),
    "enhancement_ci_only": (
        ListeningCondition.CI_ONLY,
        "Isolating whether processing helps the implant itself, rather than "
        "helping by complementing the acoustic ear.",
    ),
}
