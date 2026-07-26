# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Listening-study tooling: conditions, trials, sessions, local export.

Built for bimodal participants, who can remove either device and so can report
on electric hearing, acoustic hearing, and the two combined.

Three things are enforced here rather than left to an interface, because an
interface can omit them by accident and the resulting data looks fine:

**Blinding and randomisation** happen when a trial is constructed, so
presentation order cannot be fixed by omission.

**Catch trials** are inserted automatically at jittered intervals. Without a
response-noise floor, a preference figure means nothing.

**Fatigue limits** are a hard error, not a warning. Data collected past the
point of fatigue is indistinguishable from a null result, so an over-long
session does not merely waste trials - it produces misleading ones.

See ``docs/05-EVALUATION-PROTOCOL.md`` for the reasoning, and
``prelude.study.conditions`` for why a judgement made while wearing both devices
cannot be used to characterise the implant.
"""

from .conditions import CONDITION_FOR_PURPOSE, ConditionChange, ListeningCondition
from .session import (
    CATCH_TRIAL_EVERY,
    MAX_ACTIVE_MINUTES,
    Block,
    Session,
    SessionTooLongError,
    build_block,
    build_session,
    make_2afc_trial,
    make_catch_trial,
)
from .storage import EXPORT_SCHEMA_VERSION, export_session, load_session_export, summarise
from .trial import Stimulus, Trial, TrialKind, TrialResult, catch_trial_rate

__all__ = [
    "CATCH_TRIAL_EVERY",
    "CONDITION_FOR_PURPOSE",
    "EXPORT_SCHEMA_VERSION",
    "MAX_ACTIVE_MINUTES",
    "Block",
    "ConditionChange",
    "ListeningCondition",
    "Session",
    "SessionTooLongError",
    "Stimulus",
    "Trial",
    "TrialKind",
    "TrialResult",
    "build_block",
    "build_session",
    "catch_trial_rate",
    "export_session",
    "load_session_export",
    "make_2afc_trial",
    "make_catch_trial",
    "summarise",
]
