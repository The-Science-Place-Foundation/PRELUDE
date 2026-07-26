# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Loudness normalisation and peak limiting.

**This module is a safety boundary, not a convenience.**

Every signal that may reach a human ear must pass through :func:`prepare_for_playback`
first. Listening-study participants frequently include people with residual
hearing that is irreplaceable and, in progressive conditions, already
deteriorating. An over-level playback is not a recoverable mistake.

Level matching is also a methodological requirement, not only a safety one:
loudness differences dominate every other perceptual judgement, so an unmatched
comparison measures level rather than whatever it was intended to measure.

The LUFS implementation follows ITU-R BS.1770-4. Gating is applied for the
integrated measurement, but the loudness range and true-peak oversampling of the
full standard are simplified; for publication-grade loudness measurement, use a
dedicated implementation such as ``pyloudnorm``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

#: Default integrated loudness target for listening material.
DEFAULT_TARGET_LUFS = -23.0

#: Default true-peak ceiling. Leaves headroom for inter-sample peaks and for
#: codec-induced overshoot on the playback path.
DEFAULT_PEAK_CEILING_DB = -1.0


class LoudnessSafetyError(RuntimeError):
    """Raised when a signal cannot be made safe for playback."""


def _k_weighting_sos(sample_rate: int) -> np.ndarray:
    """K-weighting filter (BS.1770): a high-shelf followed by a highpass."""
    # Shelving filter, coefficients specified at 48 kHz and re-derived by
    # bilinear transform for other rates.
    f0 = 1681.974450955533
    g = 3.999843853973347
    q = 0.7071752369554196

    k = np.tan(np.pi * f0 / sample_rate)
    vh = 10.0 ** (g / 20.0)
    vb = vh**0.4996667741545416
    denom = 1.0 + k / q + k * k
    b_shelf = (
        np.array([vh + vb * k / q + k * k, 2.0 * (k * k - vh), vh - vb * k / q + k * k])
        / denom
    )
    a_shelf = np.array([1.0, 2.0 * (k * k - 1.0) / denom, (1.0 - k / q + k * k) / denom])

    # Highpass.
    f0 = 38.13547087602444
    q = 0.5003270373238773
    k = np.tan(np.pi * f0 / sample_rate)
    denom = 1.0 + k / q + k * k
    b_hp = np.array([1.0, -2.0, 1.0])
    a_hp = np.array([1.0, 2.0 * (k * k - 1.0) / denom, (1.0 - k / q + k * k) / denom])

    return np.stack(
        [
            np.concatenate([b_shelf, a_shelf]),
            np.concatenate([b_hp, a_hp]),
        ]
    )


def integrated_lufs(x: np.ndarray, sample_rate: int) -> float:
    """Gated integrated loudness in LUFS, per ITU-R BS.1770-4.

    Returns ``-inf`` for silence.
    """
    x = np.asarray(x, dtype=float)
    if x.ndim == 1:
        x = x[None, :]

    filtered = signal.sosfilt(_k_weighting_sos(sample_rate), x, axis=-1)

    block = max(1, int(0.400 * sample_rate))
    hop = max(1, block // 4)
    n = filtered.shape[-1]
    if n < block:
        block, hop = n, max(1, n // 4)

    starts = range(0, max(1, n - block + 1), hop)
    powers = np.array([(filtered[:, s : s + block] ** 2).mean(axis=-1).sum() for s in starts])
    powers = powers[powers > 0]
    if powers.size == 0:
        return float("-inf")

    loud = -0.691 + 10.0 * np.log10(powers)

    # Absolute gate, then relative gate at -10 LU below the ungated mean.
    keep = loud > -70.0
    if not keep.any():
        return float("-inf")
    rel = -0.691 + 10.0 * np.log10(powers[keep].mean()) - 10.0
    keep &= loud > rel
    if not keep.any():
        return float("-inf")

    return float(-0.691 + 10.0 * np.log10(powers[keep].mean()))


def true_peak_db(x: np.ndarray, oversample: int = 4) -> float:
    """Approximate true-peak level in dBFS, via oversampling.

    Inter-sample peaks can exceed the sample peak by a decibel or more, which
    matters because reconstruction happens after our last chance to intervene.
    """
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return float("-inf")
    up = signal.resample_poly(x, oversample, 1, axis=-1)
    peak = float(np.abs(up).max())
    return 20.0 * np.log10(peak) if peak > 0 else float("-inf")


@dataclass(frozen=True)
class PlaybackReport:
    """Record of what :func:`prepare_for_playback` did, for the session log."""

    input_lufs: float
    output_lufs: float
    gain_db: float
    input_true_peak_db: float
    output_true_peak_db: float
    limited: bool

    def summary(self) -> str:
        return (
            f"{self.input_lufs:.1f} -> {self.output_lufs:.1f} LUFS "
            f"(gain {self.gain_db:+.1f} dB), "
            f"true peak {self.output_true_peak_db:.1f} dBTP"
            + (", limiter engaged" if self.limited else "")
        )


def prepare_for_playback(
    x: np.ndarray,
    sample_rate: int,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: float = DEFAULT_PEAK_CEILING_DB,
) -> tuple[np.ndarray, PlaybackReport]:
    """Normalise loudness and enforce a true-peak ceiling.

    Call this on **every** signal before a human hears it. There is deliberately
    no bypass argument.

    Returns the processed signal and a :class:`PlaybackReport` to be recorded in
    the session log, so that any later question about presentation level has an
    answer.

    Raises
    ------
    LoudnessSafetyError
        If the signal contains NaN or infinite values, or is silent. Both
        indicate an upstream defect, and neither should be quietly presented to a
        listener.
    """
    x = np.asarray(x, dtype=float)

    if not np.all(np.isfinite(x)):
        raise LoudnessSafetyError(
            "signal contains NaN or infinite values; refusing to prepare it for "
            "playback. Check the processing chain for division by zero or an "
            "unstable filter."
        )
    if x.size == 0 or not np.any(x):
        raise LoudnessSafetyError("signal is empty or silent")

    in_lufs = integrated_lufs(x, sample_rate)
    in_peak = true_peak_db(x)

    if not np.isfinite(in_lufs):
        raise LoudnessSafetyError("could not measure loudness; signal may be silent")

    gain_db = target_lufs - in_lufs
    y = x * (10.0 ** (gain_db / 20.0))

    limited = False
    out_peak = true_peak_db(y)
    if out_peak > peak_ceiling_db:
        y = y * (10.0 ** ((peak_ceiling_db - out_peak) / 20.0))
        limited = True

    report = PlaybackReport(
        input_lufs=in_lufs,
        output_lufs=integrated_lufs(y, sample_rate),
        gain_db=gain_db,
        input_true_peak_db=in_peak,
        output_true_peak_db=true_peak_db(y),
        limited=limited,
    )
    return y, report


def match_levels(
    signals: list[np.ndarray],
    sample_rate: int,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: float = DEFAULT_PEAK_CEILING_DB,
) -> tuple[list[np.ndarray], list[PlaybackReport]]:
    """Bring several signals to a common loudness for comparison.

    Use this for any A/B or forced-choice comparison. Comparing signals at
    different levels measures the level difference, not the processing.
    """
    out, reports = [], []
    for s in signals:
        y, r = prepare_for_playback(s, sample_rate, target_lufs, peak_ceiling_db)
        out.append(y)
        reports.append(r)
    return out, reports
