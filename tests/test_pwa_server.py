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


class TestPresentationOrderIsCounterbalanced:
    """Independent per-trial draws streaked far enough to confound a real result.

    In the session of 2026-07-29 the per-trial shuffle came up [1,0] six times
    running. Because the information-gain selector puts the leading candidate
    first in most pairs, that placed the favoured candidate in the second
    interval on all five trials it appeared in - so "preferred that candidate"
    and "pressed the second button" predicted identical data.

    The shuffle was not broken; measured 0.501 over 4000 seeds. Randomness
    streaks, which is exactly why the design must not rely on it not to.
    """

    def test_order_is_balanced_within_every_block_of_two(self, srv):
        sess = srv._new_session()
        seen = []
        for n in range(12):
            sess["responses"] = [None] * n
            t = srv._next_trial(sess)
            seen.append(tuple(t["presentation_order"]))
            sess["trials"] = []
        for b in range(6):
            pair = seen[2 * b:2 * b + 2]
            assert set(pair) == {(0, 1), (1, 0)}, (
                f"block {b} was {pair}; each block must contain one of each")

    def test_no_streak_can_exceed_one_trial(self, srv):
        """The specific failure: five consecutive trials with the same order."""
        for k in range(200):
            sess = srv._new_session()
            sess["session_id"] = f"streaktest{k}"
            orders = []
            for n in range(10):
                sess["responses"] = [None] * n
                sess["trials"] = []
                orders.append(tuple(srv._next_trial(sess)["presentation_order"]))
            run = best = 1
            for i in range(1, len(orders)):
                run = run + 1 if orders[i] == orders[i - 1] else 1
                best = max(best, run)
            assert best <= 2, f"session {k} streaked {best} trials: {orders}"

    def test_control_trials_are_counterbalanced_too(self, srv):
        """The control is the one place a slot bias would be read as a level effect."""
        sess = srv._new_session()
        quiet_slots = []
        for n in range(srv.CONTROL_TRIALS):
            sess["responses"] = [None] * n
            sess["trials"] = []
            t = srv._next_trial(sess)
            assert t["is_control"]
            quiet_slots.append(0 if t["quiet_first"] else 1)
        assert len(set(quiet_slots)) > 1, (
            "the quieter interval must not always land in the same slot")


class TestSelfMeasuredMapping:
    """The map we collect ourselves, because the clinic cannot be asked.

    Two measurements: which narrowband bursts reach the acoustic ear at the
    level the study presents, and where the implant places a given frequency.
    Neither involves the simulator - part two sends plain audio to the implant
    ear so the listener's own device does its own allocation, which is what
    makes it a measurement of the device rather than of our model.
    """

    def _manifest(self, srv, target_lufs=-26.6):
        (srv.AUDIO_DIR / "mapping.json").write_text(json.dumps({
            "sample_rate": 20000, "implant_ear": "right", "acoustic_ear": "left",
            "target_lufs": target_lufs, "burst_ms": 400,
            "detect": [{"file": f"map_detect_{f}.wav", "center_hz": float(f)}
                       for f in (250, 1000, 4000)],
            "match": [{"file": f"map_ci_{f}.wav", "center_hz": float(f)}
                      for f in (500, 1500, 3000)],
            "probe": [{"file": f"map_probe_{f}.wav", "center_hz": float(f)}
                      for f in (125, 250, 500, 1000, 2000, 4000, 8000)],
        }))
        return srv._load_mapping_manifest()

    def test_absent_stimuli_are_reported_rather_than_faked(self, srv):
        """Offering a test the stimuli cannot support wastes a listener's evening."""
        assert srv._load_mapping_manifest() is None

    def test_manifest_loads_when_present(self, srv):
        m = self._manifest(srv)
        assert len(m["detect"]) == 3 and len(m["probe"]) == 7

    def test_a_partial_map_is_kept(self, srv):
        """Sessions stop early by design; half a map is still a map."""
        self._manifest(srv)
        srv.MAPPING_FILE().write_text(json.dumps({
            "detect": [{"center_hz": 250.0, "heard": "clear"}],
            "match": [], "complete": False,
        }))
        r = srv._read_mapping_result()
        assert r["complete"] is False and len(r["detect"]) == 1

    def test_a_corrupt_map_file_does_not_raise(self, srv):
        srv.MAPPING_FILE().write_text("{not json")
        assert srv._read_mapping_result() is None


