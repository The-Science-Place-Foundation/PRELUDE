# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Tests for the listening-study tooling.

These check the protections, not the plumbing. Blinding, catch trials and
fatigue limits exist to stop a session producing confident nonsense, so they are
what the tests assert on.
"""

from __future__ import annotations

import json
import random

import numpy as np
import pytest

from prelude.study import (
    Block,
    Ear,
    EarAssignment,
    ListeningCondition,
    PresentationMode,
    SessionTooLongError,
    Stimulus,
    TrialResult,
    build_block,
    build_dichotic,
    build_session,
    catch_trial_rate,
    export_session,
    load_session_export,
    make_2afc_trial,
    summarise,
)


def stim(i: int) -> Stimulus:
    return Stimulus(stimulus_id=f"s{i}", path=f"/local/s{i}.wav", config_hash=f"h{i}")


def trials(n: int, rng: random.Random, condition=ListeningCondition.CI_ONLY):
    return [
        make_2afc_trial(condition, stim(i), stim(i + 100), "Which is closer?", rng)
        for i in range(n)
    ]


class TestBlinding:
    def test_presentation_order_is_randomised(self):
        rng = random.Random(0)
        orders = {make_2afc_trial(
            ListeningCondition.CI_ONLY, stim(1), stim(2), "?", rng
        ).presentation_order for _ in range(40)}
        assert orders == {(0, 1), (1, 0)}, "presentation order is not being shuffled"

    def test_choice_resolves_through_the_shuffle(self):
        rng = random.Random(3)
        for _ in range(20):
            t = make_2afc_trial(ListeningCondition.CI_ONLY, stim(1), stim(2), "?", rng)
            first = t.presented()[0]
            assert t.resolve_choice(0) is first

    def test_out_of_range_choice_raises(self):
        t = make_2afc_trial(
            ListeningCondition.CI_ONLY, stim(1), stim(2), "?", random.Random(0)
        )
        with pytest.raises(ValueError, match="out of range"):
            t.resolve_choice(5)


class TestCatchTrials:
    def test_catches_are_inserted(self):
        rng = random.Random(1)
        block = build_block(ListeningCondition.CI_ONLY, trials(24, rng), rng)
        assert sum(1 for t in block.trials if t.is_catch) >= 3

    def test_catch_stimuli_are_identical(self):
        rng = random.Random(2)
        block = build_block(ListeningCondition.CI_ONLY, trials(20, rng), rng)
        for t in block.trials:
            if t.is_catch:
                assert t.stimuli[0].path == t.stimuli[1].path

    def test_catch_spacing_is_jittered(self):
        """Fixed spacing would let a participant learn to spot catch trials."""
        rng = random.Random(4)
        block = build_block(ListeningCondition.CI_ONLY, trials(60, rng), rng)
        idx = [i for i, t in enumerate(block.trials) if t.is_catch]
        gaps = {b - a for a, b in zip(idx[:-1], idx[1:], strict=True)}
        assert len(gaps) > 1, "catch trials fall at a fixed interval"

    def test_bias_detection(self):
        rng = random.Random(5)
        block = build_block(ListeningCondition.CI_ONLY, trials(20, rng), rng)
        by_id = {t.trial_id: t for t in block.trials}
        catches = [t for t in block.trials if t.is_catch]
        biased = [TrialResult(t.trial_id, 0, 900) for t in catches]
        assert catch_trial_rate(biased, by_id) == 1.0
        unbiased = [
            TrialResult(t.trial_id, i % 2, 900) for i, t in enumerate(catches)
        ]
        assert 0.2 < catch_trial_rate(unbiased, by_id) < 0.8

    def test_no_catches_reports_none(self):
        rng = random.Random(6)
        block = build_block(
            ListeningCondition.CI_ONLY, trials(5, rng), rng, insert_catches=False
        )
        by_id = {t.trial_id: t for t in block.trials}
        results = [TrialResult(t.trial_id, 0, 800) for t in block.trials]
        assert catch_trial_rate(results, by_id) is None


class TestFatigueLimit:
    def test_long_session_is_rejected(self):
        """A hard error, not a warning - fatigued data mimics a null result."""
        rng = random.Random(7)
        block = Block(ListeningCondition.CI_ONLY, trials(300, rng))
        with pytest.raises(SessionTooLongError, match="exceeds"):
            build_session("P01", [block])

    def test_reasonable_session_is_accepted(self):
        rng = random.Random(8)
        block = build_block(ListeningCondition.CI_ONLY, trials(40, rng), rng)
        s = build_session("P01", [block])
        assert s.estimated_minutes < 20


class TestConditions:
    def test_blocks_are_grouped_to_minimise_swaps(self):
        rng = random.Random(9)
        blocks = [
            Block(ListeningCondition.CI_ONLY, trials(4, rng)),
            Block(ListeningCondition.HA_ONLY, trials(4, rng)),
            Block(ListeningCondition.CI_ONLY, trials(4, rng)),
        ]
        s = build_session("P01", blocks)
        conditions = [b.condition for b in s.blocks]
        required = [c for c in s.condition_changes() if c.is_required]
        assert len(required) <= len(set(conditions))

    def test_only_ci_only_isolates_electric_hearing(self):
        assert ListeningCondition.CI_ONLY.isolates_electric
        assert not ListeningCondition.BIMODAL.isolates_electric
        assert not ListeningCondition.HA_ONLY.isolates_electric

    def test_change_prompt_names_the_device(self):
        rng = random.Random(10)
        s = build_session("P01", [Block(ListeningCondition.HA_ONLY, trials(3, rng))])
        assert "implant" in s.condition_changes()[0].prompt.lower()


class TestExport:
    def test_roundtrip_and_no_identifiers(self, tmp_path):
        rng = random.Random(11)
        block = build_block(ListeningCondition.CI_ONLY, trials(12, rng), rng)
        s = build_session("P01", [block], session_id="S000001")
        results = [
            TrialResult(t.trial_id, i % 2, 800 + i, position_in_session=i)
            for i, t in enumerate(s.all_trials)
        ]
        p = export_session(
            tmp_path / "s.json", s, results,
            started_at="2026-07-25T10:00:00Z", finished_at="2026-07-25T10:14:00Z",
            device_notes={"processor": "generic"}, audiogram_date="2026-06-01",
        )
        data = load_session_export(p)
        assert data["participant_code"] == "P01"
        assert len(data["results"]) == len(s.all_trials)
        assert data["audiogram_date"] == "2026-06-01"
        # No audio is embedded - only paths and hashes.
        assert "wav" not in json.dumps(data["results"])

    def test_unknown_trial_reference_raises(self, tmp_path):
        rng = random.Random(12)
        s = build_session("P01", [build_block(ListeningCondition.CI_ONLY, trials(4, rng), rng)])
        with pytest.raises(ValueError, match="unknown trials"):
            export_session(tmp_path / "s.json", s, [TrialResult("nope", 0, 500)],
                           started_at="x", finished_at="y")

    def test_schema_version_mismatch_raises(self, tmp_path):
        p = tmp_path / "old.json"
        p.write_text(json.dumps({"schema_version": 999}))
        with pytest.raises(ValueError, match="schema version"):
            load_session_export(p)


class TestValidityWarnings:
    def test_position_bias_is_flagged(self):
        rng = random.Random(13)
        block = build_block(ListeningCondition.CI_ONLY, trials(20, rng), rng)
        s = build_session("P01", [block])
        results = [TrialResult(t.trial_id, 0, 900) for t in s.all_trials]
        warnings = summarise(s, results)["validity_warnings"]
        assert any("position bias" in w for w in warnings)

    def test_fatigue_drift_is_flagged(self):
        rng = random.Random(14)
        block = build_block(ListeningCondition.CI_ONLY, trials(20, rng), rng)
        s = build_session("P01", [block])
        n = len(s.all_trials)
        results = [
            TrialResult(t.trial_id, i % 2, 500 if i < n // 2 else 3000)
            for i, t in enumerate(s.all_trials)
        ]
        assert any("fatigue" in w for w in summarise(s, results)["validity_warnings"])

    def test_missing_catch_trials_is_flagged(self):
        rng = random.Random(15)
        block = build_block(
            ListeningCondition.CI_ONLY, trials(8, rng), rng, insert_catches=False
        )
        s = build_session("P01", [block])
        results = [TrialResult(t.trial_id, i % 2, 800) for i, t in enumerate(s.all_trials)]
        assert any("noise floor" in w for w in summarise(s, results)["validity_warnings"])

    def test_clean_session_has_no_warnings(self):
        rng = random.Random(16)
        block = build_block(ListeningCondition.CI_ONLY, trials(20, rng), rng)
        s = build_session("P01", [block])
        results = [
            TrialResult(t.trial_id, i % 2, 800 + (i % 3) * 10)
            for i, t in enumerate(s.all_trials)
        ]
        assert summarise(s, results)["validity_warnings"] == []


class TestDichotic:
    """Different audio to each ear from one stereo file.

    This is what makes direct comparison possible without device swaps: the
    implanted ear hears a source and produces the electric percept, while the
    contralateral ear hears a candidate simulation of it.
    """

    SR = 20000

    def _signals(self):
        t = np.arange(self.SR) / self.SR
        return 0.2 * np.sin(2 * np.pi * 220 * t), 0.2 * np.sin(2 * np.pi * 880 * t)

    def test_ear_assignment_has_no_default(self):
        """Getting this backwards silently inverts the experiment."""
        with pytest.raises(TypeError):
            EarAssignment()

    def test_signal_reaches_the_assigned_ear(self):
        src, cand = self._signals()
        for implant_ear in (Ear.LEFT, Ear.RIGHT):
            d = build_dichotic(
                src, cand, self.SR, EarAssignment(implant_ear),
                mode=PresentationMode.SIMULTANEOUS,
            )
            impl = d.channel(implant_ear)
            ac = d.channel(implant_ear.other)
            # The implant ear carries 220 Hz, the acoustic ear 880 Hz.
            f = np.fft.rfftfreq(len(impl), 1 / self.SR)
            assert f[np.argmax(np.abs(np.fft.rfft(impl)))] == pytest.approx(220, abs=5)
            assert f[np.argmax(np.abs(np.fft.rfft(ac)))] == pytest.approx(880, abs=5)

    def test_alternating_isolates_the_ears(self):
        """Only one ear carries signal at a time, so there is nothing to fuse."""
        src, cand = self._signals()
        d = build_dichotic(
            src, cand, self.SR, EarAssignment(Ear.RIGHT),
            mode=PresentationMode.ALTERNATING, segment_ms=250,
        )
        both = (np.abs(d.samples[0]) > 1e-4) & (np.abs(d.samples[1]) > 1e-4)
        assert both.mean() < 0.01, "ears overlap during alternation"

    def test_simultaneous_does_not_isolate(self):
        src, cand = self._signals()
        d = build_dichotic(
            src, cand, self.SR, EarAssignment(Ear.RIGHT),
            mode=PresentationMode.SIMULTANEOUS,
        )
        both = (np.abs(d.samples[0]) > 1e-4) & (np.abs(d.samples[1]) > 1e-4)
        assert both.mean() > 0.9

    def test_each_channel_is_level_matched_independently(self):
        """Electric and acoustic loudness growth differ; channels normalise apart."""
        src, cand = self._signals()
        d = build_dichotic(
            src * 10, cand * 0.01, self.SR, EarAssignment(Ear.RIGHT),
            mode=PresentationMode.SIMULTANEOUS,
        )
        assert d.implant_lufs == pytest.approx(d.acoustic_lufs, abs=1.0)

    def test_alternation_has_no_clicks(self):
        """Abrupt switching would click, which is unpleasant and an extra cue."""
        src, cand = self._signals()
        d = build_dichotic(
            src, cand, self.SR, EarAssignment(Ear.RIGHT),
            mode=PresentationMode.ALTERNATING, segment_ms=250, ramp_ms=10,
        )
        step = np.abs(np.diff(d.samples[0])).max()
        assert step < 0.1, f"discontinuity of {step:.3f} at a segment boundary"

    def test_sequential_is_longer_than_its_parts(self):
        src, cand = self._signals()
        d = build_dichotic(
            src, cand, self.SR, EarAssignment(Ear.RIGHT),
            mode=PresentationMode.SEQUENTIAL,
        )
        assert d.duration_s > 2.0

    def test_rejects_stereo_input(self):
        src, cand = self._signals()
        with pytest.raises(ValueError, match="mono"):
            build_dichotic(
                np.stack([src, src]), cand, self.SR, EarAssignment(Ear.RIGHT)
            )
