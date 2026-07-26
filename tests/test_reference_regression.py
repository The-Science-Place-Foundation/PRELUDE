"""Validation against an external reference simulator.

These tests skip when no fixtures are present, so a clean checkout passes. See
``tests/fixtures/README.md`` for how to supply them.

Passing this suite establishes *structural* correctness — that PRELUDE performs
the same transformation as an established implementation. It does not establish
that the simulation matches any particular listener's percept, which is a
separate, perceptual question requiring human validation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from prelude.audio import load_audio
from prelude.ci_sim import design_filterbank, extract_envelope, simulate
from prelude.config import load_simulator_config

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_sets() -> list[tuple[str, Path, Path, Path]]:
    out = []
    for cfg in sorted(FIXTURES.glob("*.yaml")):
        stem = cfg.stem
        source = FIXTURES / f"{stem}_source.wav"
        reference = FIXTURES / f"{stem}_reference.wav"
        if source.exists() and reference.exists():
            out.append((stem, source, reference, cfg))
    return out


FIXTURE_SETS = _fixture_sets()

pytestmark = pytest.mark.skipif(
    not FIXTURE_SETS,
    reason="no reference fixtures present; see tests/fixtures/README.md",
)


def envelope_correlation(
    a: np.ndarray, b: np.ndarray, sample_rate: int, n_bands: int = 16
) -> float:
    """Mean per-band envelope correlation between two signals.

    Compares in the domain that matters: a cochlear implant transmits envelopes,
    so two signals with near-identical envelopes sound nearly the same through
    one regardless of how different their waveforms look.
    """
    n = min(len(a), len(b))
    fb = design_filterbank(sample_rate, n_bands, 300, min(7500, sample_rate / 2 * 0.9))
    ea = extract_envelope(fb.apply(a[:n]), sample_rate, cutoff_hz=50)
    eb = extract_envelope(fb.apply(b[:n]), sample_rate, cutoff_hz=50)

    cors = [
        np.corrcoef(x, y)[0, 1]
        for x, y in zip(ea, eb, strict=True)
        if x.std() > 1e-9 and y.std() > 1e-9
    ]
    return float(np.mean(cors)) if cors else float("nan")


@pytest.mark.parametrize("name,source,reference,config_path", FIXTURE_SETS,
                         ids=[s[0] for s in FIXTURE_SETS])
def test_matches_reference_envelopes(name, source, reference, config_path):
    """PRELUDE's output should track the reference tool's envelopes closely."""
    config = load_simulator_config(config_path)
    ref = load_audio(reference)

    src = load_audio(source, target_rate=ref.sample_rate)
    result = simulate(src.samples, src.sample_rate, config)

    corr = envelope_correlation(result.audio, ref.samples, ref.sample_rate)
    assert corr > 0.7, (
        f"{name}: envelope correlation with the reference is only {corr:.3f}. "
        f"The two simulators are doing materially different things — check band "
        f"spacing, envelope cutoff, and whether the reference applies n-of-m."
    )


@pytest.mark.parametrize("name,source,reference,config_path", FIXTURE_SETS,
                         ids=[s[0] for s in FIXTURE_SETS])
def test_matches_reference_spectrum(name, source, reference, config_path):
    """Long-term average spectra should agree in shape."""
    config = load_simulator_config(config_path)
    ref = load_audio(reference)
    src = load_audio(source, target_rate=ref.sample_rate)
    result = simulate(src.samples, src.sample_rate, config)

    n = min(len(result.audio), len(ref.samples))

    def lta_spectrum(x):
        spec = np.abs(np.fft.rfft(x[:n]))
        spec = spec / (spec.sum() + 1e-12)
        # Coarse bins; fine structure differs by construction between carriers.
        return spec[: len(spec) // 1].reshape(-1, 64).mean(axis=1) if len(spec) >= 64 else spec

    a, b = lta_spectrum(result.audio), lta_spectrum(ref.samples)
    m = min(len(a), len(b))
    corr = float(np.corrcoef(a[:m], b[:m])[0, 1])
    assert corr > 0.8, f"{name}: spectral shape correlation only {corr:.3f}"


@pytest.mark.skipif(len(FIXTURE_SETS) < 2, reason="need two fixture sets to compare a delta")
def test_reproduces_difference_between_configs():
    """Reproducing a *delta* between two settings is a stronger test than an absolute.

    If the reference tool produces more-degraded output under configuration B
    than configuration A, PRELUDE must agree on the direction. This cancels
    implementation details irrelevant to the comparison.
    """
    results = []
    for name, source, reference, config_path in FIXTURE_SETS[:2]:
        config = load_simulator_config(config_path)
        ref = load_audio(reference)
        src = load_audio(source, target_rate=ref.sample_rate)
        ours = simulate(src.samples, src.sample_rate, config)
        results.append(
            (
                name,
                envelope_correlation(ref.samples, src.samples, ref.sample_rate),
                envelope_correlation(ours.audio, src.samples, ref.sample_rate),
            )
        )

    (n0, ref0, our0), (n1, ref1, our1) = results
    assert np.sign(ref0 - ref1) == np.sign(our0 - our1), (
        f"reference says {n0} is {'better' if ref0 > ref1 else 'worse'} than {n1}, "
        f"but PRELUDE says the opposite "
        f"(reference {ref0:.3f} vs {ref1:.3f}; ours {our0:.3f} vs {our1:.3f})"
    )
