# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Session construction: blocks, fatigue limits, and catch-trial insertion.

A session is a sequence of blocks, each run in one listening condition. Blocking
matters because device changes are the most disruptive part of a session -
interleaving conditions trial by trial would make the swaps dominate the
experience and would be abandoned.

Everything here exists to protect the data from the two things most likely to
ruin it: **fatigue** and **bias**.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .conditions import ConditionChange, ListeningCondition
from .trial import Stimulus, Trial, TrialKind

#: Active comparison beyond roughly this long degrades discrimination, and
#: fatigued data is indistinguishable from a null result. Enforced, not advised.
MAX_ACTIVE_MINUTES = 20

#: Roughly one trial in six is a catch trial. Fewer gives too noisy an estimate
#: of the response floor; many more wastes scarce listening time on trials that
#: carry no signal about the stimuli.
CATCH_TRIAL_EVERY = 6

#: Estimated wall-clock cost of one trial, for budgeting a session.
SECONDS_PER_TRIAL = 12


@dataclass
class Block:
    """Trials sharing one listening condition."""

    condition: ListeningCondition
    trials: list[Trial]
    purpose: str = ""

    @property
    def estimated_seconds(self) -> int:
        return len(self.trials) * SECONDS_PER_TRIAL


@dataclass
class Session:
    """A complete sitting, ordered and ready to run."""

    session_id: str
    blocks: list[Block]
    participant_code: str
    notes: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def all_trials(self) -> list[Trial]:
        return [t for b in self.blocks for t in b.trials]

    @property
    def trials_by_id(self) -> dict[str, Trial]:
        return {t.trial_id: t for t in self.all_trials}

    @property
    def estimated_minutes(self) -> float:
        active = sum(b.estimated_seconds for b in self.blocks)
        swaps = sum(1 for c in self.condition_changes() if c.is_required)
        return (active + swaps * 60) / 60.0

    def condition_changes(self) -> list[ConditionChange]:
        """Device changes required, in order."""
        changes, previous = [], None
        for block in self.blocks:
            changes.append(ConditionChange(previous, block.condition))
            previous = block.condition
        return changes


class SessionTooLongError(ValueError):
    """Raised when a session would exceed the fatigue limit."""


def build_block(
    condition: ListeningCondition,
    trials: list[Trial],
    rng: random.Random,
    purpose: str = "",
    insert_catches: bool = True,
) -> Block:
    """Shuffle trials and interleave catch trials at irregular intervals.

    Catch positions are jittered rather than fixed, because a participant who
    notices that every sixth trial is identical will treat those trials
    differently and the noise estimate stops being an estimate of anything.
    """
    ordered = list(trials)
    rng.shuffle(ordered)

    if not insert_catches or not ordered:
        return Block(condition=condition, trials=ordered, purpose=purpose)

    out: list[Trial] = []
    since_catch = 0
    for trial in ordered:
        out.append(trial)
        since_catch += 1
        if since_catch >= rng.randint(CATCH_TRIAL_EVERY - 2, CATCH_TRIAL_EVERY + 2):
            out.append(make_catch_trial(rng.choice(ordered), rng))
            since_catch = 0
    return Block(condition=condition, trials=out, purpose=purpose)


def make_catch_trial(model: Trial, rng: random.Random) -> Trial:
    """Build a catch trial by duplicating one stimulus into both slots.

    The participant is asked the same question as a real trial. Because both
    items are identical, any consistent answer measures response bias rather
    than perception.
    """
    stimulus = model.stimuli[0]
    twin = Stimulus(
        stimulus_id=stimulus.stimulus_id + "_twin",
        path=stimulus.path,
        config_hash=stimulus.config_hash,
        source_id=stimulus.source_id,
        description=stimulus.description,
    )
    order = [0, 1]
    rng.shuffle(order)
    return Trial(
        trial_id=Trial.new_id(),
        kind=TrialKind.CATCH,
        condition=model.condition,
        stimuli=(stimulus, twin),
        prompt=model.prompt,
        presentation_order=tuple(order),
        purpose="catch trial - identical stimuli, no correct answer",
    )


def make_2afc_trial(
    condition: ListeningCondition,
    option_a: Stimulus,
    option_b: Stimulus,
    prompt: str,
    rng: random.Random,
    reference: Stimulus | None = None,
    purpose: str = "",
) -> Trial:
    """A blinded two-alternative forced choice.

    Presentation order is randomised here, in the data layer, so no interface
    can present in a fixed order by omission.
    """
    order = [0, 1]
    rng.shuffle(order)
    return Trial(
        trial_id=Trial.new_id(),
        kind=TrialKind.TWO_ALTERNATIVE_CHOICE,
        condition=condition,
        stimuli=(option_a, option_b),
        prompt=prompt,
        presentation_order=tuple(order),
        reference=reference,
        purpose=purpose,
    )


def build_session(
    participant_code: str,
    blocks: list[Block],
    session_id: str | None = None,
    seed: int | None = None,
    enforce_fatigue_limit: bool = True,
) -> Session:
    """Assemble blocks into a session, ordered to minimise device changes.

    Blocks in the same condition are grouped so the participant swaps devices as
    few times as possible.

    Raises
    ------
    SessionTooLongError
        If the session exceeds :data:`MAX_ACTIVE_MINUTES` of active listening.
        This is a hard limit rather than a warning: a session that runs long
        yields data that looks like a null result and cannot be distinguished
        from one, so the trials are not merely wasted but actively misleading.
    """
    rng = random.Random(seed)

    by_condition: dict[ListeningCondition, list[Block]] = {}
    for block in blocks:
        by_condition.setdefault(block.condition, []).append(block)

    ordered: list[Block] = []
    for condition in ListeningCondition:
        ordered.extend(by_condition.get(condition, []))

    session = Session(
        session_id=session_id or f"S{rng.randint(100000, 999999)}",
        blocks=ordered,
        participant_code=participant_code,
    )

    active = sum(b.estimated_seconds for b in ordered) / 60.0
    if enforce_fatigue_limit and active > MAX_ACTIVE_MINUTES:
        raise SessionTooLongError(
            f"{active:.0f} minutes of active listening exceeds the "
            f"{MAX_ACTIVE_MINUTES}-minute limit "
            f"({sum(len(b.trials) for b in ordered)} trials). Split it across "
            f"sittings. Fatigued discrimination data cannot be distinguished "
            f"from a null result, so over-long sessions do not just waste "
            f"trials - they produce misleading ones."
        )
    return session
