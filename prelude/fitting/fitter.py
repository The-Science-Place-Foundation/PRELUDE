# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Adaptive fitting of simulator settings from forced-choice judgements.

The problem: find which simulator configuration best matches a particular
listener's percept, using as few judgements as possible. Listening time is the
binding constraint - it is slow, tiring, and where hearing is progressive its
supply shrinks - so every trial must be chosen to be worth asking.

The model. The listener's percept is produced by some unknown true configuration
*t*. Presented with two candidates, they prefer whichever sounds closer to it:

    P(choose A over B | t) = logistic( beta * [ D(B, t) - D(A, t) ] )

where ``D`` is the perceptual distance from :mod:`prelude.fitting.perceptual` and
``beta`` is the listener's discrimination sharpness - high beta means reliable
judgements, low beta means near-guessing. The key point is that ``D`` is
computable for any hypothesised *t*, so the likelihood of an observed choice can
be evaluated without ever knowing the truth.

Inference is a discrete Bayesian posterior over the candidate pool, updated
after each judgement. No gradients, no distributional assumptions, and an honest
uncertainty estimate at every point - including the ability to report that the
data so far does not identify anything, which is a real and common outcome.

Trials are chosen by expected information gain, so the next comparison is the one
that most reduces uncertainty rather than one sampled at random. In simulation
this reaches a given confidence in roughly a third of the trials that random
pairing needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..ci_sim import SimulatorConfig
from .perceptual import CandidatePool

#: Default discrimination sharpness. Calibrate per listener from catch trials -
#: see :meth:`SimulatorFitter.set_beta_from_catch_rate`.
DEFAULT_BETA = 6.0

#: Posterior mass on one candidate above which fitting is considered converged.
CONVERGENCE_THRESHOLD = 0.80


@dataclass
class Judgement:
    """One recorded forced choice between two pool members."""

    chosen: int
    rejected: int
    confidence: int | None = None
    trial_id: str = ""


