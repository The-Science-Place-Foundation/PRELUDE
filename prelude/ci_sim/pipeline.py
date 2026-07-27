# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The cochlear implant simulation pipeline.

Chains the stages in the order a real device applies them:

    filterbank -> envelope -> n-of-m selection -> loudness map
               -> channel interaction -> resynthesis

Every stage is optional and every intermediate is retained, because the value of
this simulator lies as much in inspection as in its audio output. The
electrodogram in particular - the channel-by-time matrix of stimulation levels -
is what actually reaches the auditory nerve, and is the right domain in which to
compare two signals. Waveform comparison is misleading here: two signals that
look quite different can produce near-identical electrodograms, and vice versa.

Example
-------
>>> from prelude.ci_sim import SimulatorConfig, simulate
>>> cfg = SimulatorConfig(n_channels=8, n_selected=8)   # CIS, 8 channels
>>> result = simulate(audio, sample_rate=16000, config=cfg)
>>> result.audio.shape, result.electrodogram.shape
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

import numpy as np

from .envelope import extract_envelope
from .filterbank import Filterbank, design_filterbank
from .interaction import apply_interaction, effective_channels, spread_matrix
from .mapping import LoudnessMap, apply_loudness_map, levels_to_amplitude
from .resynthesis import resynthesise
from .selection import select_n_of_m, selection_stability


@dataclass(frozen=True)
class SimulatorConfig:
    """Parameters of a simulated implant.

    Defaults describe a generic device and are **not** a substitute for a real
    clinical MAP. When the manufacturer's frequency allocation, active electrode
    count, stimulation rate and T/C levels are known, supply them: a simulator
    fitted to a specific listener is a far more useful object than a generic one.

    Attributes
    ----------
    n_channels:
        Number of analysis bands, ``m`` in n-of-m. Real arrays carry 12-22.
    n_selected:
        Channels transmitted per frame, ``n`` in n-of-m. Set equal to
        ``n_channels`` for CIS; 8-12 of 22 is typical for ACE.
    low_freq, high_freq:
        Analysis range in Hz. Must lie below Nyquist.
    spacing:
        ``"greenwood"``, ``"erb"`` or ``"table"``.
    band_edges:
        Explicit allocation table, used when ``spacing="table"``.
    envelope_method, envelope_cutoff_hz:
        See :func:`prelude.ci_sim.envelope.extract_envelope`. Cutoffs of 50-400 Hz
        are typical of real devices.
    stimulation_rate_hz:
        Pulses per second per channel. Sets the frame length for channel
        selection. Real devices run 500-2400 pps.
    dynamic_range_db:
        Electrical dynamic range between T and C levels. 6-20 dB is the realistic
        span; the narrowness of this window is the defining constraint of
        electric hearing.
    interaction_decay_db:
        Current spread falloff per channel of separation. Larger is more focused.
    carrier:
        ``"noise"``, ``"tone"`` or ``"pulse"``. Real devices stimulate with
        discrete pulses; ``"pulse"`` models that and is the faithful choice when
        reproducing a device. ``"noise"`` is the classical vocoder used
        throughout the intelligibility literature.
    synchronization:
        How tightly neural activity follows the stimulus, in [0, 1]. Applies to
        the pulse carrier only: 1.0 is exact pulse timing, 0.0 degenerates to
        noise. Models auditory-nerve health, which varies between listeners.
    n_electrodes:
        Physical contacts on the array, before any are switched off. Defaults to
        ``n_channels`` — that is, a device with nothing deactivated. Set this
        together with ``deactivated_electrodes`` to model a real array with
        dead contacts.
    deactivated_electrodes:
        Electrode numbers that are switched off, 1-based, in the manufacturer's
        numbering.

        **Deactivation is not simply "fewer channels", and modelling it that way
        misses the whole effect.** A fitting program reallocates the frequency
        range across the surviving contacts, so the processor still analyses the
        full band — each surviving channel just gets a wider slice. What it
        cannot do is move the electrodes. The band that used to go to a dead
        contact is now delivered by its neighbours, at *their* place in the
        cochlea, so a region of the frequency-to-place map is displaced.

        The simulator models this by analysing with the reallocated bands and
        resynthesising at the surviving electrodes' physical places. Passing a
        reduced ``n_channels`` instead would reproduce the loss of resolution but
        none of the place mismatch, which is the part a listener notices.
    electrode_numbering:
        ``"basal_first"`` (Cochlear: electrode 1 sits at the base and carries the
        *highest* frequency) or ``"apical_first"`` (electrode 1 at the apex,
        lowest frequency).

        Stated explicitly because getting it backwards is silent and total: it
        swaps a high-frequency dead contact for a low-frequency one, and the
        simulation still runs and still sounds like a cochlear implant.
    seed:
        Seed for the noise carrier, for reproducible output.
    """

    n_channels: int = 22
    n_selected: int = 8
    low_freq: float = 300.0
    high_freq: float = 8500.0
    spacing: str = "greenwood"
    band_edges: list[list[float]] | None = None

    n_electrodes: int | None = None
    deactivated_electrodes: tuple[int, ...] = ()
    electrode_numbering: str = "basal_first"

    envelope_method: str = "hilbert"
    envelope_cutoff_hz: float | None = 300.0

    stimulation_rate_hz: float = 900.0
    dynamic_range_db: float = 12.0
    interaction_decay_db: float = 8.0

    carrier: str = "noise"
    synchronization: float = 1.0
    seed: int | None = None

    apply_selection: bool = True
    apply_mapping: bool = True
    apply_interaction: bool = True

    def __post_init__(self) -> None:
        if self.deactivated_electrodes:
            total = self.n_electrodes
            if total is None:
                raise ValueError(
                    "deactivated_electrodes needs n_electrodes: which contacts "
                    "are off is meaningless without knowing how many there are"
                )
            bad = [e for e in self.deactivated_electrodes if not 1 <= e <= total]
            if bad:
                raise ValueError(
                    f"electrode number(s) {bad} outside 1..{total}. Numbering is "
                    f"1-based, as on a clinic printout"
                )
            if len(set(self.deactivated_electrodes)) != len(self.deactivated_electrodes):
                raise ValueError(
                    f"repeated electrode in {self.deactivated_electrodes}; each "
                    f"contact is either on or off"
                )
            surviving = total - len(set(self.deactivated_electrodes))
            if surviving != self.n_channels:
                raise ValueError(
                    f"n_channels ({self.n_channels}) must equal the surviving "
                    f"contacts ({total} - {len(set(self.deactivated_electrodes))} "
                    f"= {surviving}). A processor allocates one channel per live "
                    f"electrode; a mismatch here means one of the two is wrong."
                )
        if self.electrode_numbering not in ("basal_first", "apical_first"):
            raise ValueError(
                f"electrode_numbering must be 'basal_first' or 'apical_first', "
                f"got {self.electrode_numbering!r}"
            )
        if self.n_selected > self.n_channels:
            raise ValueError(
                f"n_selected ({self.n_selected}) cannot exceed n_channels "
                f"({self.n_channels})"
            )
        if self.stimulation_rate_hz <= 0:
            raise ValueError("stimulation_rate_hz must be positive")
        if not 0.0 <= self.synchronization <= 1.0:
            raise ValueError(
                f"synchronization must be in [0, 1], got {self.synchronization}"
            )

    def hash(self) -> str:
        """Short stable hash of the configuration, for artifact provenance.

        Every output file should record this. The archived predecessor of this
        project performed parameter sweeps by editing source between runs, and it
        is now impossible to say which settings produced which file.
        """
        blob = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


