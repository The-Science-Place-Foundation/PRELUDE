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

import warnings
from dataclasses import dataclass
from enum import Enum

import numpy as np

from ..audio.loudness import (
    DEFAULT_TARGET_LUFS,
    integrated_lufs,
    prepare_for_playback,
)


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

    # Match ACHIEVED loudness, not requested loudness.
    #
    # A signal with a high crest factor - a pulsatile simulation especially -
    # cannot reach the loudness target without breaching the true-peak ceiling,
    # so the safety stage scales it down and the requested target is silently
    # missed. Trusting the request would leave the two ears mismatched by as
    # much as 19 dB, which defeats the entire purpose of level matching and is
    # actively unsafe: the listener raises the volume to hear the quiet ear and
    # the other ear becomes far too loud.
    #
    # The intended *difference* between the two targets is preserved; only the
    # absolute level moves, so a balance offset established by calibration still
    # applies.
    requested_delta = implant_target_lufs - acoustic_target_lufs
    achieved_delta = implant_report.output_lufs - acoustic_report.output_lufs
    correction = achieved_delta - requested_delta

    if abs(correction) > 0.1:
        # Bring the louder channel down; never push a channel up, which could
        # re-breach the peak ceiling.
        if correction > 0:
            implant_safe = implant_safe * (10.0 ** (-correction / 20.0))
        else:
            acoustic_safe = acoustic_safe * (10.0 ** (correction / 20.0))

    implant_achieved = integrated_lufs(implant_safe, sample_rate)
    acoustic_achieved = integrated_lufs(acoustic_safe, sample_rate)

    headroom_cost = min(
        implant_report.output_lufs - implant_target_lufs,
        acoustic_report.output_lufs - acoustic_target_lufs,
    )
    if headroom_cost < -6.0:
        warnings.warn(
            f"a channel fell {abs(headroom_cost):.1f} dB short of its loudness "
            f"target because its peaks hit the safety ceiling. Both channels "
            f"have been matched at the lower level, so the ears are still "
            f"balanced, but the stimulus is quiet and the listener may raise "
            f"the volume. A very high crest factor - the pulse carrier is the "
            f"usual cause - is worth reducing before a listening session.",
            stacklevel=2,
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
        implant_lufs=implant_achieved,
        acoustic_lufs=acoustic_achieved,
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
    """Play each window to one ear, then the *same* window to the other.

    Each source window is heard twice - once per ear - so the listener compares
    two renderings of identical material. The output is therefore about twice as
    long as the input.

    The obvious alternative, splitting the timeline so odd windows go to one ear
    and even windows to the other, is wrong and was the original implementation
    here. It makes each ear hear *different passages*, so the listener compares
    different music rather than two versions of the same music. With material
    whose loudness varies over time the effect is severe: the synthetic melody
    used for calibration differs by nearly 13 dB between alternate 500 ms
    windows, which handed one ear all the note onsets and the other all the
    decays.
    """
    seg = max(1, int(segment_ms / 1000 * sample_rate))
    n_windows = max(1, int(np.ceil(len(x) / seg)))
    total = n_windows * seg * 2

    a, b = np.zeros(total), np.zeros(total)
    for i in range(n_windows):
        src_start = i * seg
        src_stop = min(src_start + seg, len(x))
        length = src_stop - src_start
        if length <= 0:
            break
        gate = _ramp(length, sample_rate, ramp_ms)

        a_start = i * 2 * seg
        b_start = a_start + seg
        a[a_start : a_start + length] = x[src_start:src_stop] * gate
        b[b_start : b_start + length] = y[src_start:src_stop] * gate

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
