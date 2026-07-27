"""Identity rules for candidate pools.

A pool is the referent for every judgement recorded against it. Two failures
in this area nearly corrupted real listening data, and both are encoded here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from prelude.ci_sim import SimulatorConfig

BUILDER = Path(__file__).resolve().parents[1] / "scripts" / "make_candidate_pool.py"


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("make_candidate_pool", BUILDER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BASE = dict(n_channels=19, n_selected=8, carrier="noise",
            envelope_cutoff_hz=300.0, interaction_decay_db=8.0,
            stimulation_rate_hz=900.0, low_freq=300.0, high_freq=8500.0, seed=0)

PRESENTATION = {
    "source": "clip.wav", "seconds": 6.0, "sample_rate": 20000,
    "implant_ear": "right", "balance_db": 0.0, "mode": "alternating",
    "segment_ms": 500, "common_lufs": -26.5,
}


class TestRenderIdentity:
    """The filename must change whenever the bytes change.

    ``/audio/`` is served ``immutable`` with a year-long max-age, so a name
    reused for different audio means a phone with a warm cache plays the old
    sound and has the choice scored against the new one.

    The first attempt hashed the simulator config alone. That was not enough:
    a pool rendered with the ear balance baked in and one rendered without it
    produced identical audio filenames and an identical pool id for twenty
    genuinely different stimuli. Caught by measurement before either was
    deployed.
    """

    def test_balance_changes_the_render_id(self, builder):
        cfg = SimulatorConfig(**BASE)
        a = builder._render_id(cfg, {**PRESENTATION, "balance_db": 0.0})
        b = builder._render_id(cfg, {**PRESENTATION, "balance_db": 6.0})
        assert a != b, "the exact collision that shipped two identical filenames"

    @pytest.mark.parametrize("field,value", [
        ("source", "other.wav"),
        ("seconds", 8.0),
        ("implant_ear", "left"),
        ("segment_ms", 250),
        ("mode", "simultaneous"),
        ("common_lufs", -23.0),
        ("sample_rate", 16000),
    ])
    def test_any_presentation_change_changes_the_render_id(self, builder, field, value):
        cfg = SimulatorConfig(**BASE)
        base = builder._render_id(cfg, PRESENTATION)
        assert builder._render_id(cfg, {**PRESENTATION, field: value}) != base

    def test_simulator_change_changes_the_render_id(self, builder):
        a = builder._render_id(SimulatorConfig(**BASE), PRESENTATION)
        b = builder._render_id(SimulatorConfig(**{**BASE, "n_channels": 21}), PRESENTATION)
        assert a != b

    def test_identical_inputs_give_identical_ids(self, builder):
        """Rebuilding unchanged must not churn filenames and bust every cache."""
        cfg = SimulatorConfig(**BASE)
        assert (builder._render_id(cfg, PRESENTATION)
                == builder._render_id(cfg, dict(PRESENTATION)))


class TestConfigIdentity:
    """``config_id`` answers a different question and must stay simulator-only.

    It is what relates a candidate across pools - "the same simulator settings,
    whatever either pool called it". Folding presentation into it would break
    that, which is why the two ids are separate rather than one.
    """

    def test_presentation_does_not_affect_config_id(self, builder):
        cfg = SimulatorConfig(**BASE)
        assert builder._config_id(cfg) == builder._config_id(cfg)

    def test_config_id_tracks_the_parameters_under_test(self, builder):
        base = builder._config_id(SimulatorConfig(**BASE))
        for field, value in (("n_channels", 21), ("n_selected", 4),
                             ("carrier", "pulse"), ("envelope_cutoff_hz", 900.0),
                             ("stimulation_rate_hz", 500.0),
                             ("interaction_decay_db", 16.0)):
            assert builder._config_id(SimulatorConfig(**{**BASE, field: value})) != base, (
                f"{field} varies between candidates; an id blind to it would "
                f"make two different sounds indistinguishable in the record")


class TestAssetCarryForward:
    """The app fetches two stimuli by fixed name.

    A rebuilt pool without them breaks the channel-separation check and the
    balance staircase - the calibration the pool's own levels depend on. This
    shipped: the first rebuild produced a pool missing both, and the app would
    have failed at the first tap.
    """

    def test_finds_an_asset_in_the_live_pool(self, builder, tmp_path):
        (tmp_path / "pool").mkdir()
        (tmp_path / "pool" / "channel_check.wav").write_bytes(b"RIFF")
        (tmp_path / "pool_new").mkdir()
        found = builder._find_prior_asset(tmp_path / "pool_new", "channel_check.wav")
        assert found is not None and found.parent.name == "pool"

    def test_prefers_the_live_pool_over_an_archive(self, builder, tmp_path):
        (tmp_path / "pool").mkdir()
        (tmp_path / "pool" / "balance_source.wav").write_bytes(b"live")
        arch = tmp_path / "archive" / "pool-20260101-000000"
        arch.mkdir(parents=True)
        (arch / "balance_source.wav").write_bytes(b"old")
        (tmp_path / "pool_new").mkdir()
        found = builder._find_prior_asset(tmp_path / "pool_new", "balance_source.wav")
        assert found.read_bytes() == b"live"

    def test_falls_back_to_the_newest_archive_by_mtime_not_name(self, builder, tmp_path):
        """Name order is wrong, and the hand-named archive here proves it.

        Most archives are stamped ``<pool>-<UTC timestamp>``, but
        ``pool-v1-misattributed`` is hand-named, and ``-`` sorts below
        ``_`` - so a reverse name sort puts every ``pool_new-*`` ahead of
        every ``pool-*`` regardless of date. The newest here is deliberately
        the one that loses on name order.
        """
        import os
        older = tmp_path / "archive" / "pool_new-20260201-000000"
        newer = tmp_path / "archive" / "pool-v1-misattributed"
        for d, body in ((older, b"older"), (newer, b"newer")):
            d.mkdir(parents=True)
            (d / "channel_check.wav").write_bytes(body)
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_800_000_000, 1_800_000_000))
        assert sorted([older.name, newer.name], reverse=True)[0] == older.name, (
            "the fixture must actually disagree with name order, or it tests nothing")
        (tmp_path / "pool_new").mkdir()
        found = builder._find_prior_asset(tmp_path / "pool_new", "channel_check.wav")
        assert found.read_bytes() == b"newer"

    def test_reports_absence_rather_than_inventing_a_file(self, builder, tmp_path):
        (tmp_path / "pool_new").mkdir()
        assert builder._find_prior_asset(tmp_path / "pool_new", "channel_check.wav") is None

    def test_never_returns_the_pool_being_built(self, builder, tmp_path):
        """Copying a file onto itself would truncate it."""
        out = tmp_path / "pool"
        out.mkdir()
        (out / "channel_check.wav").write_bytes(b"RIFF")
        assert builder._find_prior_asset(out, "channel_check.wav") is None
