# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Dichotic presentation: different audio to each ear from one stereo file.

A bimodal listener whose devices stream as a stereo pair can receive different
content in each ear from an ordinary two-channel file. No special transport is
needed - the left channel reaches one device and the right the other.

This makes the central comparison direct. The implanted ear hears a source
signal and produces the electric percept; the contralateral ear hears a candidate
simulation of that percept, acoustically. The listener judges whether the two
match, without removing a device and without holding one percept in memory while
the other is presented.

Three presentation modes are provided, because simultaneity is not obviously the
right choice - see :class:`PresentationMode`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from ..audio.loudness import DEFAULT_TARGET_LUFS, prepare_for_playback


class Ear(str, Enum):
    LEFT = "left"
    RIGHT = "right"

    @property
    def channel_index(self) -> int:
        return 0 if self is Ear.LEFT else 1

    @property
    def other(self) -> Ear:
        return Ear.RIGHT if self is Ear.LEFT else Ear.LEFT


class PresentationMode(str, Enum):
    """How the two signals are laid out in time.

    The choice is not obvious and should be treated as an empirical question for
    each listener rather than settled by assumption.
    """

    #: Both ears at once. Fastest, and imposes no memory load.
    #:
    #: **Carries a real risk.** Bimodal listeners frequently report that when
    #: both devices carry related material the percepts fuse into a single
    #: natural-seeming whole. That fusion is a genuine benefit in daily life and
    #: a problem here: a listener asked to compare two signals that their brain
    #: has already merged may be reporting on the merged percept rather than
    #: comparing its parts. Since the two signals here are temporally aligned
    #: and spectrally related by construction, fusion is likely.
    SIMULTANEOUS = "simultaneous"

    #: Rapid alternation between ears, a short segment at a time.
    #:
    #: Usually the best compromise. Only one ear carries signal at any instant,
    #: so there is nothing to fuse, while the gap is short enough that
    #: comparison does not depend on memory. This is the recommended default.
    ALTERNATING = "alternating"

    #: One ear in full, a silent gap, then the other.
    #:
    #: Cleanest isolation and the highest memory load. Appropriate for long or
    #: musically complex material where alternation would chop up the phrase
    #: being judged.
    SEQUENTIAL = "sequential"


@dataclass(frozen=True)
class EarAssignment:
    """Which ear carries which device.

    There is deliberately no default. Getting this backwards would present the
    simulation to the implanted ear and the source to the acoustic ear, which
    silently inverts the experiment and produces data that looks perfectly
    normal. It must be stated explicitly and recorded with every session.
    """

    implant_ear: Ear

    @property
    def acoustic_ear(self) -> Ear:
        return self.implant_ear.other

    def describe(self) -> str:
        return (
            f"implant in the {self.implant_ear.value} ear, "
            f"hearing aid in the {self.acoustic_ear.value} ear"
        )


@dataclass(frozen=True)
class DichoticStimulus:
    """A stereo signal with independent content per ear."""

    samples: np.ndarray  # shape (2, n)
    sample_rate: int
    mode: PresentationMode
    assignment: EarAssignment
    implant_lufs: float
    acoustic_lufs: float
    segment_ms: int | None = None

    @property
    def duration_s(self) -> float:
        return self.samples.shape[1] / self.sample_rate

    def channel(self, ear: Ear) -> np.ndarray:
        return self.samples[ear.channel_index]

    def crosstalk_db(self) -> float:
        """Level of the quieter channel relative to the louder, in dB.

        For alternating and sequential modes this should be very low during each
        segment. A high value means content is leaking into the ear that should
        be silent, which would invalidate the isolation the design depends on.
        """
        a = float(np.abs(self.samples[0]).max())
        b = float(np.abs(self.samples[1]).max())
        if max(a, b) <= 0:
            return float("-inf")
        return 20.0 * np.log10(min(a, b) / max(a, b) + 1e-12)


