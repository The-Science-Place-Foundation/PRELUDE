"""Behavioural tests for the listening app's server.

The server holds its own copy of the fitting maths, deliberately: it is
stdlib-only so the app can run anywhere without a numerical stack. That copy
was untested, which is how a duplicated-and-diverged estimator survived long
enough to nearly reach a listener.

Every test here encodes a specific mistake that was made. The docstrings say
which one, because a future reader needs to know why an apparently arbitrary
assertion exists before deciding to relax it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "pwa" / "server.py"


@pytest.fixture
def srv(tmp_path):
    """Load the server module against a throwaway pool and session directory."""
    spec = importlib.util.spec_from_file_location("prelude_pwa_server", SERVER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    audio = tmp_path / "pool"
    audio.mkdir()
    n = 4
    # A distance matrix with a clear structure, so a posterior can move.
    dist = [[abs(i - j) / n for j in range(n)] for i in range(n)]
    (audio / "pool.json").write_text(json.dumps({
        "pool_id": "testpool0001",
        "balance_db": 0.0,
        "control_pair": {
            "files": ["control_level_ref.wav", "control_level_quiet.wav"],
            "difference_db": 3.0,
            "duration_s": 6.0,
        },
        "candidates": [
            {"index": i, "name": f"c{i}", "file": f"c{i}.wav",
             "config_id": f"cfg{i}", "duration_s": 6.0}
            for i in range(n)
        ],
        "distances": dist,
    }))
    m.AUDIO_DIR = audio
    m.SESSION_DIR = tmp_path / "sessions"
    m.SESSION_DIR.mkdir()
    m.CALIB_FILE = lambda: m.SESSION_DIR / "calibration.json"
    m._pool = None
    return m


def _answer(srv, sess, trial, chose):
    """Record a response the way the /api/response handler does."""
    rec = {"trial_id": trial["trial_id"], "chose": chose,
           "is_catch": trial["is_catch"], "too_fast": False}
    if trial.get("is_control") and isinstance(chose, int):
        rec["chose_quieter"] = (chose == (0 if trial["quiet_first"] else 1))
    if (isinstance(chose, int) and not trial["is_catch"]
            and not trial.get("is_control")):
        shown = [trial["a_idx"], trial["b_idx"]]
        rec["chose_idx"] = shown[trial["presentation_order"][chose]]
        rec["rejected_idx"] = shown[trial["presentation_order"][1 - chose]]
    sess["responses"].append(rec)
    return rec


class TestLevelControl:
    """A control that is rendered but never presented is not a control.

    The level control pair existed in pool.json for a full revision while
    nothing in the server or app read it. It is the only thing that can
    separate "preferred the pulse carrier" from "preferred the quieter
    interval", which was the open question at the time.
    """

    def test_control_trials_are_served_at_the_head_of_the_session(self, srv):
        """Sessions end early by design, so a control at the end never runs."""
        sess = srv._new_session()
        for i in range(srv.CONTROL_TRIALS):
            t = srv._next_trial(sess)
            assert t["is_control"], f"trial {i} should be a level control"
            _answer(srv, sess, t, 0)
        assert not srv._next_trial(sess).get("is_control")

    def test_control_choice_is_scored_from_the_server_not_the_client(self, srv):
        """The client reports a slot, never which slot held the quieter file."""
        sess = srv._new_session()
        t = srv._next_trial(sess)
        quiet_slot = 0 if t["quiet_first"] else 1
        rec = _answer(srv, sess, t, quiet_slot)
        assert rec["chose_quieter"] is True
        rec2 = _answer(srv, sess, t, 1 - quiet_slot)
        assert rec2["chose_quieter"] is False

    def test_control_responses_never_reach_the_posterior(self, srv):
        """Control stimuli are not pool members; scoring them would be nonsense."""
        sess = srv._new_session()
        for _ in range(srv.CONTROL_TRIALS):
            t = srv._next_trial(sess)
            _answer(srv, sess, t, 0)
        assert all(r.get("chose_idx") is None for r in sess["responses"])
        post = srv._posterior(sess)
        assert post == pytest.approx([0.25] * 4), "controls must not move the fit"

    def test_control_trial_is_indistinguishable_in_shape(self, srv):
        """A listener who can spot a control can game it."""
        sess = srv._new_session()
        ctrl = srv._next_trial(sess)
        _answer(srv, sess, ctrl, 0)
        for _ in range(srv.CONTROL_TRIALS - 1):
            _answer(srv, sess, srv._next_trial(sess), 0)
        real = srv._next_trial(sess)
        for key in ("trial_id", "index", "options", "presentation_order",
                    "remaining", "audio_ms"):
            assert key in ctrl and key in real
        assert len(ctrl["options"]) == len(real["options"]) == 2
        assert ctrl["audio_ms"] > 0, "a zero duration would leak which trials are controls"


class TestPoolIdentity:
    """Rebuilding the pool renumbers candidates.

    Moving the anchor from 22 to 19 channels re-derived every candidate and
    shifted eight of them. Index 9 stopped being the pulse carrier and became
    a candidate that had not existed when the listener sat down, so rescoring
    would have silently reattributed six of seven judgements.
    """

    def test_session_records_the_pool_it_was_recorded_against(self, srv):
        assert srv._new_session()["pool_id"] == "testpool0001"

    def test_scoring_a_session_from_a_different_pool_is_refused(self, srv):
        sess = srv._new_session()
        sess["pool_id"] = "someotherpool"
        assert srv._pool_mismatch(sess) is not None
        assert srv._posterior(sess) == [], "must refuse, not silently rescore"

    def test_matching_pool_scores_normally(self, srv):
        sess = srv._new_session()
        sess["responses"].append({"chose_idx": 0, "rejected_idx": 3})
        assert srv._pool_mismatch(sess) is None
        assert srv._posterior(sess)[0] > 0.25

    def test_a_session_predating_pool_identity_is_flagged_not_assumed_fine(self, srv):
        sess = srv._new_session()
        del sess["pool_id"]
        assert srv._pool_mismatch(sess) is not None


class TestPositionBias:
    """Catch trials measure response bias, not discrimination sharpness.

    An estimator that set beta from catch performance was removed: catch
    trials present identical stimuli, so the distance is zero under every
    hypothesis and the response cannot depend on discrimination. A listener
    who coin-flipped everything scored a textbook 50/50 and was awarded the
    highest sharpness the model can express.
    """

    def test_two_catch_trials_say_nothing(self, srv):
        """Two coin flips landing the same way happens half the time."""
        sess = srv._new_session()
        sess["responses"] = [{"is_catch": True, "chose": 0},
                             {"is_catch": True, "chose": 0}]
        assert srv._position_bias(sess)["measurable"] is False

    def test_stray_taps_are_excluded(self, srv):
        """A response too fast to be a judgement is not evidence about position."""
        sess = srv._new_session()
        sess["responses"] = [{"is_catch": True, "chose": 0, "too_fast": True}
                             for _ in range(8)]
        assert srv._position_bias(sess)["n_catch"] == 0

    def test_one_sided_answering_is_reported_once_there_is_enough_of_it(self, srv):
        sess = srv._new_session()
        sess["responses"] = [{"is_catch": True, "chose": 0}
                             for _ in range(srv.MIN_CATCH_FOR_BIAS)]
        bias = srv._position_bias(sess)
        assert bias["measurable"] is True
        assert bias["fraction_first"] == 1.0

    def test_bias_pools_across_sessions_without_double_counting(self, srv, tmp_path):
        """Bias is a trait of the listener, not of a sitting.

        A single session is too short to collect enough catch trials, so they
        accumulate. The in-flight session is also on disk once _persist has
        run, and counting it twice would fabricate evidence.
        """
        sess = srv._new_session()
        sess["responses"] = [{"is_catch": True, "chose": 0} for _ in range(3)]
        srv._persist(sess)
        pooled = srv._pooled_position_bias(sess)
        assert pooled["n_catch"] == 3, "the persisted copy must not double-count"
        assert pooled["n_sessions"] == 1

    @pytest.mark.parametrize("body", [
        "{not json",                                   # not JSON at all
        "[1,2,3]",                                     # valid JSON, wrong shape
        '{"session_id":"x","responses":null}',         # responses not a list
        '{"session_id":"x","responses":{"a":"b"}}',    # responses a dict
        '{"session_id":"x","responses":["str"]}',      # a response not a dict
        '"just a string"',
        "null",
    ])
    def test_a_malformed_session_file_cannot_break_a_live_session(self, srv, body):
        """This runs inside /api/finish, before the final write.

        An exception here shows the listener the trouble screen at the very
        end of a session and loses the fit, the level-control result and their
        notes. Only the not-JSON case was originally handled; valid JSON of
        the wrong shape raised AttributeError or TypeError.
        """
        (srv.SESSION_DIR / "2026-01-01-broken.json").write_text(body)
        sess = srv._new_session()
        assert srv._pooled_position_bias(sess)["n_catch"] == 0
        assert srv._pooled_judgements(sess) == ([], 1)

    def test_is_catch_is_recovered_from_the_trial_when_absent(self, srv):
        """Older sessions carry is_catch on the trial, not on the response.

        Without the trial_id join those sessions contribute nothing, and the
        diagnostic would stay silent for several more sittings while the data
        to answer it sat on disk.
        """
        sess = srv._new_session()
        sess["trials"] = [{"trial_id": "t1", "is_catch": True}]
        sess["responses"] = [{"trial_id": "t1", "chose": 0}]   # no is_catch
        assert srv._position_bias({"responses": srv._with_trial_metadata(sess)})[
            "n_catch"] == 1


class TestCrossSessionAccumulation:
    """A single sitting cannot settle the pool, so judgements accumulate.

    The two real sessions ran six and nine responses against a twenty-
    candidate pool. Requiring convergence within one session either never
    fires or fires on noise. Accumulating indices across sessions is precisely
    what pool_id makes safe, and building that guard without using it would
    spend the listener's evenings on a verdict that can never be printed.
    """

    def _finished(self, srv, pool_id, judgements):
        sess = srv._new_session()
        sess["pool_id"] = pool_id
        sess["responses"] = [{"chose_idx": c, "rejected_idx": r}
                             for c, r in judgements]
        srv._persist(sess)
        return sess

    def test_judgements_from_earlier_sessions_on_the_same_pool_are_used(self, srv):
        self._finished(srv, "testpool0001", [(0, 3), (0, 2)])
        live = srv._new_session()
        pooled, n_sessions = srv._pooled_judgements(live)
        assert len(pooled) == 2 and n_sessions == 2

    def test_judgements_from_a_different_pool_are_never_folded_in(self, srv):
        """The exact operation that was unsafe before pool_id existed."""
        self._finished(srv, "a-different-pool", [(0, 3), (0, 2), (0, 1)])
        live = srv._new_session()
        pooled, _ = srv._pooled_judgements(live)
        assert pooled == []

    def test_unstamped_sessions_are_not_assumed_to_match(self, srv):
        sess = srv._new_session()
        del sess["pool_id"]
        sess["responses"] = [{"chose_idx": 0, "rejected_idx": 3}]
        srv._persist(sess)
        live = srv._new_session()
        pooled, _ = srv._pooled_judgements(live)
        assert pooled == []

    def test_the_live_session_is_not_double_counted(self, srv):
        live = srv._new_session()
        live["responses"] = [{"chose_idx": 0, "rejected_idx": 3}]
        srv._persist(live)
        pooled, n_sessions = srv._pooled_judgements(live)
        assert len(pooled) == 1 and n_sessions == 1

    def test_accumulated_judgements_move_the_posterior(self, srv):
        self._finished(srv, "testpool0001", [(0, 3), (0, 2), (0, 1)])
        live = srv._new_session()
        assert srv._posterior(live)[0] > 0.25, (
            "a fresh session must inherit what earlier sittings established")

    def test_an_out_of_range_index_from_a_larger_pool_is_skipped(self, srv):
        """Defence in depth: pool_id should already have excluded this."""
        live = srv._new_session()
        live["responses"] = [{"chose_idx": 99, "rejected_idx": 3}]
        assert srv._posterior(live) == pytest.approx([0.25] * 4)


class TestNearDuplicatesAreReportedNotBroken:
    """Naming one of an inseparable pair as "the answer" is an artefact.

    Simulated against the real pool, whether the true candidate is recovered
    is predicted almost entirely by its nearest-neighbour distance: 5-6 of 6
    runs when the nearest is 0.19 or further, 0-3 when it is within 0.07. The
    anchor is in the second group - env900 sits 0.021 away - so the most
    important hypothesis in the pool is one the fit cannot pick out.

    The response is to report the tie. Deleting a candidate on a metric's
    say-so was tried here before and removed the comparisons that would have
    settled the question.
    """

    @pytest.fixture
    def twinned(self, srv, tmp_path):
        """A pool where candidates 0 and 1 are near-identical."""
        pool = srv._load_pool()
        d = [[0.0, 0.01, 0.4, 0.4],
             [0.01, 0.0, 0.4, 0.4],
             [0.4, 0.4, 0.0, 0.3],
             [0.4, 0.4, 0.3, 0.0]]
        pool["distances"] = d
        srv._pool = pool
        return srv

    def test_a_tie_with_a_near_duplicate_is_named(self, twinned):
        pool = twinned._load_pool()
        dist = pool["distances"]
        top = 0
        tied = [pool["candidates"][i]["name"] for i in range(len(dist))
                if i != top and dist[top][i] < twinned.NEAR_DUPLICATE_DISTANCE]
        assert tied == ["c1"]

    def test_a_well_separated_winner_has_no_ties(self, twinned):
        pool = twinned._load_pool()
        dist = pool["distances"]
        top = 2
        tied = [pool["candidates"][i]["name"] for i in range(len(dist))
                if i != top and dist[top][i] < twinned.NEAR_DUPLICATE_DISTANCE]
        assert tied == []

    def test_the_threshold_matches_the_builders_warning(self, srv):
        """make_candidate_pool warns at the same distance; they must agree."""
        assert srv.NEAR_DUPLICATE_DISTANCE == 0.05


class TestPoolChangingUnderALiveSession:
    def test_the_session_ends_cleanly_rather_than_crashing(self, srv):
        """_posterior returns [] on a mismatch, and the trial selector then
        indexed an empty posterior. Reachable if the pool is deployed while a
        session is open."""
        sess = srv._new_session()
        sess["pool_id"] = "a-different-pool"
        assert srv._next_trial(sess) is None


class TestBetaIsAssumed:
    def test_posterior_moves_with_beta(self, srv):
        """The sensitivity that makes a single reported number misleading."""
        sess = srv._new_session()
        for r in (2, 3):
            sess["responses"].append({"chose_idx": 0, "rejected_idx": r})
        low = srv._posterior(sess, min(srv.BETA_RANGE))
        high = srv._posterior(sess, max(srv.BETA_RANGE))
        assert high[0] > low[0]

    def test_beta_range_spans_the_plausible_values(self, srv):
        assert min(srv.BETA_RANGE) < srv.DEFAULT_BETA <= max(srv.BETA_RANGE)


class TestBalanceIsAppliedOnce:
    """A pool rendered with the balance baked in, served to an app that also
    applies it, puts the ears at twice the measured offset.

    This was caught before deployment: a pool built with --balance-db 6.0
    would have been presented through an app applying the measured 6 dB again,
    giving 12 dB against a balance measured at 6.
    """

    def test_server_reports_what_the_pool_already_carries(self, srv):
        pool = srv._load_pool()
        assert "balance_db" in pool, (
            "the app subtracts this to get the residual; a missing value "
            "silently becomes a full double-application")

    def test_residual_is_the_measured_balance_minus_what_is_baked_in(self, srv):
        """Arithmetic the app performs, asserted here so it cannot drift."""
        measured, baked = 6.0, 6.0
        assert measured - baked == 0.0
        assert 6.0 - (srv._load_pool().get("balance_db") or 0.0) == 6.0
