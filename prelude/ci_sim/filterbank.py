# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Analysis filterbanks for cochlear implant simulation.

Two spacings are provided:

``erb``
    Equivalent Rectangular Bandwidth spacing with gammatone filters, following
    Glasberg & Moore (1990) and Slaney's Auditory Toolbox (1993). This models the
    *biological* cochlea and is the right choice when simulating normal hearing or
    when reproducing a Shannon-style noise vocoder.

``greenwood``
    Frequency-to-place spacing after Greenwood (1990), band edges placed at equal
    cochlear distances. This models *electrode position* and is the right choice
    when the band edges should correspond to physical contacts on an array.

``table``
    Explicit band edges, for reproducing a manufacturer's frequency allocation
    table verbatim. Prefer this whenever the real allocation is known.

Linear spacing is deliberately not offered: the cochlea is approximately
logarithmic, and linear bands over-resolve the treble while under-resolving the
bass. See ``docs/01-DOMAIN-PRIMER.md`` section 1.2.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

# Glasberg & Moore (1990) ERB parameters.
_EAR_Q = 9.26449
_MIN_BW = 24.7

# Greenwood (1990) human cochlear map constants.
_GREENWOOD_A = 165.4
_GREENWOOD_ALPHA = 2.1
_GREENWOOD_K = 0.88


def erb_space(low_freq: float, high_freq: float, num: int) -> np.ndarray:
    """Return ``num`` centre frequencies spaced equally on the ERB scale.

    Ordered low to high. Mirrors ``ERBSpace`` from Slaney's Auditory Toolbox,
    which returns high to low; we reverse for consistency with the rest of the
    package, where channel 0 is always the most apical (lowest frequency).
    """
    if num < 1:
        raise ValueError(f"num must be >= 1, got {num}")
    if not 0 < low_freq < high_freq:
        raise ValueError(f"require 0 < low_freq < high_freq, got {low_freq}, {high_freq}")

    idx = np.arange(1, num + 1, dtype=float)
    overlap = _EAR_Q * _MIN_BW
    cf = -overlap + np.exp(
        idx * (-np.log(high_freq + overlap) + np.log(low_freq + overlap)) / num
    ) * (high_freq + overlap)
    return np.sort(cf)


def greenwood_frequency(position: np.ndarray | float) -> np.ndarray | float:
    """Characteristic frequency (Hz) at normalised cochlear ``position`` in [0, 1].

    ``position`` is measured from the apex, so 0 is the apical (low-frequency) end
    and 1 the basal (high-frequency) end.
    """
    x = np.asarray(position, dtype=float)
    return _GREENWOOD_A * (10.0 ** (_GREENWOOD_ALPHA * x) - _GREENWOOD_K)


def greenwood_position(frequency: np.ndarray | float) -> np.ndarray | float:
    """Inverse of :func:`greenwood_frequency`; returns normalised position in [0, 1]."""
    f = np.asarray(frequency, dtype=float)
    return np.log10(f / _GREENWOOD_A + _GREENWOOD_K) / _GREENWOOD_ALPHA


def greenwood_space(low_freq: float, high_freq: float, num: int) -> np.ndarray:
    """Return ``num`` centre frequencies at equal cochlear distances.

    This is what an electrode array with uniformly spaced contacts spanning
    ``low_freq`` to ``high_freq`` would address.
    """
    if num < 1:
        raise ValueError(f"num must be >= 1, got {num}")
    if not 0 < low_freq < high_freq:
        raise ValueError(f"require 0 < low_freq < high_freq, got {low_freq}, {high_freq}")

    x = np.linspace(greenwood_position(low_freq), greenwood_position(high_freq), num)
    return np.asarray(greenwood_frequency(x), dtype=float)


def erb_bandwidth(cf: np.ndarray) -> np.ndarray:
    """Equivalent rectangular bandwidth (Hz) at each centre frequency."""
    return ((np.asarray(cf, dtype=float) / _EAR_Q) ** 4 + _MIN_BW**4) ** 0.25


def erb_rate(f: np.ndarray | float) -> np.ndarray | float:
    """Position on the ERB-rate scale (Glasberg & Moore 1990)."""
    return 21.4 * np.log10(1.0 + 0.00437 * np.asarray(f, dtype=float))


def erb_rate_inverse(e: np.ndarray | float) -> np.ndarray | float:
    """Frequency in Hz from a position on the ERB-rate scale."""
    return (10.0 ** (np.asarray(e, dtype=float) / 21.4) - 1.0) / 0.00437


def greenwood_edges(low_freq: float, high_freq: float, num: int) -> np.ndarray:
    """Return ``num + 1`` band edges at equal cochlear distances.

    Models an electrode array whose contacts are uniformly spaced along the
    cochlea. Bands tile ``[low_freq, high_freq]`` contiguously and widen towards
    the base, as the cochlea's frequency map does.
    """
    _validate_range(low_freq, high_freq, num)
    x = np.linspace(greenwood_position(low_freq), greenwood_position(high_freq), num + 1)
    return np.asarray(greenwood_frequency(x), dtype=float)


def erb_edges(low_freq: float, high_freq: float, num: int) -> np.ndarray:
    """Return ``num + 1`` band edges spaced equally on the ERB-rate scale.

    Models the biological cochlea's critical-band structure. Use this when
    simulating normal hearing or reproducing a Shannon-style noise vocoder.
    """
    _validate_range(low_freq, high_freq, num)
    e = np.linspace(erb_rate(low_freq), erb_rate(high_freq), num + 1)
    return np.asarray(erb_rate_inverse(e), dtype=float)


