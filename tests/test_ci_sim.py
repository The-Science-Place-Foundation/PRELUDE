# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Tests for the CI simulation pipeline.

Several of these encode defects found in this project's predecessor. They are
regression tests against specific, real mistakes rather than hypothetical ones -
see ``docs/03-PRIOR-ART.md``.
"""

from __future__ import annotations

import numpy as np
import pytest

from prelude.ci_sim import (
    LoudnessMap,
    SimulatorConfig,
    apply_interaction,
    apply_loudness_map,
    design_filterbank,
    effective_channels,
    envelope_modulation_depth,
    erb_space,
    extract_envelope,
    greenwood_frequency,
    greenwood_position,
    invert_loudness_map,
    levels_to_amplitude,
    pulse_carrier,
    resynthesise,
    select_n_of_m,
    simulate,
    spread_matrix,
)

SR = 20000  # native rate of the archived reference simulator; fits a 8.5 kHz ceiling


@pytest.fixture
def speech_like():
    """A harmonic signal with an amplitude envelope, standing in for speech."""
    rng = np.random.default_rng(0)
    t = np.arange(SR) / SR
    f0 = 120.0
    sig = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 12))
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
    return (sig * env + 0.01 * rng.standard_normal(len(t))) / 4.0


class TestFilterbank:
    def test_rejects_band_above_nyquist(self):
        """The predecessor silently dropped 10 of 21 channels this way.

        A nominally 21-channel bank ran with 11 because band edges above Nyquist
        hit a `continue`. Failing loudly is the entire point of this test.
        """
        with pytest.raises(ValueError, match="Nyquist"):
            design_filterbank(sample_rate=16000, n_channels=21, low_freq=700, high_freq=16000)

    def test_all_channels_survive(self):
        for n in (8, 12, 16, 22):
            fb = design_filterbank(SR, n, 300, 7500)
            assert fb.n_channels == n
            assert fb.sos.shape[0] == n

    def test_greenwood_spacing_is_logarithmic(self):
        """Band widths must grow towards the base, as in the cochlea."""
        fb = design_filterbank(SR, 12, 300, 7500, spacing="greenwood")
        widths = fb.edges[:, 1] - fb.edges[:, 0]
        assert np.all(np.diff(widths) > 0), "bands should widen with frequency"

    def test_greenwood_roundtrip(self):
        f = np.array([200.0, 1000.0, 4000.0])
        assert np.allclose(greenwood_frequency(greenwood_position(f)), f)

    def test_erb_spacing_ordered_and_in_range(self):
        cf = erb_space(300, 7500, 16)
        assert len(cf) == 16
        assert np.all(np.diff(cf) > 0)
        assert 250 < cf[0] < 400 and cf[-1] < 7500

    def test_bands_are_contiguous(self):
        fb = design_filterbank(SR, 10, 300, 7500)
        assert np.allclose(fb.edges[:-1, 1], fb.edges[1:, 0])

    def test_explicit_allocation_table(self):
        edges = np.array([[300, 600], [600, 1200], [1200, 2400], [2400, 4800]], dtype=float)
        fb = design_filterbank(SR, 4, spacing="table", edges=edges)
        assert np.allclose(fb.edges, edges)

    def test_apply_shape(self, speech_like):
        fb = design_filterbank(SR, 8, 300, 7500)
        bands = fb.apply(speech_like)
        assert bands.shape == (8, len(speech_like))

    def test_rejects_stereo(self, speech_like):
        fb = design_filterbank(SR, 8, 300, 7500)
        with pytest.raises(ValueError, match="mono"):
            fb.apply(np.stack([speech_like, speech_like]))


class TestEnvelope:
    def test_envelope_is_nonnegative_and_smooth(self, speech_like):
        fb = design_filterbank(SR, 8, 300, 7500)
        env = extract_envelope(fb.apply(speech_like), SR, cutoff_hz=300)
        assert env.shape == (8, len(speech_like))
        assert np.all(env >= 0)

    def test_envelope_discards_fine_structure(self, speech_like):
        """The envelope must not simply reproduce the band signal.

        The predecessor half-wave rectified each band and called the result an
        envelope, which preserves exactly the fine structure a real implant
        destroys. A true envelope has far less high-frequency content.
        """
        fb = design_filterbank(SR, 8, 1000, 7000)
        bands = fb.apply(speech_like)
        env = extract_envelope(bands, SR, cutoff_hz=200)

        def hf_energy(x):
            spec = np.abs(np.fft.rfft(x, axis=-1))
            freqs = np.fft.rfftfreq(x.shape[-1], 1 / SR)
            hi = freqs > 800
            return (spec[:, hi] ** 2).sum() / (spec**2).sum()

        assert hf_energy(env) < 0.1 * hf_energy(bands)

    def test_rectify_requires_lowpass(self):
        with pytest.raises(ValueError, match="does not produce an envelope"):
            extract_envelope(np.ones((2, 100)), SR, method="rectify", cutoff_hz=None)

    def test_modulation_depth_bounds(self):
        t = np.arange(SR) / SR
        steady = np.ones((1, SR))
        modulated = (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t))[None, :]
        assert envelope_modulation_depth(steady)[0] < 1e-6
        assert envelope_modulation_depth(modulated)[0] > 0.9


class TestSelection:
    def test_keeps_exactly_n_channels(self):
        rng = np.random.default_rng(1)
        env = np.abs(rng.standard_normal((22, 4000)))
        _, mask = select_n_of_m(env, n_selected=8, frame_samples=100)
        per_frame = mask[:, ::100].sum(axis=0)
        assert np.all(per_frame == 8)

    def test_selects_the_strongest(self):
        env = np.zeros((5, 100))
        env[2] = 1.0
        env[4] = 0.5
        selected, mask = select_n_of_m(env, n_selected=2, frame_samples=100)
        assert mask[2].all() and mask[4].all()
        assert not mask[0].any()
        assert np.allclose(selected[2], 1.0)

    def test_cis_passes_everything(self):
        env = np.abs(np.random.default_rng(2).standard_normal((8, 500)))
        selected, mask = select_n_of_m(env, n_selected=8, frame_samples=50)
        assert mask.all()
        assert np.allclose(selected, env)

    def test_rejects_n_greater_than_m(self):
        with pytest.raises(ValueError, match="between 1 and"):
            select_n_of_m(np.ones((4, 100)), n_selected=5, frame_samples=10)


class TestLoudnessMapping:
    def test_compresses_into_dynamic_range(self):
        """A 60 dB acoustic range must land inside the electrical window."""
        lm = LoudnessMap.uniform(4, dynamic_range_db=12.0)
        env = np.tile(np.array([1.0, 0.1, 0.01, 0.001])[:, None], (1, 10))
        out = apply_loudness_map(env, lm, reference=1.0)
        active = out[out > 0]
        span_db = 20 * np.log10(active.max() / active.min())
        assert span_db <= 12.5

    def test_compression_survives_into_the_audio(self):
        """The narrow electrical dynamic range must reach the listener.

        Regression test for a real defect. The pipeline used to compress into
        [T, C] and then invert the map before resynthesis, restoring the original
        dynamic range to floating-point precision. The electrodogram showed the
        constraint; the audio did not. Since that constraint is the defining
        limitation of electric hearing, the simulation was quietly understating
        the very thing it exists to demonstrate.
        """
        lm = LoudnessMap.uniform(4, dynamic_range_db=12.0)
        env = np.tile(np.logspace(-3, 0, 200), (4, 1))  # 60 dB span
        out = levels_to_amplitude(apply_loudness_map(env, lm, reference=1.0), lm)
        audible = out[0][out[0] > 0]
        out_db = 20 * np.log10(audible.max() / audible.min())
        assert out_db < 40, f"output span {out_db:.1f} dB - compression was undone"
        assert out_db > 5, f"output span {out_db:.1f} dB - over-compressed to nothing"

    def test_invert_is_a_true_inverse(self):
        """invert_loudness_map stays exact - it is for analysis, not resynthesis."""
        lm = LoudnessMap.uniform(3, dynamic_range_db=12.0)
        env = np.tile(np.logspace(-2, 0, 100), (3, 1))
        back = invert_loudness_map(apply_loudness_map(env, lm, reference=1.0), lm, 1.0)
        ok = env[0] > 10 ** (lm.input_floor_db / 20)
        assert np.allclose(back[0][ok], env[0][ok], rtol=1e-9)

    def test_roundtrip_is_monotonic(self):
        lm = LoudnessMap.uniform(3, dynamic_range_db=12.0)
        env = np.tile(np.linspace(0.01, 1.0, 50), (3, 1))
        back = invert_loudness_map(apply_loudness_map(env, lm, reference=1.0), lm, reference=1.0)
        assert np.all(np.diff(back[0]) >= -1e-9)

    def test_subthreshold_maps_to_zero(self):
        lm = LoudnessMap.uniform(2, dynamic_range_db=12.0, input_floor_db=-40.0)
        env = np.array([[1.0], [1e-6]])
        out = apply_loudness_map(env, lm, reference=1.0)
        assert out[0, 0] > 0 and out[1, 0] == 0

    def test_channel_count_mismatch_raises(self):
        lm = LoudnessMap.uniform(4)
        with pytest.raises(ValueError, match="channels"):
            apply_loudness_map(np.ones((3, 10)), lm)


class TestInteraction:
    def test_spread_reduces_effective_channels(self):
        tight = spread_matrix(22, decay_db_per_channel=40.0)
        loose = spread_matrix(22, decay_db_per_channel=3.0)
        assert effective_channels(tight) > effective_channels(loose)
        assert effective_channels(loose) < 12

    def test_spread_conserves_energy(self):
        m = spread_matrix(12, 8.0, normalise=True)
        assert np.allclose(m.sum(axis=0), 1.0)

    def test_smearing_spreads_a_single_channel(self):
        levels = np.zeros((9, 5))
        levels[4] = 1.0
        out = apply_interaction(levels, spread_matrix(9, 6.0))
        assert out[3, 0] > 0 and out[5, 0] > 0
        assert out[4, 0] == out[:, 0].max()


class TestPipeline:
    def test_end_to_end_shape_and_finiteness(self, speech_like):
        result = simulate(speech_like, SR, SimulatorConfig(n_channels=12, n_selected=6, seed=0))
        assert result.audio.shape == speech_like.shape
        assert np.all(np.isfinite(result.audio))
        assert result.electrodogram.shape[0] == 12

    def test_reproducible_with_seed(self, speech_like):
        cfg = SimulatorConfig(n_channels=8, n_selected=8, seed=42)
        a = simulate(speech_like, SR, cfg).audio
        b = simulate(speech_like, SR, cfg).audio
        assert np.allclose(a, b)

    def test_fewer_channels_loses_more_information(self, speech_like):
        """Reducing channel count must degrade envelope fidelity.

        This is the single most robust qualitative fact about CI simulation
        (Shannon et al., 1995) and a simulator that fails it is not modelling an
        implant.
        """

        def fidelity(n):
            cfg = SimulatorConfig(
                n_channels=n, n_selected=n, seed=0,
                apply_selection=False, apply_interaction=False,
            )
            r = simulate(speech_like, SR, cfg)
            ref = design_filterbank(SR, 16, 300, 7500).apply(speech_like)
            out = design_filterbank(SR, 16, 300, 7500).apply(r.audio)
            re_ = extract_envelope(ref, SR, cutoff_hz=50)
            oe = extract_envelope(out, SR, cutoff_hz=50)
            return float(np.mean([
                np.corrcoef(a, b)[0, 1]
                for a, b in zip(re_, oe, strict=True)
                if a.std() > 1e-9 and b.std() > 1e-9
            ]))

        assert fidelity(16) > fidelity(4)

    def test_config_hash_is_stable_and_sensitive(self):
        a = SimulatorConfig(n_channels=12)
        b = SimulatorConfig(n_channels=12)
        c = SimulatorConfig(n_channels=13)
        assert a.hash() == b.hash()
        assert a.hash() != c.hash()

    def test_rejects_stereo(self):
        with pytest.raises(ValueError, match="mono"):
            simulate(np.zeros((2, 1000)), SR)

    def test_rejects_n_selected_above_n_channels(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            SimulatorConfig(n_channels=8, n_selected=12)

    def test_diagnostics_present(self, speech_like):
        r = simulate(speech_like, SR, SimulatorConfig(n_channels=12, n_selected=4, seed=0))
        d = r.diagnostics()
        assert "config_hash" in d
        assert 0.0 <= d["selection_stability"] <= 1.0
        assert d["mean_channels_active"] == pytest.approx(4.0, abs=0.5)


class TestResynthesis:
    def test_output_is_band_limited(self):
        """Carriers must stay inside their bands, not leak broadband."""
        fb = design_filterbank(SR, 6, 300, 4000)
        env = np.ones((6, SR)) * 0.1
        out = resynthesise(env, fb, carrier="noise", rng=np.random.default_rng(0))
        spec = np.abs(np.fft.rfft(out))
        freqs = np.fft.rfftfreq(len(out), 1 / SR)
        above = (spec[freqs > 6000] ** 2).sum()
        inband = (spec[(freqs > 300) & (freqs < 4000)] ** 2).sum()
        assert above < 0.01 * inband

    def test_tone_carrier_runs(self):
        fb = design_filterbank(SR, 4, 300, 4000)
        out = resynthesise(np.ones((4, 1000)) * 0.1, fb, carrier="tone")
        assert np.all(np.isfinite(out))

    def test_unknown_carrier_raises(self):
        fb = design_filterbank(SR, 4, 300, 4000)
        with pytest.raises(ValueError, match="unknown carrier"):
            resynthesise(np.ones((4, 100)), fb, carrier="square")

    def test_pulse_carrier_requires_rate(self):
        fb = design_filterbank(SR, 4, 300, 4000)
        with pytest.raises(ValueError, match="requires rate_hz"):
            resynthesise(np.ones((4, 100)), fb, carrier="pulse")


class TestPulseCarrier:
    """Pulsatile stimulation - what real devices actually deliver."""

    def test_pulse_count_matches_stimulation_rate(self):
        rate, dur = 900.0, 1.0
        p = pulse_carrier(4, int(SR * dur), rate, SR, synchronization=1.0)
        for ch in p:
            assert abs(np.count_nonzero(ch) - rate * dur) / (rate * dur) < 0.05

    def test_channels_are_interleaved(self):
        """Adjacent electrodes must not fire simultaneously.

        Simultaneous stimulation sums in the cochlea; avoiding it is what the
        "interleaved" in Continuous Interleaved Sampling refers to.
        """
        p = pulse_carrier(8, SR, 900.0, SR, synchronization=1.0)
        first = [np.flatnonzero(ch)[0] for ch in p]
        assert len(set(first)) == len(first), "channels fire at the same instant"

    def test_synchronization_zero_is_noise_like(self):
        """At sync 0 the carrier degenerates to noise, per the physiology."""
        pulsed = pulse_carrier(4, SR, 900.0, SR, synchronization=1.0,
                               rng=np.random.default_rng(0))
        noisy = pulse_carrier(4, SR, 900.0, SR, synchronization=0.0,
                              rng=np.random.default_rng(0))
        assert np.count_nonzero(pulsed) < 0.1 * pulsed.size
        assert np.count_nonzero(noisy) > 0.9 * noisy.size

    def test_charge_is_approximately_balanced(self):
        """Alternating pulse signs approximate the charge balance devices require."""
        p = pulse_carrier(4, SR, 900.0, SR, synchronization=1.0)
        for ch in p:
            assert abs(ch.sum()) <= 1.0

    def test_rejects_rate_above_sample_rate(self):
        with pytest.raises(ValueError, match="too high for sample rate"):
            pulse_carrier(4, 1000, 20000.0, SR)

    def test_rejects_out_of_range_synchronization(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            pulse_carrier(4, 1000, 900.0, SR, synchronization=1.5)

    def test_pipeline_accepts_pulse_carrier(self, speech_like):
        r = simulate(speech_like, SR, SimulatorConfig(
            n_channels=12, n_selected=12, carrier="pulse",
            stimulation_rate_hz=900.0, synchronization=1.0, seed=0))
        assert np.all(np.isfinite(r.audio))
        assert r.audio.shape == speech_like.shape

    def test_config_rejects_bad_synchronization(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            SimulatorConfig(synchronization=2.0)


class TestElectrodeDeactivation:
    """A dead contact is a place mismatch, not just one channel fewer.

    A fitting program reallocates the frequency range across the surviving
    electrodes, so the processor still analyses the full band. What it cannot
    do is move the electrodes: the range that used to go to the dead contact is
    now delivered by its neighbours, at *their* place in the cochlea. Modelling
    deactivation as a lower channel count reproduces the lost resolution and
    none of the displacement.
    """

    def test_electrode_one_is_the_highest_frequency_band(self):
        """Cochlear numbers electrode 1 at the BASE.

        Filterbanks are indexed low to high, so the two orderings are mirror
        images. Reading one as the other is silent and total: it turns a dead
        7 kHz contact into a dead 300 Hz one and the output still sounds like
        a cochlear implant.
        """
        from prelude.ci_sim.pipeline import electrode_to_band_index
        assert electrode_to_band_index(1, 22) == 21
        assert electrode_to_band_index(22, 22) == 0
        assert electrode_to_band_index(1, 22, "apical_first") == 0
        assert electrode_to_band_index(22, 22, "apical_first") == 21

    def test_a_dead_contact_displaces_the_frequency_place_map(self, speech_like):
        """The carriers must not sit at the analysis band centres."""
        from prelude.ci_sim.filterbank import design_filterbank
        from prelude.ci_sim.pipeline import _surviving_band_indices
        cfg = SimulatorConfig(n_channels=21, n_selected=8, n_electrodes=22,
                              deactivated_electrodes=(2,), low_freq=300.0,
                              high_freq=7500.0)
        analysis = design_filterbank(sample_rate=16000, n_channels=21,
                                     low_freq=300.0, high_freq=7500.0)
        full = design_filterbank(sample_rate=16000, n_channels=22,
                                 low_freq=300.0, high_freq=7500.0)
        places = full.center_freqs[_surviving_band_indices(cfg)]
        assert not np.allclose(analysis.center_freqs, places), (
            "analysis and delivery must diverge, or no mismatch is modelled")
        # The displacement is on the side the contact died, and is real but
        # bounded - a couple of semitones, not an octave.
        shift = 12 * np.log2(places / analysis.center_freqs)
        assert 0.5 < np.abs(shift).max() < 6.0

    def test_no_deactivation_leaves_delivery_at_the_analysis_bands(self, speech_like):
        """The ordinary case must be untouched by this feature."""
        from prelude.ci_sim.filterbank import design_filterbank
        cfg = SimulatorConfig(n_channels=22, n_selected=8, high_freq=7500.0)
        assert cfg.deactivated_electrodes == ()
        fb = design_filterbank(sample_rate=16000, n_channels=22,
                               low_freq=cfg.low_freq, high_freq=cfg.high_freq)
        r = simulate(speech_like, 16000, cfg)
        assert r.audio.shape == speech_like.shape
        assert fb.n_channels == 22

    def test_a_basal_and_an_apical_dead_contact_are_not_the_same_simulation(
            self, speech_like):
        """The distinction the numbering ambiguity turns on.

        If these produced similar audio, resolving whether the dead contact is
        electrode 2 or electrode 21 would not matter. They do not.
        """
        basal = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=21, n_selected=8, n_electrodes=22,
            deactivated_electrodes=(2,), high_freq=7500.0, seed=0))
        apical = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=21, n_selected=8, n_electrodes=22,
            deactivated_electrodes=(21,), high_freq=7500.0, seed=0))
        assert not np.allclose(basal.audio, apical.audio)

    def test_config_hash_changes_with_the_dead_contact(self):
        """Provenance: two runs differing only here must be distinguishable."""
        a = SimulatorConfig(n_channels=21, n_electrodes=22,
                            deactivated_electrodes=(2,))
        b = SimulatorConfig(n_channels=21, n_electrodes=22,
                            deactivated_electrodes=(21,))
        assert a.hash() != b.hash()

    def test_deactivation_without_an_array_size_is_refused(self):
        with pytest.raises(ValueError, match="n_electrodes"):
            SimulatorConfig(n_channels=21, deactivated_electrodes=(2,))

    def test_channel_count_must_match_the_surviving_contacts(self):
        """Guards the specific error this replaced: modelling 22 minus one
        dead contact as an arbitrary smaller number of evenly spaced channels."""
        with pytest.raises(ValueError, match="surviving"):
            SimulatorConfig(n_channels=19, n_electrodes=22,
                            deactivated_electrodes=(2,))

    def test_electrode_numbers_are_one_based_like_a_clinic_printout(self):
        with pytest.raises(ValueError, match="1-based"):
            SimulatorConfig(n_channels=21, n_electrodes=22,
                            deactivated_electrodes=(0,))


class TestMeasuredPlaceMap:
    """A measured frequency-place map moves the carriers, not the analysis.

    The analysis bands are what the processor does to the input. The place map
    is where the listener's device puts the result. Warping the analysis
    instead would model a different device rather than a different ear.
    """

    KNOTS = ((500.0, 396.9), (1500.0, 1542.2), (3000.0, 2378.4))

    def test_it_interpolates_between_knots_and_holds_flat_outside(self):
        from prelude.ci_sim.pipeline import warp_through_place_map
        got = warp_through_place_map(
            np.array([500.0, 1500.0, 3000.0]), self.KNOTS)
        assert got == pytest.approx([396.9, 1542.2, 2378.4], rel=1e-6)
        # Between knots, monotonic and bounded by them.
        mid = warp_through_place_map(np.array([800.0]), self.KNOTS)[0]
        assert 396.9 < mid < 1542.2
        # Outside, the outermost SHIFT continues - the frequency is not clamped.
        low = warp_through_place_map(np.array([250.0]), self.KNOTS)[0]
        assert low == pytest.approx(250.0 * (396.9 / 500.0), rel=1e-6)
        high = warp_through_place_map(np.array([6000.0]), self.KNOTS)[0]
        assert high == pytest.approx(6000.0 * (2378.4 / 3000.0), rel=1e-6)

    def test_no_map_is_the_identity(self):
        from prelude.ci_sim.pipeline import warp_through_place_map
        f = np.array([300.0, 1000.0, 4000.0])
        assert warp_through_place_map(f, ()) == pytest.approx(f)

    def test_a_map_changes_the_audio(self, speech_like):
        plain = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=8, n_selected=8, high_freq=7000.0, seed=0))
        warped = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=8, n_selected=8, high_freq=7000.0, seed=0,
            place_map_hz=self.KNOTS))
        assert not np.allclose(plain.audio, warped.audio)

    def test_a_downward_map_moves_output_energy_down(self, speech_like):
        """The listener's measured map is downward, so the output should be."""
        def centroid(x):
            X = np.abs(np.fft.rfft(x))
            f = np.fft.rfftfreq(len(x), 1 / 16000)
            return float((f * X).sum() / X.sum())
        plain = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=8, n_selected=8, high_freq=7000.0, seed=0))
        warped = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=8, n_selected=8, high_freq=7000.0, seed=0,
            place_map_hz=self.KNOTS))
        assert centroid(warped.audio) < centroid(plain.audio)

    def test_the_electrodogram_is_untouched_by_the_map(self, speech_like):
        """The map is about where stimulation is HEARD, not what is sent.

        Channel selection and levels happen before resynthesis, so warping the
        carriers must not disturb them - otherwise the map would be silently
        changing the device rather than the ear.
        """
        base = dict(n_channels=8, n_selected=4, high_freq=7000.0, seed=0)
        plain = simulate(speech_like, 16000, SimulatorConfig(**base))
        warped = simulate(speech_like, 16000,
                          SimulatorConfig(**base, place_map_hz=self.KNOTS))
        assert np.allclose(plain.electrodogram, warped.electrodogram)

    def test_a_map_that_would_cross_nyquist_is_refused(self, speech_like):
        upward = ((500.0, 2000.0), (3000.0, 12000.0))
        with pytest.raises(ValueError, match="Nyquist"):
            simulate(speech_like, 16000, SimulatorConfig(
                n_channels=8, n_selected=8, high_freq=7000.0,
                place_map_hz=upward))

    def test_the_map_takes_precedence_over_modelled_deactivation(self, speech_like):
        """Both describe the same displacement; composing would double-count.

        A measured map comes from sending a tone to the real device and asking
        where it landed, so it already contains that device's allocation, its
        electrode positions and whichever contacts are off.
        """
        with_dead = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=21, n_selected=8, n_electrodes=22,
            deactivated_electrodes=(2,), high_freq=7000.0, seed=0,
            place_map_hz=self.KNOTS))
        without = simulate(speech_like, 16000, SimulatorConfig(
            n_channels=21, n_selected=8, high_freq=7000.0, seed=0,
            place_map_hz=self.KNOTS))
        # Channel count and selection still differ in general, but the carrier
        # placement is governed by the map alone, so the two agree.
        assert np.allclose(with_dead.audio, without.audio)

    def test_config_hash_covers_the_map(self):
        a = SimulatorConfig(n_channels=8, place_map_hz=self.KNOTS)
        b = SimulatorConfig(n_channels=8)
        assert a.hash() != b.hash()