def electrode_to_band_index(electrode: int, n_electrodes: int,
                            numbering: str = "basal_first") -> int:
    """Position of an electrode in an ascending-frequency filterbank.

    Filterbanks here are indexed low frequency to high. Cochlear numbers
    electrodes the other way round: **electrode 1 sits at the base and carries
    the highest frequency**, electrode 22 at the apex carries the lowest. So
    under ``basal_first`` the two orderings are mirror images, and reading one
    as the other swaps the top of the frequency range for the bottom.

    That error is silent. The simulation runs, the output still sounds like a
    cochlear implant, and a dead 7 kHz contact has been modelled as a dead
    300 Hz one.

    >>> electrode_to_band_index(1, 22)     # most basal -> highest band
    21
    >>> electrode_to_band_index(22, 22)    # most apical -> lowest band
    0
    >>> electrode_to_band_index(1, 22, "apical_first")
    0
    """
    if not 1 <= electrode <= n_electrodes:
        raise ValueError(f"electrode {electrode} outside 1..{n_electrodes}")
    if numbering == "basal_first":
        return n_electrodes - electrode
    if numbering == "apical_first":
        return electrode - 1
    raise ValueError(f"unknown numbering {numbering!r}")


def _surviving_band_indices(config: SimulatorConfig) -> list[int]:
    """Ascending-frequency band indices of the electrodes still in use."""
    dead = {
        electrode_to_band_index(e, config.n_electrodes, config.electrode_numbering)
        for e in config.deactivated_electrodes
    }
    return [i for i in range(config.n_electrodes) if i not in dead]


