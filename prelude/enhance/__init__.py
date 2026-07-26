# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Pre-processing transforms — Pillar 2.

Not yet implemented. The design is recorded in ``docs/04-ARCHITECTURE.md``; the
intended blocks, ranked by expected value, are dereverberation, source
separation, spectral contrast enhancement, dynamic range compression matched to
the electrical window, onset sharpening, F0 emphasis, and masker removal.

Two constraints govern anything added here.

**Evaluate one lever at a time.** The predecessor project applied several
transforms simultaneously and could not attribute the outcome to any of them.

**The loss is measured after the simulator**, not before it — ``d(CI(g(x)), x)``.
See ``docs/decisions/ADR-0001-learning-formulation.md``; that placement is the
whole problem, and getting it wrong produces a model that tries to recover
information the device has already destroyed.
"""

__all__: list[str] = []
