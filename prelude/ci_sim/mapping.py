"""Loudness mapping - acoustic amplitude to electrical stimulation level.

This stage models the most severe constraint in electric hearing. Acoustic
hearing spans roughly 120 dB; the electrical dynamic range between threshold
(T level) and most comfortable loudness (C level) is typically only 6-20 dB. The
processor compresses its input range into that window with a logarithmic-ish
loudness growth function.

Everything the listener hears lives inside that window. Material with wide
dynamic range - a classical recording, say - is largely flattened.

The standard formulation (used by Cochlear Ltd's processors and widely in the
literature) is

    p = log(1 + c * x) / log(1 + c)

for input ``x`` normalised to [0, 1], where ``c`` controls the steepness of
compression. The result is then scaled into [T, C].
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LoudnessMap:
    """Per-channel threshold and comfort levels, in arbitrary current units.

    Real devices express these in device-specific current units; the absolute
    scale does not matter for simulation, only the ratio C/T and the resulting
    dynamic range. Supply per-channel arrays when a real MAP is available -
    thresholds vary substantially across electrodes.
    """

    t_level: np.ndarray
    c_level: np.ndarray
    base: float = 416.2
    input_floor_db: float = -60.0

    @classmethod
    def uniform(
        cls,
        n_channels: int,
        dynamic_range_db: float = 12.0,
        base: float = 416.2,
        input_floor_db: float = -60.0,
    ) -> LoudnessMap:
        """A generic map with the same T and C on every channel.

        ``dynamic_range_db`` is the electrical range between T and C. Values of
        6-20 dB are typical; 12 dB is a reasonable generic default. This is a
        placeholder for a real clinical MAP, not a substitute for one.
        """
        t = np.ones(n_channels, dtype=float)
        c = t * (10.0 ** (dynamic_range_db / 20.0))
        return cls(t_level=t, c_level=c, base=base, input_floor_db=input_floor_db)

    @property
    def n_channels(self) -> int:
        return len(self.t_level)

    @property
    def dynamic_range_db(self) -> np.ndarray:
        return 20.0 * np.log10(self.c_level / self.t_level)


def apply_loudness_map(
    env: np.ndarray,
    loudness_map: LoudnessMap,
    reference: float | None = None,
) -> np.ndarray:
    """Compress channel envelopes into the electrical dynamic range.

    Parameters
    ----------
    env:
        Channel envelopes, shape ``(n_channels, n_samples)``, non-negative.
    loudness_map:
        Per-channel T and C levels.
    reference:
        Amplitude mapped to C level. Defaults to the maximum of ``env``, which
        makes the mapping signal-relative. **Pass an explicit, fixed reference
        when comparing two signals** - otherwise each is normalised to its own
        peak and any level difference between them silently disappears.

    Returns
    -------
    np.ndarray
        Stimulation levels in the same units as T and C, shape as ``env``.
        Channels whose input falls below ``input_floor_db`` map to zero, modelling
        sub-threshold input rather than clamping to T.
    """
    env = np.atleast_2d(np.asarray(env, dtype=float))
    if env.shape[0] != loudness_map.n_channels:
        raise ValueError(
            f"envelope has {env.shape[0]} channels but map has "
            f"{loudness_map.n_channels}"
        )

    if reference is None:
        reference = float(env.max())
    if reference <= 0:
        return np.zeros_like(env)

    x = np.clip(env / reference, 0.0, 1.0)

    floor = 10.0 ** (loudness_map.input_floor_db / 20.0)
    audible = x > floor

    c = loudness_map.base
    compressed = np.log1p(c * x) / np.log1p(c)

    t = loudness_map.t_level[:, None]
    c_lvl = loudness_map.c_level[:, None]
    out = t + compressed * (c_lvl - t)
    return np.where(audible, out, 0.0)


def invert_loudness_map(
    levels: np.ndarray,
    loudness_map: LoudnessMap,
    reference: float = 1.0,
) -> np.ndarray:
    """Map stimulation levels back to acoustic amplitude, for resynthesis.

    Resynthesis needs an acoustic-domain envelope. Passing the compressed levels
    straight to a carrier would apply the compression twice - once here and again
    in the listener's own perception - so the mapping is inverted before the
    signal is turned back into sound.
    """
    levels = np.atleast_2d(np.asarray(levels, dtype=float))
    t = loudness_map.t_level[:, None]
    c_lvl = loudness_map.c_level[:, None]

    frac = np.clip((levels - t) / (c_lvl - t), 0.0, 1.0)
    c = loudness_map.base
    x = (np.expm1(frac * np.log1p(c))) / c
    return np.where(levels > 0, x * reference, 0.0)
