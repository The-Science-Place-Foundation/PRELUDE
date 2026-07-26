# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Trials: the unit of perceptual data collection.

A trial presents stimuli and records one judgement. Everything that protects the
data - blinding, catch trials, level matching - is enforced here rather than left
to the interface, so that a new front end cannot accidentally omit it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from .conditions import ListeningCondition


class TrialKind(str, Enum):
    #: "Which of these is closer to X?" - the workhorse. Forced choice between
    #: two candidates beats asking for a rating, because people are far better
    #: at comparing than at placing an absolute value on a sensation.
    TWO_ALTERNATIVE_CHOICE = "2afc"

    #: Two identical stimuli presented as though different. Has no correct
    #: answer; its purpose is to measure how often the participant reports a
    #: difference where none exists. Without that floor, a 60% preference is
    #: uninterpretable.
    CATCH = "catch"

    #: Adjust a parameter until it matches a reference. Slower than forced
    #: choice but converges faster per unit of listening time when the
    #: parameter is continuous and the participant is confident.
    ADJUSTMENT = "adjustment"

    #: Free description. Generates hypotheses and vocabulary; cannot test them.
    DESCRIPTION = "description"


@dataclass(frozen=True)
class Stimulus:
    """One audio item in a trial.

    ``path`` is local; audio is never uploaded. ``config_hash`` ties the item
    back to the exact simulator or enhancer settings that produced it, so a
    result remains interpretable after the code has moved on.
    """

    stimulus_id: str
    path: str
    config_hash: str | None = None
    source_id: str | None = None
    description: str = ""

    #: Set by the presentation layer after loudness normalisation. A trial
    #: whose stimuli were not level-matched measures the level difference.
    normalised_lufs: float | None = None


@dataclass(frozen=True)
class Trial:
    """A single judgement to be collected.

    Attributes
    ----------
    presentation_order:
        Indices into ``stimuli``, randomised per trial. The interface must
        present in this order and must not reveal which item is which - the
        participant is frequently the investigator's partner, and unblinded
        comparison in that situation is not a small bias.
    """

    trial_id: str
    kind: TrialKind
    condition: ListeningCondition
    stimuli: tuple[Stimulus, ...]
    prompt: str
    presentation_order: tuple[int, ...]
    reference: Stimulus | None = None
    purpose: str = ""
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]

    @property
    def is_catch(self) -> bool:
        return self.kind is TrialKind.CATCH

    def presented(self) -> list[Stimulus]:
        """Stimuli in the order the participant will hear them."""
        return [self.stimuli[i] for i in self.presentation_order]

    def resolve_choice(self, presented_index: int) -> Stimulus:
        """Map a choice made against the shuffled order back to its stimulus.

        The interface knows only "the participant picked the second one". This
        undoes the blinding for analysis.
        """
        if not 0 <= presented_index < len(self.presentation_order):
            raise ValueError(
                f"presented_index {presented_index} out of range for "
                f"{len(self.presentation_order)} stimuli"
            )
        return self.stimuli[self.presentation_order[presented_index]]


@dataclass(frozen=True)
class TrialResult:
    """What the participant reported, plus the context needed to interpret it.

    Raw per-trial records are retained rather than only summaries: a summary can
    always be recomputed, but discarded raw data cannot be recovered, and
    listening sessions are not repeatable under identical conditions when
    hearing is changing.
    """

    trial_id: str
    presented_index: int | None
    response_ms: int
    confidence: int | None = None
    comment: str = ""
    skipped: bool = False

    #: Trial number within the session. Used to check for drift as fatigue
    #: accumulates - if late trials differ systematically from early ones, the
    #: session ran too long.
    position_in_session: int = 0

    def __post_init__(self) -> None:
        if self.confidence is not None and not 1 <= self.confidence <= 5:
            raise ValueError(f"confidence must be 1-5, got {self.confidence}")
        if not self.skipped and self.presented_index is None:
            raise ValueError("a non-skipped trial must record a choice")


def catch_trial_rate(results: list[TrialResult], trials: dict[str, Trial]) -> float | None:
    """Fraction of catch trials on which a difference was reported.

    Catch trials present the same stimulus twice. Any consistent preference is
    noise, so this estimates the participant's response noise floor.

    Interpretation: near 0.5 is ideal, meaning choices on identical pairs were
    at chance. Values far from 0.5 indicate a position bias - always picking the
    first or second item - which inflates apparent effects elsewhere and means
    the session's other results should be treated with caution.

    Returns ``None`` when no catch trials were run, which is itself a finding:
    the session has no noise floor and its effect sizes cannot be calibrated.
    """
    catches = [r for r in results if not r.skipped and trials[r.trial_id].is_catch]
    if not catches:
        return None
    return sum(1 for r in catches if r.presented_index == 0) / len(catches)
