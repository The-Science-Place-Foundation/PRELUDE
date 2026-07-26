# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Channel selection - the n-of-m stage.

Peak-picking strategies such as ACE transmit only the ``n`` highest-energy of
``m`` analysis bands in each frame. Everything else is dropped.

This has a consequence that is easy to miss and matters a great deal for any
pre-processing work: **channel selection is competitive**. Adding energy to one
band can push another band out of the transmitted set, deleting it entirely. A
pre-processor that "enhances" a signal by boosting content may therefore remove
more information than it adds. Conversely, removing a loud but uninformative
masker can promote quieter, more useful content into the transmitted set.

Set ``n_selected == n_channels`` to model CIS, which transmits every channel.
"""

from __future__ import annotations

import numpy as np


def select_n_of_m(
    env: np.ndarray,
    n_selected: int,
    frame_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Zero all but the ``n_selected`` strongest channels in each frame.

    Parameters
    ----------
    env:
        Channel envelopes, shape ``(n_channels, n_samples)``.
    n_selected:
        The ``n`` in n-of-m. Must be between 1 and ``n_channels``.
    frame_samples:
        Frame length in samples. Selection is constant within a frame, as in a
        real device where it is recomputed once per stimulation cycle.

    Returns
    -------
    selected_env:
        Envelopes with non-selected channels zeroed, same shape as ``env``.
    mask:
        Boolean array, same shape, True where a channel was transmitted. Useful
        for diagnosing selection instability - a rapidly changing mask indicates
        channels competing, which is typical of polyphonic music and is a strong
        hint that source separation would help.
    """
    env = np.atleast_2d(np.asarray(env, dtype=float))
    n_channels, n_samples = env.shape

    if not 1 <= n_selected <= n_channels:
        raise ValueError(
            f"n_selected ({n_selected}) must be between 1 and n_channels ({n_channels})"
        )
    if frame_samples < 1:
        raise ValueError(f"frame_samples must be >= 1, got {frame_samples}")

    mask = np.zeros_like(env, dtype=bool)

    if n_selected == n_channels:
        mask[:] = True
        return env.copy(), mask

    for start in range(0, n_samples, frame_samples):
        stop = min(start + frame_samples, n_samples)
        frame_energy = env[:, start:stop].mean(axis=1)
        # argpartition is O(n) versus argsort's O(n log n); with 22 channels the
        # difference is immaterial, but this runs once per frame over long files.
        winners = np.argpartition(frame_energy, -n_selected)[-n_selected:]
        mask[winners, start:stop] = True

    return env * mask, mask


def selection_stability(mask: np.ndarray, frame_samples: int) -> float:
    """Fraction of frame-to-frame transitions in which the selected set changed.

    Returns a value in [0, 1]; 0 means the same channels were chosen throughout,
    1 means the set changed at every frame boundary. High instability suggests
    the material is overloading the available channels.
    """
    mask = np.atleast_2d(np.asarray(mask, dtype=bool))
    n_samples = mask.shape[1]
    starts = range(0, n_samples, frame_samples)
    sets = [frozenset(np.flatnonzero(mask[:, i]).tolist()) for i in starts]
    if len(sets) < 2:
        return 0.0
    changes = sum(1 for a, b in zip(sets[:-1], sets[1:], strict=True) if a != b)
    return changes / (len(sets) - 1)