def _validate_range(low_freq: float, high_freq: float, num: int) -> None:
    if num < 1:
        raise ValueError(f"num must be >= 1, got {num}")
    if not 0 < low_freq < high_freq:
        raise ValueError(f"require 0 < low_freq < high_freq, got {low_freq}, {high_freq}")


@dataclass(frozen=True)
class Filterbank:
    """A bank of bandpass filters, one per simulated channel.

    Attributes
    ----------
    sos:
        Second-order-section coefficients, shape ``(n_channels, n_sections, 6)``.
        Second-order sections are used rather than transfer-function coefficients
        because high-order bandpass filters are numerically unstable in ``ba``
        form.
    center_freqs:
        Centre frequency of each channel in Hz, ascending.
    edges:
        Band edges in Hz, shape ``(n_channels, 2)``.
    sample_rate:
        Sample rate the filters were designed for. Applying them at a different
        rate is an error.
    """

    sos: np.ndarray
    center_freqs: np.ndarray
    edges: np.ndarray
    sample_rate: int

    @property
    def n_channels(self) -> int:
        return len(self.center_freqs)

    def apply(self, x: np.ndarray) -> np.ndarray:
        """Filter ``x`` into channels; returns shape ``(n_channels, len(x))``.

        Uses zero-phase filtering (``sosfiltfilt``) so that channels are not
        smeared relative to one another by differing group delays. A real device
        is causal and does introduce such delays, but modelling them would
        misalign the channels for analysis without changing the envelope content
        that matters here.
        """
        x = np.asarray(x, dtype=float)
        if x.ndim != 1:
            raise ValueError(f"expected mono 1-D signal, got shape {x.shape}")
        return np.stack([signal.sosfiltfilt(s, x) for s in self.sos])

    def apply_multi(self, rows: np.ndarray) -> np.ndarray:
        """Filter row ``i`` with channel ``i``'s filter; shape preserved.

        Used to band-limit per-channel carriers during resynthesis, where each
        carrier must be confined to its own band rather than every channel
        filtering the same input.
        """
        rows = np.atleast_2d(np.asarray(rows, dtype=float))
        if rows.shape[0] != self.n_channels:
            raise ValueError(
                f"expected {self.n_channels} rows, got {rows.shape[0]}"
            )
        return np.stack(
            [signal.sosfiltfilt(s, r) for s, r in zip(self.sos, rows, strict=True)]
        )


def design_filterbank(
    sample_rate: int,
    n_channels: int,
    low_freq: float = 300.0,
    high_freq: float = 8500.0,
    spacing: str = "greenwood",
    order: int = 4,
    edges: np.ndarray | None = None,
) -> Filterbank:
    """Design a bandpass filterbank for CI simulation.

    Parameters
    ----------
    sample_rate:
        Sample rate in Hz. ``high_freq`` must be below Nyquist.
    n_channels:
        Number of simulated channels. Ignored when ``edges`` is given.
    low_freq, high_freq:
        Analysis range. Defaults follow the archived CI_SIM configurations
        (300-8500 Hz), which are typical of a real allocation.
    spacing:
        ``"greenwood"``, ``"erb"``, or ``"table"``. ``"table"`` requires ``edges``.
    order:
        Butterworth order per band.
    edges:
        Explicit band edges, shape ``(n_channels, 2)``, used when
        ``spacing="table"``. Supply a manufacturer allocation table here.

    Raises
    ------
    ValueError
        If ``high_freq`` is at or above Nyquist. This is deliberately fatal rather
        than clamped: silently dropping out-of-range bands has caused a real,
        hard-to-see defect in this project's history, where a nominally
        21-channel bank ran with 11 channels.
    """
    nyquist = sample_rate / 2.0

    if edges is not None:
        edges = np.asarray(edges, dtype=float)
        if edges.ndim != 2 or edges.shape[1] != 2:
            raise ValueError(f"edges must have shape (n_channels, 2), got {edges.shape}")
        centers = np.sqrt(edges[:, 0] * edges[:, 1])  # geometric mean
    else:
        if high_freq >= nyquist:
            raise ValueError(
                f"high_freq ({high_freq} Hz) must be below Nyquist ({nyquist} Hz) "
                f"for sample_rate={sample_rate}. Raise the sample rate or lower "
                f"high_freq; bands above Nyquist cannot be represented."
            )
        if spacing == "greenwood":
            points = greenwood_edges(low_freq, high_freq, n_channels)
        elif spacing == "erb":
            points = erb_edges(low_freq, high_freq, n_channels)
        else:
            raise ValueError(
                f"unknown spacing {spacing!r}; use 'greenwood', 'erb', or 'table'"
            )
        edges = np.stack([points[:-1], points[1:]], axis=1)
        centers = np.sqrt(edges[:, 0] * edges[:, 1])

    if np.any(edges[:, 1] >= nyquist):
        raise ValueError(
            f"band edge {edges[:, 1].max():.1f} Hz is at or above Nyquist "
            f"({nyquist} Hz). Bands above Nyquist cannot be represented."
        )
    if np.any(edges[:, 0] <= 0):
        raise ValueError("band edges must be positive")
    if np.any(edges[:, 0] >= edges[:, 1]):
        raise ValueError("each band's low edge must be below its high edge")

    sos = np.stack(
        [
            signal.butter(
                order, [lo / nyquist, hi / nyquist], btype="band", output="sos"
            )
            for lo, hi in edges
        ]
    )
    return Filterbank(
        sos=sos,
        center_freqs=np.asarray(centers, dtype=float),
        edges=np.asarray(edges, dtype=float),
        sample_rate=int(sample_rate),
    )


#: Sample rate at which the default 300-8500 Hz analysis range is representable.
#: Also the native output rate of the archived reference simulator, which makes
#: it the natural working rate for this package.
DEFAULT_SAMPLE_RATE = 20000
