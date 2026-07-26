# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Resynthesis - turning channel envelopes back into audible sound.

A cochlear implant delivers electrical pulses, which cannot be heard by a
normal-hearing listener. To make the simulation audible we resynthesise: each
channel's envelope modulates a carrier confined to that channel's frequency band,
and the results are summed.

    y(t) = sum_i  envelope_i(t) * carrier_i(t)

This is the defining operation of a vocoder. Summing bandpass-filtered signals
*without* replacing their fine structure does not simulate an implant - it leaves
intact precisely the information the device destroys.

Two carriers are offered. Noise is the standard in the intelligibility literature
(Shannon et al., 1995) and gives the characteristic harsh, breathy quality. Tones
produce a cleaner, more musical result that some listeners find closer to their
percept; the choice is ultimately an empirical question for the listener being
modelled.
"""

from __future__ import annotations

import numpy as np

from .filterbank import Filterbank


def pulse_carrier(
    n_channels: int,
    n_samples: int,
    rate_hz: float,
    sample_rate: int,
    synchronization: float = 1.0,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Interleaved biphasic-style pulse trains, one per channel.

    Real devices stimulate with discrete pulses at a fixed rate, not with
    continuous noise. How faithfully the auditory nerve follows those pulses
    varies between listeners and is the physiological quantity
    ``synchronization`` models: at 1.0 neural activity locks tightly to the
    stimulus, at 0.0 it is essentially random and the percept is noise-like.

    Pulses are **interleaved** across channels - each channel's train is offset
    by a fraction of the pulse period - because simultaneous stimulation on
    adjacent electrodes would sum in the cochlea. Avoiding that is what the
    "interleaved" in Continuous Interleaved Sampling refers to.

    Parameters
    ----------
    rate_hz:
        Stimulation rate per channel, in pulses per second.
    synchronization:
        0.0 gives white noise, 1.0 gives exact pulse timing, and intermediate
        values jitter pulse positions. Below roughly 800 pps real devices show
        unwanted neural synchronisation artefacts, which this does not model.

    Returns
    -------
    np.ndarray
        Shape ``(n_channels, n_samples)``, unnormalised. Band-limit it through
        the analysis filterbank before use, which turns each impulse into that
        channel's impulse response - physically what a pulse on one electrode
        does.
    """
    if not 0.0 <= synchronization <= 1.0:
        raise ValueError(f"synchronization must be in [0, 1], got {synchronization}")
    if rate_hz <= 0:
        raise ValueError(f"rate_hz must be positive, got {rate_hz}")
    if rng is None:
        rng = np.random.default_rng()

    period = sample_rate / rate_hz
    if period < 2.0:
        raise ValueError(
            f"stimulation rate {rate_hz} Hz is too high for sample rate "
            f"{sample_rate} Hz; pulses would be less than 2 samples apart"
        )

    pulses = np.zeros((n_channels, n_samples))
    jitter = (1.0 - synchronization) * period / 2.0

    for ch in range(n_channels):
        # Interleave: stagger each channel by a fraction of the pulse period.
        offset = period * ch / n_channels
        idx = np.arange(offset, n_samples, period)
        if jitter > 0:
            idx = idx + rng.uniform(-jitter, jitter, size=idx.shape)
        idx = np.clip(np.round(idx).astype(int), 0, n_samples - 1)
        # Alternate sign, approximating charge-balanced biphasic pulses.
        np.add.at(pulses[ch], idx, np.where(np.arange(len(idx)) % 2, -1.0, 1.0))

    if synchronization < 1.0:
        noise = rng.standard_normal((n_channels, n_samples))
        pulses = synchronization * pulses + (1.0 - synchronization) * noise

    return pulses


