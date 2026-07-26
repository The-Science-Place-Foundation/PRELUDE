# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Local storage and export of session data.

**Perceptual session records are health information.** They stay on the
participant's device, are exported deliberately by the participant, and are never
uploaded automatically. There is no sync client here by design.

Exports carry a de-identified participant code and never a name. Audio is
referenced by path and hash but never embedded, so an export can be shared for
analysis without carrying a recording of anyone's voice.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .session import Session
from .trial import Trial, TrialResult, catch_trial_rate

#: Bump when the export shape changes, so old files remain readable.
EXPORT_SCHEMA_VERSION = 1


def export_session(
    path: str | Path,
    session: Session,
    results: list[TrialResult],
    started_at: str,
    finished_at: str,
    device_notes: dict | None = None,
    audiogram_date: str | None = None,
) -> Path:
    """Write one session to a JSON file.

    Parameters
    ----------
    started_at, finished_at:
        ISO-8601 timestamps, supplied by the caller rather than read from the
        clock so that exports are reproducible and testable.
    device_notes:
        Processor model, program slot, streaming path, playback volume. Recorded
        because a result is only interpretable alongside the device state that
        produced it.
    audiogram_date:
        When the contralateral ear was last measured. Where hearing is
        progressive, a result from six months ago was measured on a different
        instrument, and comparing across that gap without knowing is a mistake.

    Notes
    -----
    Raw per-trial records are written in full. Summaries can always be
    recomputed; discarded raw data cannot be recovered, and these sessions are
    not repeatable under identical conditions.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    trials = session.trials_by_id
    unknown = [r.trial_id for r in results if r.trial_id not in trials]
    if unknown:
        raise ValueError(f"results reference unknown trials: {unknown[:5]}")

    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "session_id": session.session_id,
        "participant_code": session.participant_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "audiogram_date": audiogram_date,
        "device_notes": device_notes or {},
        "notes": session.notes,
        "metadata": session.metadata,
        "blocks": [
            {
                "condition": b.condition.value,
                "purpose": b.purpose,
                "trial_ids": [t.trial_id for t in b.trials],
            }
            for b in session.blocks
        ],
        "trials": [_trial_dict(t) for t in session.all_trials],
        "results": [asdict(r) for r in results],
        "summary": summarise(session, results),
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def _trial_dict(trial: Trial) -> dict:
    d = asdict(trial)
    d["kind"] = trial.kind.value
    d["condition"] = trial.condition.value
    return d


def summarise(session: Session, results: list[TrialResult]) -> dict:
    """Session-level summary, including the figures needed to judge validity.

    ``catch_trial_bias`` and ``response_time_drift`` are reported prominently
    because a session can produce a clean-looking effect and still be worthless
    if the participant was guessing with a position bias or was fatigued by the
    end.
    """
    trials = session.trials_by_id
    answered = [r for r in results if not r.skipped]

    catch_bias = catch_trial_rate(results, trials)
    drift = None
    if len(answered) >= 8:
        half = len(answered) // 2
        early = sum(r.response_ms for r in answered[:half]) / half
        late = sum(r.response_ms for r in answered[half:]) / (len(answered) - half)
        drift = round(late / early, 3) if early > 0 else None

    per_condition: dict[str, int] = {}
    for r in answered:
        c = trials[r.trial_id].condition.value
        per_condition[c] = per_condition.get(c, 0) + 1

    warnings = []
    if catch_bias is None:
        warnings.append(
            "No catch trials were run, so there is no response-noise floor and "
            "effect sizes in this session cannot be calibrated."
        )
    elif abs(catch_bias - 0.5) > 0.25:
        warnings.append(
            f"Catch-trial responses were {catch_bias:.0%} toward one side, "
            f"indicating a strong position bias. Treat other results with "
            f"caution."
        )
    if drift is not None and drift > 1.5:
        warnings.append(
            f"Response times rose {drift:.1f}x from the first half to the "
            f"second, which suggests fatigue. Later trials may be unreliable."
        )
    if len(answered) < len(session.all_trials) * 0.8:
        warnings.append(
            f"Only {len(answered)} of {len(session.all_trials)} trials were "
            f"answered; the session may have been abandoned partway."
        )

    return {
        "trials_presented": len(session.all_trials),
        "trials_answered": len(answered),
        "trials_skipped": sum(1 for r in results if r.skipped),
        "trials_by_condition": per_condition,
        "catch_trial_bias": catch_bias,
        "response_time_drift": drift,
        "median_response_ms": (
            sorted(r.response_ms for r in answered)[len(answered) // 2]
            if answered
            else None
        ),
        "validity_warnings": warnings,
    }


def load_session_export(path: str | Path) -> dict:
    """Read an exported session, checking the schema version."""
    data = json.loads(Path(path).read_text())
    version = data.get("schema_version")
    if version != EXPORT_SCHEMA_VERSION:
        raise ValueError(
            f"export schema version {version} does not match the expected "
            f"{EXPORT_SCHEMA_VERSION}; migrate the file before loading"
        )
    return data
