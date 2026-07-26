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


def resynthesise(
    env: np.ndarray,
    filterbank: Filterbank,
    carrier: str = "noise",
    rng: np.random.Generator | None = None,
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
    else:
        raise ValueError(f"unknown carrier {carrier!r}; use 'noise' or 'tone'")

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
