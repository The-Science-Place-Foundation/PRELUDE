"""Visualisation.

The electrodogram plot is the important one. Cochlear implant processing is not
intuitively predictable, and being able to *see* what reaches the nerve is how
structural mistakes get caught early rather than after months of tuning against a
wrong model.

Requires the optional ``viz`` extra: ``pip install -e ".[viz]"``.
"""

from __future__ import annotations

import numpy as np


def _require_matplotlib():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "plotting requires matplotlib; install with: pip install -e '.[viz]'"
        ) from exc
    return plt


def plot_electrodogram(
    electrodogram: np.ndarray,
    sample_rate: int,
    center_freqs: np.ndarray | None = None,
    title: str = "Electrodogram",
    ax=None,
    cmap: str = "magma",
):
    """Plot stimulation level as channel against time.

    This is the information actually delivered to the auditory nerve. Comparing
    the electrodograms of two signals is far more informative than comparing
    their waveforms or even their spectrograms.

    Parameters
    ----------
    electrodogram:
        Stimulation levels, shape ``(n_channels, n_samples)``.
    sample_rate:
        Sample rate in Hz.
    center_freqs:
        Channel centre frequencies, used to label the vertical axis. Falls back
        to channel indices when omitted.
    """
    plt = _require_matplotlib()
    e = np.atleast_2d(np.asarray(electrodogram, dtype=float))

    if ax is None:
        _, ax = plt.subplots(figsize=(11, 4))

    duration = e.shape[1] / sample_rate
    im = ax.imshow(
        e, aspect="auto", origin="lower", cmap=cmap,
        extent=(0.0, duration, -0.5, e.shape[0] - 0.5),
        interpolation="nearest",
    )
    ax.set_xlabel("Time (s)")

    if center_freqs is not None:
        step = max(1, len(center_freqs) // 8)
        ticks = np.arange(0, len(center_freqs), step)
        ax.set_yticks(ticks)
        ax.set_yticklabels([f"{center_freqs[i]:.0f}" for i in ticks])
        ax.set_ylabel("Channel centre frequency (Hz)")
    else:
        ax.set_ylabel("Channel (apical to basal)")

    ax.set_title(title)
    ax.figure.colorbar(im, ax=ax, label="Stimulation level")
    return ax


def plot_selection_mask(
    mask: np.ndarray,
    sample_rate: int,
    title: str = "Transmitted channels (n-of-m)",
    ax=None,
):
    """Plot which channels won selection in each frame.

    Rapid vertical striping indicates channels competing for a limited transmission
    budget, which is characteristic of polyphonic material and a strong hint that
    source separation would help.
    """
    plt = _require_matplotlib()
    m = np.atleast_2d(np.asarray(mask, dtype=float))

    if ax is None:
        _, ax = plt.subplots(figsize=(11, 3))

    ax.imshow(
        m, aspect="auto", origin="lower", cmap="Greys",
        extent=(0.0, m.shape[1] / sample_rate, -0.5, m.shape[0] - 0.5),
        interpolation="nearest", vmin=0, vmax=1,
    )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Channel")
    ax.set_title(title)
    return ax


def plot_envelope_comparison(
    envelopes: dict[str, np.ndarray],
    sample_rate: int,
    channel: int = 0,
    ax=None,
):
    """Overlay one channel's envelope across several conditions.

    Useful for showing what a pre-processing step did to the cue the implant
    actually transmits. Signals must be level-matched beforehand or the
    comparison shows only the gain difference.
    """
    plt = _require_matplotlib()

    if ax is None:
        _, ax = plt.subplots(figsize=(11, 3))

    for label, env in envelopes.items():
        e = np.atleast_2d(np.asarray(env, dtype=float))[channel]
        t = np.arange(len(e)) / sample_rate
        ax.plot(t, e, label=label, linewidth=1.0)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Envelope amplitude")
    ax.set_title(f"Channel {channel} envelope")
    ax.legend()
    return ax