def resynthesise(
    env: np.ndarray,
    filterbank: Filterbank,
    carrier: str = "noise",
    rng: np.random.Generator | None = None,
    rate_hz: float | None = None,
    synchronization: float = 1.0,
) -> np.ndarray:
    """Resynthesise audio from channel envelopes.

    Parameters
    ----------
    env:
        Channel envelopes in the acoustic domain, shape
        ``(n_channels, n_samples)``. If these came from a loudness map, invert it
        first - see :func:`prelude.ci_sim.mapping.invert_loudness_map`.
    filterbank:
        The same filterbank used for analysis. Reusing it guarantees each carrier
        is confined to its own band.
    carrier:
        ``"noise"`` for band-limited white noise, ``"tone"`` for a sinusoid at the
        channel centre frequency.
    rng:
        Random generator for the noise carrier. Pass a seeded generator for
        reproducible output; results are otherwise not bit-reproducible.

    Returns
    -------
    np.ndarray
        Mono signal, length ``n_samples``. Not normalised - apply loudness
        handling from :mod:`prelude.audio.loudness` before playback.
    """
    env = np.atleast_2d(np.asarray(env, dtype=float))
    n_channels, n_samples = env.shape

    if n_channels != filterbank.n_channels:
        raise ValueError(
            f"envelope has {n_channels} channels but filterbank has "
            f"{filterbank.n_channels}"
        )

    if carrier == "noise":
        if rng is None:
            rng = np.random.default_rng()
        raw = rng.standard_normal((n_channels, n_samples))
        # Band-limit each carrier to its own channel. Omitting this step yields
        # broadband noise shaped only by the envelope, which loses the spectral
        # structure the filterbank just established.
        carriers = filterbank.apply_multi(raw)
    elif carrier == "tone":
        t = np.arange(n_samples, dtype=float) / filterbank.sample_rate
        phase = (
            rng.uniform(0, 2 * np.pi, size=n_channels)
            if rng is not None
            else np.zeros(n_channels)
        )
        carriers = np.stack(
            [
                np.sin(2 * np.pi * f * t + p)
                for f, p in zip(filterbank.center_freqs, phase, strict=True)
            ]
        )
    elif carrier == "pulse":
        if rate_hz is None:
            raise ValueError("carrier='pulse' requires rate_hz (the stimulation rate)")
        carriers = filterbank.apply_multi(
            pulse_carrier(
                n_channels,
                n_samples,
                rate_hz,
                filterbank.sample_rate,
                synchronization=synchronization,
                rng=rng,
            )
        )
    else:
        raise ValueError(
            f"unknown carrier {carrier!r}; use 'noise', 'tone' or 'pulse'"
        )

    return (env * _unit_rms(carriers)).sum(axis=0)


def _unit_rms(carriers: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Scale each carrier to unit RMS.

    This is not cosmetic. Band-limited white noise has RMS proportional to the
    square root of its bandwidth, and a cochleotopic filterbank's bands widen
    steeply towards the base - with Greenwood spacing over 300-8500 Hz, the most
    basal band is around fifty times wider than the most apical one. Modulating
    un-normalised carriers therefore weights each channel by its bandwidth rather
    than by its envelope, tilting the output heavily towards high frequencies.

    The requirement follows from what an envelope means. For output band ``i`` to
    carry the same energy as input band ``i``, we need
    ``rms(env_i * c_i) ~= rms(band_i)``. Since ``rms(env_i * c_i)`` is roughly
    ``rms(env_i) * rms(c_i)``, the carrier RMS must be a constant independent of
    the band. Leaving it proportional to bandwidth weights every channel by how
    wide it happens to be.

    Measured effect, against an external reference simulator on a speech sample:
    energy above 4 kHz fell from 0.375 to 0.070 of the total (the source itself
    has 0.163), and the mean absolute log-distance between the output and
    reference band-energy profiles improved from 0.55 to 0.39.

    Note that per-band envelope *correlation* with that reference did not improve
    (0.65 to 0.64). The two measures answer different questions - one asks where
    the energy sits, the other how it moves over time - and the remaining
    disagreement with that reference is unresolved. See
    ``docs/lab-notebook/`` for the investigation.
    """
    rms = np.sqrt((carriers**2).mean(axis=-1, keepdims=True))
    return carriers / (rms + eps)