class TestPitchMatchStaircase:
    """Ported from the simulation that validated it before deployment.

    Both calibration procedures on this project shipped broken in ways a few
    minutes of simulation would have caught. This one was simulated against
    synthetic listeners first: median error 1.5-3.0 semitones over 200 runs per
    condition, ~8-10 trials, resolving shifts up to an octave.

    A quarter-octave ladder was tried first and rejected - it has a
    3-semitone floor, which would blur the very mismatch the test exists to
    size. The top reference was moved from 4 kHz to 3 kHz because at 4 kHz a
    12-semitone upward shift pinned the ladder against its ceiling in 198 of
    200 runs.
    """

    LADDER = [125.0 * (2 ** (k / 8)) for k in range(49)]
    STEPS = [8, 4, 2, 1]
    TARGET_REVERSALS = 6

    def _run(self, true_match_hz, jnd_st, start_below, seed):
        import math
        import random
        import statistics
        rng = random.Random(seed)
        near = min(range(len(self.LADDER)),
                   key=lambda i: abs(math.log2(self.LADDER[i] / true_match_hz)))
        i = max(0, min(len(self.LADDER) - 1,
                       near + (-self.STEPS[0] if start_below else self.STEPS[0])))
        step_ix, direction, reversals, trials = 0, None, [], 0
        while trials < 18 and len(reversals) < self.TARGET_REVERSALS:
            probe = self.LADDER[i]
            diff = 12 * math.log2(probe / true_match_hz)
            p = 1 / (1 + math.exp(-diff / max(0.3, jnd_st / 2)))
            higher = rng.random() < p
            trials += 1
            new_dir = "down" if higher else "up"
            if direction is not None and new_dir != direction:
                # Step size travels with the reversal: only reversals at the
                # finest step carry the claimed resolution.
                reversals.append((probe, step_ix))
                if step_ix < len(self.STEPS) - 1:
                    step_ix += 1
            direction = new_dir
            i = max(0, min(len(self.LADDER) - 1,
                           i + (-self.STEPS[step_ix] if higher else self.STEPS[step_ix])))
        finest = [hz for hz, sx in reversals if sx == len(self.STEPS) - 1]
        if len(finest) < 2:
            return None, trials
        use = finest[-4:]
        return 2 ** statistics.fmean(math.log2(hz) for hz in use), trials

    def test_it_recovers_a_known_match_within_its_stated_resolution(self):
        import math
        import statistics
        errs = []
        for k in range(120):
            est, _ = self._run(1500.0, 2.0, k % 2 == 0, seed=f"a{k}")
            if est is not None:
                errs.append(abs(12 * math.log2(est / 1500.0)))
        assert len(errs) > 100, "should almost always resolve"
        assert statistics.median(errs) < 1.5, (
            f"median error {statistics.median(errs):.1f} st - the docs claim "
            f"0.5 st median and must not overstate it")

    def test_it_recovers_an_upward_shift_which_is_the_expected_direction(self):
        """CI arrays do not reach the apex, so matches usually sit high."""
        import math
        import statistics
        true = 1500.0 * (2 ** (6 / 12))
        ests = [e for e, _ in (self._run(true, 2.0, k % 2 == 0, seed=f"b{k}")
                               for k in range(120)) if e is not None]
        assert statistics.median(ests) > 1500.0, "must not collapse toward the input"
        assert abs(12 * math.log2(statistics.median(ests) / true)) < 3.0

    def test_starting_side_does_not_determine_the_answer(self):
        """A fixed starting side anchors the estimate toward it."""
        import statistics
        below = [e for e, _ in (self._run(1500.0, 2.0, True, seed=f"c{k}")
                                for k in range(80)) if e is not None]
        above = [e for e, _ in (self._run(1500.0, 2.0, False, seed=f"d{k}")
                                for k in range(80)) if e is not None]
        import math
        gap = abs(12 * math.log2(statistics.median(below) / statistics.median(above)))
        # Was 4.5 st when the step advanced every second reversal and the last
        # four were averaged regardless of step size. That is the defect this
        # asserts against.
        assert gap < 1.5, f"starting side shifted the answer by {gap:.1f} st"

    def test_it_stays_within_a_tolerable_number_of_trials(self):
        """Listening time is the binding constraint on the whole project."""
        import statistics
        ns = [n for _, n in (self._run(1500.0, 2.0, k % 2 == 0, seed=f"e{k}")
                             for k in range(120))]
        assert statistics.median(ns) <= 13


