# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Envelope extraction.

The envelope is the information a cochlear implant actually transmits. Temporal
fine structure - the rapid phase detail within each band - is discarded by
standard coding strategies and replaced by a fixed-rate pulse carrier. Getting
this stage right is therefore the difference between simulating an implant and
merely distorting audio.

Two methods are provided, both used by real devices and by the research
literature:

``hilbert``
    Magnitude of the analytic signal, optionally lowpassed. Matches the
    "Hilbert + FIR" setting recorded in the archived CI_SIM configurations.

``rectify``
    Half-wave rectification followed by a lowpass filter. Cheaper, and closer to
    what early hardware did.

Note that rectification *without* a subsequent lowpass does not produce an
envelope - it produces a distorted copy of the band signal, rich in harmonics
that were not in the input. The lowpass is not optional.
"""

from __future__ import annotations

import numpy as np
from scipy import signal


def extract_envelope(
    bands: np.ndarray,
    sample_rate: int,
    method: str = "hilbert",
    cutoff_hz: float = 300.0,
    order: int = 4,
) -> np.ndarray:
    """Extract the amplitude envelope of each channel.

    Parameters
    ----------
    bands:
        Bandpass-filtered channels, shape ``(n_channels, n_samples)``.
    sample_rate:
        Sample rate in Hz.
    method:
        ``"hilbert"`` or ``"rectify"``.
    cutoff_hz:
        Lowpass cutoff applied to the envelope. Real devices typically use
        50-400 Hz. Higher cutoffs let more temporal fine structure survive and
        will make the simulation sound better than the device does - which is the
        wrong kind of error for this project. Pass ``None`` to skip smoothing
        (Hilbert only).
    order:
        Butterworth order of the smoothing lowpass.

    Returns
    -------
    np.ndarray
        Non-negative amplitude envelopes, shape ``(n_channels, n_samples)``.

    Notes
    -----
    The result is an *amplitude* envelope, not a power envelope. Downstream
    stages assume amplitude: modulating a carrier by power would square the
    dynamics. If you port code that computes a mean-square envelope, take the
    square root before using it here.
    """
    bands = np.atleast_2d(np.asarray(bands, dtype=float))

    if method == "hilbert":
        env = np.abs(signal.hilbert(bands, axis=-1))
    elif method == "rectify":
        env = np.maximum(bands, 0.0)
        if cutoff_hz is None:
            raise ValueError(
                "method='rectify' requires a lowpass cutoff; rectification alone "
                "does not produce an envelope."
            )
    else:
        raise ValueError(f"unknown method {method!r}; use 'hilbert' or 'rectify'")

    if cutoff_hz is not None:
        nyquist = sample_rate / 2.0
        if not 0 < cutoff_hz < nyquist:
            raise ValueError(
                f"cutoff_hz ({cutoff_hz}) must be between 0 and Nyquist ({nyquist})"
            )
        sos = signal.butter(order, cutoff_hz / nyquist, btype="low", output="sos")
        env = signal.sosfiltfilt(sos, env, axis=-1)

    # Zero-phase filtering can produce small negative values around sharp onsets;
    # an amplitude envelope is non-negative by definition.
    return np.maximum(env, 0.0)


def envelope_modulation_depth(env: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Per-channel modulation depth, ``(max - min) / (max + min)``, in [0, 1].

    Modulation depth is the primary cue a cochlear implant conveys, so this is a
    useful diagnostic when comparing processed against unprocessed audio. Values
    near zero mean the channel carries almost no information.
    """
    env = np.atleast_2d(np.asarray(env, dtype=float))
    hi = env.max(axis=-1)
    lo = env.min(axis=-1)
    return (hi - lo) / (hi + lo + eps)
