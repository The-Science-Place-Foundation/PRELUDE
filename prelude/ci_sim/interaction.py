# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Channel interaction - electrical current spread in the cochlea.

Current injected at one electrode does not stay there. It spreads through the
conductive perilymph and excites neural populations belonging to neighbouring
electrodes, decaying roughly exponentially with distance:

    I(d) = I0 * exp(-d / lambda)

Typical falloff corresponds to 3-8 dB/mm. The practical result is that the number
of *functionally independent* channels saturates around 4-8 regardless of how
many electrodes the array carries - which is why a 22-electrode implant does not
give 22 channels of resolution.

For a pre-processor this stage is important in a specific way: it smears spectral
detail, so sharpening spectral contrast *before* transmission can partially
pre-compensate for the smearing that follows. That makes contrast enhancement one
of the better-motivated levers available.
"""

from __future__ import annotations

import numpy as np


def spread_matrix(
    n_channels: int,
    decay_db_per_channel: float = 8.0,
    normalise: bool = True,
) -> np.ndarray:
    """Build an ``(n_channels, n_channels)`` current-spread matrix.

    Element ``[i, j]`` is the fraction of channel ``j``'s stimulation that
    reaches the neural population of channel ``i``.

    Parameters
    ----------
    n_channels:
        Number of channels.
    decay_db_per_channel:
        Attenuation per channel of separation. Larger values mean tighter, more
        focused stimulation. 8 dB/channel is a reasonable generic figure for
        monopolar stimulation; current-focused modes are tighter. Pass a very
        large value to effectively disable interaction.
    normalise:
        Scale each column to sum to 1, conserving total stimulation energy so
        that adding interaction does not also change overall loudness.

    Notes
    -----
    Distance is expressed in channel indices rather than millimetres. This is
    exact only for uniformly spaced electrodes; with a known array geometry,
    build the matrix from physical positions instead.
    """
    if n_channels < 1:
        raise ValueError(f"n_channels must be >= 1, got {n_channels}")
    if decay_db_per_channel <= 0:
        raise ValueError(
            f"decay_db_per_channel must be positive, got {decay_db_per_channel}"
        )

    idx = np.arange(n_channels)
    distance = np.abs(idx[:, None] - idx[None, :])
    matrix = 10.0 ** (-decay_db_per_channel * distance / 20.0)

    if normalise:
        matrix = matrix / matrix.sum(axis=0, keepdims=True)
    return matrix


def apply_interaction(levels: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Apply current spread to per-channel stimulation levels.

    Parameters
    ----------
    levels:
        Stimulation levels, shape ``(n_channels, n_samples)``.
    matrix:
        Spread matrix from :func:`spread_matrix`.

    Returns
    -------
    np.ndarray
        Smeared levels, same shape.
    """
    levels = np.atleast_2d(np.asarray(levels, dtype=float))
    matrix = np.asarray(matrix, dtype=float)

    if matrix.shape != (levels.shape[0], levels.shape[0]):
        raise ValueError(
            f"matrix shape {matrix.shape} does not match "
            f"{levels.shape[0]} channels"
        )
    return matrix @ levels


def effective_channels(matrix: np.ndarray) -> float:
    """Estimate the number of independent channels the spread matrix permits.

    Computed as the participation ratio of the matrix's singular values,
    ``(sum s)^2 / sum(s^2)``. A diagonal matrix returns ``n_channels``; heavy
    smearing returns considerably fewer. Useful as a sanity check that an
    interaction setting is producing a plausible degree of degradation.
    """
    s = np.linalg.svd(np.asarray(matrix, dtype=float), compute_uv=False)
    return float(s.sum() ** 2 / (s**2).sum())