def build_dichotic(
    implant_signal: np.ndarray,
    acoustic_signal: np.ndarray,
    sample_rate: int,
    assignment: EarAssignment,
    mode: PresentationMode = PresentationMode.ALTERNATING,
    segment_ms: int = 500,
    implant_target_lufs: float = DEFAULT_TARGET_LUFS,
    acoustic_target_lufs: float = DEFAULT_TARGET_LUFS,
    ramp_ms: float = 10.0,
) -> DichoticStimulus:
    """Combine two mono signals into one stereo stimulus.

    Parameters
    ----------
    implant_signal:
        Routed to the implanted ear. For simulator fitting this is the unmodified
        source, which the implant will transform into the percept being matched.
    acoustic_signal:
        Routed to the contralateral ear. For simulator fitting this is the
        candidate simulation.
    assignment:
        Which physical ear holds which device. Recorded in the result.
    segment_ms:
        Alternation period, used by :attr:`PresentationMode.ALTERNATING`.
        Roughly 300-700 ms works well: long enough to perceive the character of
        each, short enough that comparison does not rely on memory.
    implant_target_lufs, acoustic_target_lufs:
        Separate loudness targets, and they are separate for a reason. Electric
        and acoustic hearing have entirely different loudness growth functions,
        so matching the two channels to the same measured level does **not**
        make them equally loud to the listener. These should be set from a
        per-listener balance calibration - see :func:`balance_prompt` - and the
        values recorded with the session.
    ramp_ms:
        Raised-cosine fade at each segment boundary, preventing the clicks that
        abrupt switching would otherwise produce. Clicks are both unpleasant and
        an unintended cue.

    Notes
    -----
    Each channel passes through the standard playback safety path independently,
    so neither can exceed the loudness or true-peak ceiling.
    """
    implant_signal = np.asarray(implant_signal, dtype=float)
    acoustic_signal = np.asarray(acoustic_signal, dtype=float)

    if implant_signal.ndim != 1 or acoustic_signal.ndim != 1:
        raise ValueError("both signals must be mono")
    if segment_ms <= 0:
        raise ValueError(f"segment_ms must be positive, got {segment_ms}")

    n = min(len(implant_signal), len(acoustic_signal))
    if n == 0:
        raise ValueError("signals are empty")
    implant_signal, acoustic_signal = implant_signal[:n], acoustic_signal[:n]

    implant_safe, implant_report = prepare_for_playback(
        implant_signal, sample_rate, target_lufs=implant_target_lufs
    )
    acoustic_safe, acoustic_report = prepare_for_playback(
        acoustic_signal, sample_rate, target_lufs=acoustic_target_lufs
    )

    if mode is PresentationMode.SIMULTANEOUS:
        a, b = implant_safe, acoustic_safe
    elif mode is PresentationMode.ALTERNATING:
        a, b = _alternate(implant_safe, acoustic_safe, sample_rate, segment_ms, ramp_ms)
    elif mode is PresentationMode.SEQUENTIAL:
        a, b = _sequential(implant_safe, acoustic_safe, sample_rate, ramp_ms)
    else:
        raise ValueError(f"unknown presentation mode {mode!r}")

    stereo = np.zeros((2, len(a)))
    stereo[assignment.implant_ear.channel_index] = a
    stereo[assignment.acoustic_ear.channel_index] = b

    return DichoticStimulus(
        samples=stereo,
        sample_rate=sample_rate,
        mode=mode,
        assignment=assignment,
        implant_lufs=implant_report.output_lufs,
        acoustic_lufs=acoustic_report.output_lufs,
        segment_ms=segment_ms if mode is PresentationMode.ALTERNATING else None,
    )


def _ramp(n: int, sample_rate: int, ramp_ms: float) -> np.ndarray:
    """Raised-cosine gate of length ``n`` with fades at both ends."""
    gate = np.ones(n)
    r = min(int(ramp_ms / 1000 * sample_rate), n // 2)
    if r > 0:
        fade = 0.5 * (1 - np.cos(np.linspace(0, np.pi, r)))
        gate[:r] = fade
        gate[-r:] = fade[::-1]
    return gate


def _alternate(
    x: np.ndarray, y: np.ndarray, sample_rate: int, segment_ms: int, ramp_ms: float
) -> tuple[np.ndarray, np.ndarray]:
    seg = max(1, int(segment_ms / 1000 * sample_rate))
    a, b = np.zeros_like(x), np.zeros_like(y)
    for i, start in enumerate(range(0, len(x), seg)):
        stop = min(start + seg, len(x))
        gate = _ramp(stop - start, sample_rate, ramp_ms)
        if i % 2 == 0:
            a[start:stop] = x[start:stop] * gate
        else:
            b[start:stop] = y[start:stop] * gate
    return a, b


def _sequential(
    x: np.ndarray, y: np.ndarray, sample_rate: int, ramp_ms: float, gap_ms: int = 400
) -> tuple[np.ndarray, np.ndarray]:
    gap = int(gap_ms / 1000 * sample_rate)
    total = len(x) + gap + len(y)
    a, b = np.zeros(total), np.zeros(total)
    a[: len(x)] = x * _ramp(len(x), sample_rate, ramp_ms)
    b[len(x) + gap :] = y * _ramp(len(y), sample_rate, ramp_ms)
    return a, b


def balance_prompt(assignment: EarAssignment) -> str:
    """Instructions for the per-listener loudness balance calibration.

    This must be done before any dichotic comparison and repeated whenever the
    audiogram changes. Electric and acoustic loudness growth differ so much that
    equal measured levels are not equally loud, and an unbalanced pair means
    every subsequent judgement is partly a judgement about level.
    """
    return (
        f"Balance check ({assignment.describe()}).\n\n"
        "You will hear the same sound in both ears. Adjust the balance until it "
        "sits in the centre of your head rather than pulling to one side.\n\n"
        "Take your time - this only needs doing once per session, but every "
        "later comparison depends on it being right."
    )
