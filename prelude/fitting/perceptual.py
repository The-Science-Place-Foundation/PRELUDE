# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Perceptual distance between two simulator settings.

Fitting needs a way to ask "how differently do these two configurations sound?"
without a listener in the loop, so that the small number of judgements available
is spent on the comparisons that matter.

Distance is computed on **channel envelopes**, not waveforms. Envelopes are what
an implant transmits, and two signals with matching envelopes sound nearly
identical through one regardless of how different their samples look. A waveform
distance would mostly measure carrier noise seeds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..ci_sim import SimulatorConfig, design_filterbank, extract_envelope, simulate

#: Bands used for the comparison analysis. Independent of the configurations
#: being compared, so that two settings with different channel counts remain
#: comparable.
ANALYSIS_BANDS = 16
ANALYSIS_LOW_HZ = 300.0
ANALYSIS_HIGH_HZ = 7500.0

#: Envelope cutoffs at which the comparison is made, in Hz.
#:
#: **Multi-scale, and that is not decoration.** A single low cutoff smooths away
#: every difference that lives above it, so the measure silently reports
#: "identical" for parameters it simply cannot resolve. Compared at 50 Hz alone,
#: two simulations whose envelope bandwidths were 300 and 900 Hz scored 0.010
#: apart - and were discarded as indistinguishable when nothing had established
#: that a listener could not hear the difference.
#:
#: The slow scale captures the modulation an implant transmits; the faster ones
#: capture the temporal detail that separates one configuration from another.
#: The highest must exceed any envelope bandwidth being compared.
ANALYSIS_CUTOFFS_HZ = (50.0, 200.0, 800.0)

#: Retained for callers that want the slow scale alone.
ANALYSIS_ENVELOPE_CUTOFF_HZ = 50.0


@dataclass
class CandidatePool:
    """Pre-rendered simulator outputs and their pairwise distances.

    Rendering audio is far too slow to do inside a fitting loop, so a fixed pool
    of candidate configurations is rendered once and the full distance matrix
    computed up front. Fitting then reduces to table lookup, which keeps the
    interactive loop responsive during a session.
    """

    configs: list[SimulatorConfig]
    distances: np.ndarray  # (n, n), symmetric, zero diagonal
    stimulus_ids: list[str]

    def __len__(self) -> int:
        return len(self.configs)

    def distance(self, i: int, j: int) -> float:
        return float(self.distances[i, j])

    def most_distinct_pairs(self, k: int = 10) -> list[tuple[int, int, float]]:
        """The ``k`` most audibly different pairs, for a first coarse session."""
        n = len(self.configs)
        pairs = [
            (i, j, float(self.distances[i, j]))
            for i in range(n)
            for j in range(i + 1, n)
        ]
        pairs.sort(key=lambda p: -p[2])
        return pairs[:k]


def envelope_distance(
    a: np.ndarray,
    b: np.ndarray,
    sample_rate: int,
    cutoffs: tuple[float, ...] = ANALYSIS_CUTOFFS_HZ,
) -> float:
    """Perceptual distance in [0, 2]; 0 identical, 1 uncorrelated.

    One minus the mean per-band envelope correlation, averaged over several
    envelope cutoffs. Bands whose envelope is flat in either signal are skipped,
    since correlation is undefined there.

    The multi-scale average matters: measured at one low cutoff, this returns
    near-zero for any difference living above that cutoff, and a caller cannot
    tell "these are the same" from "I cannot see this". Two settings differing
    only in envelope bandwidth, or in stimulation rate, were reported as
    identical for exactly that reason.
    """
    n = min(len(a), len(b))
    if n == 0:
        return 1.0
    fb = design_filterbank(
        sample_rate, ANALYSIS_BANDS, ANALYSIS_LOW_HZ,
        min(ANALYSIS_HIGH_HZ, sample_rate / 2 * 0.9),
    )
    ba, bb = fb.apply(a[:n]), fb.apply(b[:n])

    scales = []
    for cut in cutoffs:
        if cut >= sample_rate / 2:
            continue
        ea = extract_envelope(ba, sample_rate, cutoff_hz=cut)
        eb = extract_envelope(bb, sample_rate, cutoff_hz=cut)
        cors = [
            np.corrcoef(x, y)[0, 1]
            for x, y in zip(ea, eb, strict=True)
            if x.std() > 1e-9 and y.std() > 1e-9
        ]
        if cors:
            scales.append(1.0 - float(np.mean(cors)))
    return float(np.mean(scales)) if scales else 1.0


def build_candidate_pool(
    configs: list[SimulatorConfig],
    stimuli: dict[str, np.ndarray],
    sample_rate: int,
    progress: bool = False,
) -> CandidatePool:
    """Render every configuration on every stimulus and tabulate distances.

    Parameters
    ----------
    stimuli:
        Named source signals. Distances are averaged across them, so a
        configuration that differs on speech but not on music lands at a moderate
        distance rather than being judged on whichever happened to be used.
        **Use at least two contrasting stimuli** - fitting to one clip produces a
        simulator that is right about that clip.

    Notes
    -----
    Cost is ``len(configs) * len(stimuli)`` renders plus ``n^2/2`` distance
    computations. A 40-configuration pool on two short stimuli takes a couple of
    minutes; this runs once, offline, before a session.
    """
    if len(configs) < 2:
        raise ValueError("a pool needs at least two configurations")
    if not stimuli:
        raise ValueError("at least one stimulus is required")
    if len(stimuli) == 1:
        import warnings

        warnings.warn(
            "fitting against a single stimulus will produce a simulator tuned to "
            "that clip; supply at least two contrasting stimuli",
            stacklevel=2,
        )

    rendered: dict[str, list[np.ndarray]] = {}
    for name, x in stimuli.items():
        outputs = []
        for k, cfg in enumerate(configs):
            if progress:
                print(f"  rendering {name}: {k + 1}/{len(configs)}", end="\r")
            outputs.append(simulate(x, sample_rate, cfg).audio)
        rendered[name] = outputs

    n = len(configs)
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = np.mean([
                envelope_distance(rendered[s][i], rendered[s][j], sample_rate)
                for s in stimuli
            ])
            dist[i, j] = dist[j, i] = d

    return CandidatePool(
        configs=list(configs), distances=dist, stimulus_ids=list(stimuli)
    )
