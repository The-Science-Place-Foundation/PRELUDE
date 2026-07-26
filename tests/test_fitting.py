# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Tests for adaptive fitting.

The central test is *recovery*: given a simulated listener with known settings,
does the fitter find them? And judged by perceptual distance rather than index
equality, because two configurations that sound the same are equally correct
answers and demanding an exact index would fail a working fitter.
"""

from __future__ import annotations

import numpy as np
import pytest

from prelude.fitting import (
    CandidatePool,
    Judgement,
    SimulatorFitter,
    envelope_distance,
)


def synthetic_pool(n: int = 40, seed: int = 0) -> tuple[CandidatePool, np.ndarray]:
    """Candidates in a 2-D latent space; distance is Euclidean and normalised."""
    rng = np.random.default_rng(seed)
    pts = rng.uniform(0, 1, size=(n, 2))
    d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
    d /= d.max()
    return CandidatePool(configs=[None] * n, distances=d, stimulus_ids=["synthetic"]), d


def simulated_listener(d: np.ndarray, truth: int, beta: float, rng):
    def choose(a: int, b: int) -> int:
        margin = beta * (d[b, truth] - d[a, truth])
        return a if rng.random() < 1 / (1 + np.exp(-margin)) else b

    return choose


class TestRecovery:
    def test_finds_a_perceptually_equivalent_candidate(self):
        pool, d = synthetic_pool()
        truth, beta = 7, 8.0
        rng = np.random.default_rng(1)
        choose = simulated_listener(d, truth, beta, rng)
        fitter = SimulatorFitter(pool, beta=beta)

        for _ in range(40):
            i, j = fitter.propose_comparison()
            c = choose(i, j)
            fitter.observe(Judgement(chosen=c, rejected=j if c == i else i))

        s = fitter.summary()
        error = d[s.best_index, truth]
        median = float(np.median(d[np.triu_indices(len(pool), 1)]))
        assert error < 0.25 * median, (
            f"converged {error:.3f} from the truth, against a median pairwise "
            f"distance of {median:.3f}"
        )

    def test_a_sharp_listener_recovers_exactly(self):
        pool, d = synthetic_pool()
        truth, beta = 7, 12.0
        rng = np.random.default_rng(2)
        choose = simulated_listener(d, truth, beta, rng)
        fitter = SimulatorFitter(pool, beta=beta)
        for _ in range(50):
            i, j = fitter.propose_comparison()
            c = choose(i, j)
            fitter.observe(Judgement(chosen=c, rejected=j if c == i else i))
        assert fitter.summary().best_index == truth

    def test_adaptive_beats_random_pairing(self):
        """The whole point: fewer trials for the same confidence."""
        pool, d = synthetic_pool()
        truth, beta, n_trials = 7, 8.0, 30

        rng = np.random.default_rng(3)
        choose = simulated_listener(d, truth, beta, rng)
        adaptive = SimulatorFitter(pool, beta=beta)
        for _ in range(n_trials):
            i, j = adaptive.propose_comparison()
            c = choose(i, j)
            adaptive.observe(Judgement(chosen=c, rejected=j if c == i else i))

        rng = np.random.default_rng(3)
        choose = simulated_listener(d, truth, beta, rng)
        random_fit = SimulatorFitter(pool, beta=beta)
        for _ in range(n_trials):
            i, j = (int(x) for x in rng.choice(len(pool), 2, replace=False))
            c = choose(i, j)
            random_fit.observe(Judgement(chosen=c, rejected=j if c == i else i))

        assert adaptive.summary().best_probability > random_fit.summary().best_probability


class TestHonestUncertainty:
    def test_starts_uninformative(self):
        pool, _ = synthetic_pool()
        s = SimulatorFitter(pool).summary()
        assert s.best_probability == pytest.approx(1 / len(pool), rel=0.2)
        assert s.relative_entropy > 0.99
        assert not s.converged

    def test_a_guessing_listener_does_not_produce_confidence(self):
        """Random answers must not yield a confident fit.

        This is the failure mode that matters. A fitter that converges on noise
        would hand back settings that look authoritative and are meaningless.
        """
        pool, _ = synthetic_pool()
        rng = np.random.default_rng(4)
        fitter = SimulatorFitter(pool, beta=6.0)
        for _ in range(40):
            i, j = fitter.propose_comparison()
            c = i if rng.random() < 0.5 else j
            fitter.observe(Judgement(chosen=c, rejected=j if c == i else i))
        assert fitter.summary().best_probability < 0.8

    def test_report_flags_early_and_unconverged_results(self):
        pool, _ = synthetic_pool()
        fitter = SimulatorFitter(pool)
        fitter.observe(Judgement(chosen=1, rejected=2))
        text = fitter.summary().report()
        assert "NOT converged" in text
        assert "Fewer than 15 judgements" in text


class TestBetaCalibration:
    def test_position_bias_lowers_beta(self):
        pool, _ = synthetic_pool()
        fitter = SimulatorFitter(pool)
        before = fitter.beta
        fitter.set_beta_from_catch_rate(catch_bias=1.0, n_catch=10)
        assert fitter.beta < before

    def test_chance_catch_performance_keeps_beta_high(self):
        pool, _ = synthetic_pool()
        fitter = SimulatorFitter(pool)
        fitter.set_beta_from_catch_rate(catch_bias=0.5, n_catch=10)
        assert fitter.beta == pytest.approx(6.0, rel=0.05)

    def test_too_few_catch_trials_leaves_beta_alone(self):
        pool, _ = synthetic_pool()
        fitter = SimulatorFitter(pool)
        before = fitter.beta
        fitter.set_beta_from_catch_rate(catch_bias=1.0, n_catch=2)
        assert fitter.beta == before


class TestTrialSelection:
    def test_does_not_repeat_a_pair_while_alternatives_remain(self):
        """Re-asking a pair gathers nothing and looks careless to the participant.

        Repeats become legitimate only once the posterior has narrowed so far
        that every pair among the surviving candidates has been asked, so this
        checks the early phase where alternatives clearly remain.
        """
        pool, d = synthetic_pool(n=30)
        rng = np.random.default_rng(5)
        choose = simulated_listener(d, 3, 8.0, rng)
        fitter = SimulatorFitter(pool, beta=8.0)

        seen: set[tuple[int, int]] = set()
        for _ in range(15):
            i, j = fitter.propose_comparison()
            key = tuple(sorted((i, j)))
            assert key not in seen, f"pair {key} proposed twice"
            seen.add(key)
            c = choose(i, j)
            fitter.observe(Judgement(chosen=c, rejected=j if c == i else i))

    def test_rejects_invalid_judgements(self):
        pool, _ = synthetic_pool(n=8)
        fitter = SimulatorFitter(pool)
        with pytest.raises(ValueError, match="outside pool"):
            fitter.observe(Judgement(chosen=99, rejected=1))
        with pytest.raises(ValueError, match="the same"):
            fitter.observe(Judgement(chosen=2, rejected=2))


class TestPerceptualDistance:
    def test_identical_signals_are_zero_distance(self):
        sr = 20000
        x = np.sin(2 * np.pi * 440 * np.arange(sr) / sr) * 0.2
        assert envelope_distance(x, x, sr) < 1e-6

    def test_different_signals_are_further_apart(self):
        sr = 20000
        t = np.arange(sr) / sr
        a = 0.2 * np.sin(2 * np.pi * 300 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
        b = 0.2 * np.sin(2 * np.pi * 3000 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 11 * t))
        assert envelope_distance(a, b, sr) > envelope_distance(a, a, sr)