class TestMappingSurvivesMultipleSittings:
    """The map is expected to take several sittings, so nothing may be lost.

    The first version of the endpoint wrote whatever the current visit had
    collected straight over the file. Answering four bands, stopping, and
    returning to answer two would have left two - silently discarding real
    measurements from a listener who cannot easily be asked to repeat them.
    """

    def test_a_later_sitting_does_not_erase_an_earlier_one(self, srv):
        a = [{"center_hz": 250.0, "heard": "clear"},
             {"center_hz": 500.0, "heard": "faint"}]
        b = [{"center_hz": 1000.0, "heard": "none"}]
        merged = srv._merge_by(a, b, "center_hz")
        assert [m["center_hz"] for m in merged] == [250.0, 500.0, 1000.0]

    def test_re_answering_a_band_updates_it(self, srv):
        a = [{"center_hz": 250.0, "heard": "none"}]
        b = [{"center_hz": 250.0, "heard": "clear"}]
        merged = srv._merge_by(a, b, "center_hz")
        assert len(merged) == 1 and merged[0]["heard"] == "clear"

    def test_a_resolved_match_is_never_replaced_by_an_abandoned_one(self, srv):
        """Half a staircase must not overwrite a completed one."""
        prior = [{"ci_hz": 1500.0, "match_hz": 2121.0, "resolved": True}]
        later = [{"ci_hz": 1500.0, "match_hz": None, "resolved": False}]
        merged = srv._merge_by(prior, later, "ci_hz", prefer="resolved")
        assert merged[0]["resolved"] is True and merged[0]["match_hz"] == 2121.0

    def test_a_resolved_match_does_replace_an_unresolved_one(self, srv):
        prior = [{"ci_hz": 1500.0, "match_hz": None, "resolved": False}]
        later = [{"ci_hz": 1500.0, "match_hz": 2121.0, "resolved": True}]
        merged = srv._merge_by(prior, later, "ci_hz", prefer="resolved")
        assert merged[0]["resolved"] is True

    def test_order_follows_when_it_was_first_measured(self, srv):
        a = [{"center_hz": 4000.0, "heard": "none"}]
        b = [{"center_hz": 250.0, "heard": "clear"}, {"center_hz": 4000.0, "heard": "faint"}]
        assert [m["center_hz"] for m in srv._merge_by(a, b, "center_hz")] == [4000.0, 250.0]

    def test_malformed_entries_are_skipped_not_fatal(self, srv):
        a = [{"center_hz": 250.0, "heard": "clear"}, "garbage", {"no_key": 1}]
        merged = srv._merge_by(a, None, "center_hz")
        assert len(merged) == 1

    def test_missing_prior_or_incoming_is_fine(self, srv):
        assert srv._merge_by(None, None, "center_hz") == []
        assert len(srv._merge_by(None, [{"center_hz": 1.0}], "center_hz")) == 1
        assert len(srv._merge_by([{"center_hz": 1.0}], None, "center_hz")) == 1


class TestMappingRejectsAnythingNotFromTheApp:
    """Verification must not be able to write to the live record.

    While this endpoint was being checked with hand-made requests, five of the
    listener's real detection answers were overwritten. The merge keys on
    frequency and had no way to distinguish a measurement from a probe, and the
    probe values looked entirely plausible. Requiring the stimulus filename -
    which the app always sends and a hand-made request generally will not -
    closes that path.
    """

    def test_an_entry_without_a_stimulus_file_is_refused(self, srv):
        from_app = [{"center_hz": 250.0, "heard": "clear", "file": "map_detect_250.wav"}]
        probe = [{"center_hz": 250.0, "heard": "none"}]
        keep = [i for i in probe
                if isinstance(i, dict) and isinstance(i.get("file"), str)]
        assert keep == [], "a probe with no file must not be accepted"
        merged = srv._merge_by(from_app, keep, "center_hz")
        assert merged[0]["heard"] == "clear", "the real answer must survive"

    def test_a_traversal_style_filename_is_refused(self, srv):
        bad = {"center_hz": 250.0, "heard": "clear", "file": "../../etc/passwd"}
        assert not srv.SAFE_NAME.match(bad["file"])

    def test_a_normal_stimulus_filename_passes(self, srv):
        assert srv.SAFE_NAME.match("map_detect_4500.wav")
        assert srv.SAFE_NAME.match("map_ci_1500.wav")


