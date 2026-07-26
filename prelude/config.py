# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Configuration loading.

Simulator parameters live in YAML rather than in source. This is not a style
preference: the predecessor project performed its parameter sweeps by editing
constants between runs, and it is now impossible to say which settings produced
which output file. Configurations here carry a hash that is written into every
artifact's provenance sidecar.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import yaml

from .ci_sim import SimulatorConfig


def load_simulator_config(path: str | Path) -> SimulatorConfig:
    """Load a :class:`SimulatorConfig` from a YAML file.

    Unknown keys raise rather than being ignored, so that a typo in a parameter
    name fails immediately instead of silently leaving the default in place.
    """
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}

    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")

    data.pop("name", None)
    data.pop("description", None)

    known = {f.name for f in fields(SimulatorConfig)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(
            f"{path}: unknown configuration keys {sorted(unknown)}. "
            f"Valid keys are {sorted(known)}."
        )

    return SimulatorConfig(**data)


def save_simulator_config(path: str | Path, config: SimulatorConfig, name: str = "") -> None:
    """Write a configuration to YAML, including its hash as a comment."""
    from dataclasses import asdict

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    body = yaml.safe_dump(asdict(config), sort_keys=True, default_flow_style=False)
    header = f"# {name}\n" if name else ""
    path.write_text(f"{header}# config_hash: {config.hash()}\n{body}")
