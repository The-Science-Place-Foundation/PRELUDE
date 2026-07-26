"""Audio input and output.

All file access goes through this module. Ad-hoc conversion at call sites is how
a units mismatch - integer sample values compared against floating-point audio -
went unnoticed in this project's predecessor long enough to be nearly reported as
a result. Centralising the boundary makes the convention enforceable.

Convention: audio is float64 in the range [-1, 1], mono unless explicitly stated,
and sample rate always travels with the signal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal


@dataclass(frozen=True)
class Audio:
    """A signal and its sample rate.

    Keeping the two together prevents the most common class of audio bug, where a
    signal is processed at a rate it was not sampled at.
    """

    samples: np.ndarray
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return self.samples.shape[-1] / self.sample_rate

    @property
    def is_mono(self) -> bool:
        return self.samples.ndim == 1

    def to_mono(self) -> "Audio":
        if self.is_mono:
            return self
        return Audio(self.samples.mean(axis=0), self.sample_rate)

    def resample(self, target_rate: int) -> "Audio":
        if target_rate == self.sample_rate:
            return self
        g = np.gcd(int(target_rate), int(self.sample_rate))
        return Audio(
            signal.resample_poly(
                self.samples, target_rate // g, self.sample_rate // g, axis=-1
            ),
            target_rate,
        )


def load_audio(
    path: str | Path,
    target_rate: int | None = None,
    mono: bool = True,
) -> Audio:
    """Load an audio file as float64 in [-1, 1].

    Parameters
    ----------
    path:
        File to read. Any format libsndfile supports.
    target_rate:
        Resample to this rate if given.
    mono:
        Mix down to mono. Channels are averaged.
    """
    path = Path(path)
    samples, rate = sf.read(str(path), dtype="float64", always_2d=True)
    samples = samples.T  # soundfile gives (frames, channels)

    audio = Audio(samples, int(rate))
    if mono:
        audio = Audio(samples.mean(axis=0), int(rate))
    if target_rate is not None:
        audio = audio.resample(target_rate)
    return audio


def save_audio(
    path: str | Path,
    audio: Audio,
    subtype: str = "PCM_16",
    metadata: dict | None = None,
) -> None:
    """Write audio, optionally with a provenance sidecar.

    When ``metadata`` is given, a ``.json`` file is written alongside recording
    how the artifact was produced. Doing this consistently is what makes results
    reproducible months later; its absence is why the predecessor project's
    parameter sweeps can no longer be interpreted.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = audio.samples
    peak = float(np.abs(data).max()) if data.size else 0.0
    if peak > 1.0:
        raise ValueError(
            f"signal peaks at {peak:.3f}, above full scale; it would clip on "
            f"write. Normalise it first - see prelude.audio.loudness."
        )

    sf.write(str(path), data.T if data.ndim > 1 else data, audio.sample_rate, subtype=subtype)

    if metadata is not None:
        sidecar = dict(metadata)
        sidecar.setdefault("sample_rate", audio.sample_rate)
        sidecar.setdefault("duration_s", round(audio.duration_s, 4))
        path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2, default=str))


def file_hash(path: str | Path) -> str:
    """SHA-256 of a file's contents, truncated. For provenance records."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