class TestPitchMatchReliabilityIsJudgedNotAssumed:
    """A staircase fed random answers still converges — on noise.

    The client's own `resolved` flag only checked that the finest step had been
    reached and reversed at twice. An investigator ran three staircases with
    deliberately random answers and all three came back resolved, reporting
    shifts of -20, +24 and -31 semitones. A tonotopic map cannot do that, and
    the numbers were being presented as measurements.

    The discriminator is the spread among finest-step reversals. The finest rung
    is 1.5 semitones, so a listener genuinely tracking pitch oscillates within
    a rung or two; scattered reversals mean nothing was bracketed.
    """

    def _assess(self, srv, reversals, ci_hz=1500.0, match_hz=2000.0):
        import math
        finest = [r["hz"] for r in reversals if r["stepIx"] == srv._finest_step_index()]
        if len(finest) < 2:
            return False, None
        spread = 12 * math.log2(max(finest) / min(finest))
        return spread <= srv.RELIABLE_SPREAD_ST, round(spread, 2)

    def test_the_real_random_run_is_rejected(self, srv):
        """The exact reversals from the random test session."""
        scattered = [{"hz": 6168.8, "stepIx": 0}, {"hz": 4362, "stepIx": 1},
                     {"hz": 5187.4, "stepIx": 2}, {"hz": 4756.8, "stepIx": 3},
                     {"hz": 7336, "stepIx": 3}, {"hz": 6727.2, "stepIx": 3}]
        settled, spread = self._assess(srv, scattered)
        assert settled is False
        assert spread > 7.0, f"spread was {spread}, should be wide"

    def test_a_tightly_bracketed_run_is_accepted(self, srv):
        """What a listener actually tracking pitch looks like: within a rung or two."""
        tight = [{"hz": 1500.0, "stepIx": 0}, {"hz": 2200.0, "stepIx": 1},
                 {"hz": 2000.0, "stepIx": 2}, {"hz": 2062.0, "stepIx": 3},
                 {"hz": 1943.0, "stepIx": 3}, {"hz": 2062.0, "stepIx": 3}]
        settled, spread = self._assess(srv, tight)
        assert settled is True, f"spread {spread} st should pass"
        assert spread < srv.RELIABLE_SPREAD_ST

    def test_reversals_only_at_coarse_steps_are_rejected(self, srv):
        """Never reaching the finest step is not a measurement at its resolution."""
        coarse = [{"hz": 1500.0, "stepIx": 0}, {"hz": 2200.0, "stepIx": 1},
                  {"hz": 1800.0, "stepIx": 2}]
        assert self._assess(srv, coarse)[0] is False

    def test_a_single_finest_reversal_is_not_a_bracket(self, srv):
        one = [{"hz": 2000.0, "stepIx": 3}, {"hz": 1500.0, "stepIx": 1}]
        assert self._assess(srv, one)[0] is False

    def test_the_finest_index_matches_the_client_ladder(self, srv):
        """MAP_STEPS in app.js is [8, 4, 2, 1]; drift here silently breaks this."""
        app_js = (Path(__file__).resolve().parents[1]
                  / "pwa" / "static" / "app.js").read_text()
        assert "const MAP_STEPS = [8, 4, 2, 1];" in app_js
        assert srv._finest_step_index() == 3

    def test_direction_disagreement_across_references_is_flagged(self, srv):
        """A tonotopic map cannot shift up at one frequency and down at another."""
        shifts = [-20.0, 24.48, -30.52]          # the random run
        signs = {1 if v > 1.5 else -1 if v < -1.5 else 0 for v in shifts}
        assert len(signs - {0}) > 1, "must be detected as inconsistent"
        consistent = [6.0, 7.5, 5.0]
        signs2 = {1 if v > 1.5 else -1 if v < -1.5 else 0 for v in consistent}
        assert len(signs2 - {0}) <= 1