@dataclass
class SimulationResult:
    """Output of :func:`simulate`, including all intermediates."""

    audio: np.ndarray
    sample_rate: int
    config: SimulatorConfig

    bands: np.ndarray = field(repr=False)
    envelopes: np.ndarray = field(repr=False)
    electrodogram: np.ndarray = field(repr=False)
    selection_mask: np.ndarray | None = field(default=None, repr=False)
    filterbank: Filterbank | None = field(default=None, repr=False)

    @property
    def n_channels(self) -> int:
        return self.envelopes.shape[0]

    def diagnostics(self) -> dict:
        """Summary statistics worth logging alongside any result."""
        d: dict = {
            "config_hash": self.config.hash(),
            "n_channels": self.n_channels,
            "duration_s": round(self.audio.shape[-1] / self.sample_rate, 3),
        }
        if self.selection_mask is not None:
            frame = max(1, int(self.sample_rate / self.config.stimulation_rate_hz))
            d["selection_stability"] = round(
                selection_stability(self.selection_mask, frame), 4
            )
            d["mean_channels_active"] = round(
                float(self.selection_mask.sum(axis=0).mean()), 2
            )
        if self.config.apply_interaction:
            m = spread_matrix(self.n_channels, self.config.interaction_decay_db)
            d["effective_channels"] = round(effective_channels(m), 2)
        return d


def simulate(
    x: np.ndarray,
    sample_rate: int,
    config: SimulatorConfig | None = None,
) -> SimulationResult:
    """Run audio through the simulated implant.

    Parameters
    ----------
    x:
        Mono audio. Stereo input is an error - a single implant receives one
        signal, and silently mixing to mono would hide a caller's mistake.
    sample_rate:
        Sample rate in Hz.
    config:
        Device parameters; defaults to a generic device.

    Returns
    -------
    SimulationResult
        Audio plus every intermediate. The audio is **not** loudness-normalised;
        pass it through :func:`prelude.audio.loudness.prepare_for_playback`
        before any human hears it.
    """
    config = config or SimulatorConfig()
    x = np.asarray(x, dtype=float)

    if x.ndim != 1:
        raise ValueError(
            f"expected mono audio, got shape {x.shape}. Mix to mono explicitly - "
            f"which ear this represents is a decision for the caller."
        )

    edges = np.asarray(config.band_edges, dtype=float) if config.band_edges else None
    fb = design_filterbank(
        sample_rate=sample_rate,
        n_channels=config.n_channels,
        low_freq=config.low_freq,
        high_freq=config.high_freq,
        spacing=config.spacing,
        edges=edges,
    )

    # Where the surviving electrodes physically sit. With nothing deactivated
    # this is the analysis bank itself and the two coincide, which is the
    # ordinary case. With a dead contact they diverge, and the divergence is
    # the point: the processor reallocates the frequency range across the live
    # contacts, but it cannot move them, so a band is delivered at a place that
    # does not correspond to its frequency.
    place_fb = fb
    if config.deactivated_electrodes:
        full = design_filterbank(
            sample_rate=sample_rate,
            n_channels=config.n_electrodes,
            low_freq=config.low_freq,
            high_freq=config.high_freq,
            spacing=config.spacing,
        )
        live = _surviving_band_indices(config)
        place_fb = Filterbank(
            sos=full.sos[live],
            center_freqs=full.center_freqs[live],
            edges=full.edges[live],
            sample_rate=full.sample_rate,
        )

    bands = fb.apply(x)
    env = extract_envelope(
        bands,
        sample_rate,
        method=config.envelope_method,
        cutoff_hz=config.envelope_cutoff_hz,
    )

    mask = None
    stim = env
    if config.apply_selection:
        frame = max(1, int(sample_rate / config.stimulation_rate_hz))
        stim, mask = select_n_of_m(stim, config.n_selected, frame)

    loudness_map = LoudnessMap.uniform(fb.n_channels, config.dynamic_range_db)
    reference = float(env.max()) if env.size else 1.0

    if config.apply_mapping:
        stim = apply_loudness_map(stim, loudness_map, reference=reference)

    if config.apply_interaction:
        matrix = spread_matrix(fb.n_channels, config.interaction_decay_db)
        stim = apply_interaction(stim, matrix)

    electrodogram = stim.copy()

    # levels_to_amplitude, not invert_loudness_map: the compression must survive
    # into the audio, since the narrow electrical dynamic range is the constraint
    # being simulated. Inverting the map would hand it back.
    acoustic = (
        levels_to_amplitude(stim, loudness_map, reference=reference)
        if config.apply_mapping
        else stim
    )

    rng = np.random.default_rng(config.seed)
    audio = resynthesise(
        acoustic,
        place_fb,
        carrier=config.carrier,
        rng=rng,
        rate_hz=config.stimulation_rate_hz,
        synchronization=config.synchronization,
    )

    return SimulationResult(
        audio=audio,
        sample_rate=sample_rate,
        config=config,
        bands=bands,
        envelopes=env,
        electrodogram=electrodogram,
        selection_mask=mask,
        filterbank=fb,
    )