@dataclass
class SimulatorFitter:
    """Sequential Bayesian fit over a pre-rendered candidate pool.

    Example
    -------
    >>> fitter = SimulatorFitter(pool)
    >>> i, j = fitter.propose_comparison()
    >>> fitter.observe(Judgement(chosen=i, rejected=j))
    >>> fitter.summary().converged
    """

    pool: CandidatePool
    beta: float = DEFAULT_BETA
    log_posterior: np.ndarray = field(default=None, repr=False)
    judgements: list[Judgement] = field(default_factory=list)
    _asked: set[tuple[int, int]] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if self.log_posterior is None:
            # Uniform prior: no candidate is favoured before any data.
            self.log_posterior = np.full(len(self.pool), -math.log(len(self.pool)))

    @property
    def posterior(self) -> np.ndarray:
        p = np.exp(self.log_posterior - self.log_posterior.max())
        return p / p.sum()

    def set_beta_from_catch_rate(self, catch_bias: float, n_catch: int) -> None:
        """Calibrate discrimination sharpness from catch-trial performance.

        Catch trials present identical stimuli, so responses should be at chance.
        A listener who answers them near 50/50 is discriminating rather than
        guessing on the real trials, which supports a higher ``beta``. A strong
        position bias means their choices carry less information and ``beta``
        should fall, so that the fit does not over-trust them.

        Fitting with an uncalibrated ``beta`` is the main way this procedure can
        produce confident nonsense: too high, and noise is read as signal.
        """
        if n_catch < 4:
            return  # too few to estimate anything
        bias = abs(catch_bias - 0.5) * 2.0  # 0 = at chance, 1 = fully biased
        self.beta = DEFAULT_BETA * max(0.15, 1.0 - bias)

    def _choice_loglik(self, chosen: int, rejected: int) -> np.ndarray:
        """Log P(chosen preferred over rejected | each candidate is the truth)."""
        d_chosen = self.pool.distances[chosen]
        d_rejected = self.pool.distances[rejected]
        margin = self.beta * (d_rejected - d_chosen)
        # log(sigmoid(m)), numerically stable
        return -np.logaddexp(0.0, -margin)

    def observe(self, judgement: Judgement) -> None:
        """Fold one judgement into the posterior."""
        n = len(self.pool)
        for idx in (judgement.chosen, judgement.rejected):
            if not 0 <= idx < n:
                raise ValueError(f"candidate index {idx} outside pool of {n}")
        if judgement.chosen == judgement.rejected:
            raise ValueError("chosen and rejected candidates are the same")

        ll = self._choice_loglik(judgement.chosen, judgement.rejected)
        if judgement.confidence is not None:
            # Weight by stated confidence: a hesitant answer should move the
            # posterior less than a decisive one.
            ll = ll * (0.4 + 0.15 * judgement.confidence)

        self.log_posterior = self.log_posterior + ll
        self.log_posterior -= self.log_posterior.max()
        self.judgements.append(judgement)
        self._asked.add(tuple(sorted((judgement.chosen, judgement.rejected))))

    def propose_comparison(self, n_sample: int = 60) -> tuple[int, int]:
        """Choose the next pair, by expected information gain.

        Candidates are sampled from the current posterior so that comparisons
        concentrate on the region still in contention, then scored by how much
        each pair is expected to reduce posterior entropy. Pairs already asked
        are skipped - re-asking gathers nothing and looks careless to the
        participant.
        """
        n = len(self.pool)
        if n < 2:
            raise ValueError("pool must contain at least two candidates")

        post = self.posterior
        live = np.flatnonzero(post > post.max() * 1e-4)
        if len(live) < 2:
            live = np.argsort(-post)[: min(8, n)]

        rng = np.random.default_rng(len(self.judgements))
        pool_idx = live if len(live) <= 12 else rng.choice(
            live, size=12, replace=False, p=post[live] / post[live].sum()
        )

        best, best_gain = None, -np.inf
        for a_i, a in enumerate(pool_idx):
            for b in pool_idx[a_i + 1 :]:
                key = tuple(sorted((int(a), int(b))))
                if key in self._asked:
                    continue
                gain = self._expected_information_gain(int(a), int(b), post)
                if gain > best_gain:
                    best, best_gain = (int(a), int(b)), gain

        if best is None:  # everything among the live set has been asked
            order = np.argsort(-post)
            return int(order[0]), int(order[1])
        return best

    def _expected_information_gain(self, a: int, b: int, post: np.ndarray) -> float:
        """Expected reduction in posterior entropy from asking about (a, b)."""
        ll_a = self._choice_loglik(a, b)
        ll_b = self._choice_loglik(b, a)

        p_a = float(np.sum(post * np.exp(ll_a)))
        p_b = float(np.sum(post * np.exp(ll_b)))
        total = p_a + p_b
        if total <= 0:
            return -np.inf
        p_a, p_b = p_a / total, p_b / total

        def posterior_entropy(ll: np.ndarray) -> float:
            q = post * np.exp(ll)
            s = q.sum()
            if s <= 0:
                return 0.0
            q = q / s
            nz = q[q > 0]
            return float(-(nz * np.log(nz)).sum())

        prior = post[post > 0]
        h_prior = float(-(prior * np.log(prior)).sum())
        h_expected = p_a * posterior_entropy(ll_a) + p_b * posterior_entropy(ll_b)
        return h_prior - h_expected

    def summary(self) -> FitSummary:
        post = self.posterior
        order = np.argsort(-post)
        top = int(order[0])
        nz = post[post > 0]
        entropy = float(-(nz * np.log(nz)).sum())
        max_entropy = math.log(len(self.pool))
        return FitSummary(
            best_index=top,
            best_config=self.pool.configs[top],
            best_probability=float(post[top]),
            runners_up=[(int(i), float(post[i])) for i in order[1:4]],
            entropy=entropy,
            relative_entropy=entropy / max_entropy if max_entropy > 0 else 0.0,
            n_judgements=len(self.judgements),
            beta=self.beta,
        )


@dataclass(frozen=True)
class FitSummary:
    """Current state of the fit, with the caveats needed to read it."""

    best_index: int
    best_config: SimulatorConfig
    best_probability: float
    runners_up: list[tuple[int, float]]
    entropy: float
    relative_entropy: float
    n_judgements: int
    beta: float

    @property
    def converged(self) -> bool:
        return self.best_probability >= CONVERGENCE_THRESHOLD

    def report(self) -> str:
        lines = [
            f"After {self.n_judgements} judgements (beta {self.beta:.1f}):",
            f"  best candidate #{self.best_index} at "
            f"{self.best_probability:.0%} posterior probability",
            f"  remaining uncertainty {self.relative_entropy:.0%} of maximum",
        ]
        if self.runners_up:
            near = ", ".join(f"#{i} ({p:.0%})" for i, p in self.runners_up if p > 0.02)
            if near:
                lines.append(f"  still in contention: {near}")
        if not self.converged:
            lines.append(
                "  NOT converged - this is a current best guess, not a fitted "
                "result. Do not treat it as the listener's settings yet."
            )
        if self.n_judgements < 15:
            lines.append(
                "  Fewer than 15 judgements; a leading candidate this early is "
                "usually an artefact of which pairs happened to be asked."
            )
        return "\n".join(lines)
