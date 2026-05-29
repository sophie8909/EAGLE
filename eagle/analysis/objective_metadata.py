"""Objective metadata helpers for analysis rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eagle.objectives.registry import get_objective
from eagle.core.plugin_loader import load_plugin


@dataclass(frozen=True)
class ObjectiveSpec:
    """Display metadata for one fitness vector position."""

    index: int
    name: str
    display_name: str
    direction: str | None = None

    @property
    def axis_label(self) -> str:
        """Return a plot label with optimization direction when known."""
        suffix = {"max": " ↑", "min": " ↓"}.get(str(self.direction or "").lower(), "")
        return f"{self.display_name}{suffix}"


def load_run_objective_specs(run_dir: str | Path, dimension: int = 0) -> list[ObjectiveSpec]:
    """Load ordered objective specs from a run config, padding missing metadata."""
    path = Path(run_dir)
    payload = _load_config_payload(path)
    configured_names = _configured_objective_names(payload.get("objective_config"))
    minimum = max(dimension, len(configured_names))
    if minimum == 0:
        minimum = 2

    application = str(payload.get("application") or "microrts")
    if application == "microrts":
        register = getattr(load_plugin("microrts"), "register_defaults", None)
        if callable(register):
            register()
    specs: list[ObjectiveSpec] = []
    for index in range(minimum):
        name = configured_names[index] if index < len(configured_names) else f"objective_{index}"
        specs.append(_objective_spec(application, name, index))
    return specs


def objective_names(specs: list[ObjectiveSpec]) -> list[str]:
    """Return fitness keys in configured index order."""
    return [spec.name for spec in specs]


def objective_axis_labels(specs: list[ObjectiveSpec]) -> dict[str, str]:
    """Return axis labels keyed by objective name."""
    return {spec.name: spec.axis_label for spec in specs}


def _load_config_payload(path: Path) -> dict[str, Any]:
    """Return the config JSON mapping for a run directory or config path."""
    config_path = path / "config.json" if path.is_dir() else path
    if not config_path.exists():
        return {}
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _configured_objective_names(objective_config: Any) -> list[str]:
    """Return the configured fitness index order, if present."""
    if not isinstance(objective_config, dict):
        return []
    mode = str(objective_config.get("mode") or "").strip().lower()
    if mode == "multi" and isinstance(objective_config.get("objectives"), list):
        return [str(name) for name in objective_config["objectives"] if str(name).strip()]
    if mode == "weighted_mix" and isinstance(objective_config.get("weights"), dict):
        return [str(name) for name in objective_config["weights"] if str(name).strip()]
    if mode == "single" and objective_config.get("objective"):
        return [str(objective_config["objective"])]
    return []


def _objective_spec(application: str, name: str, index: int) -> ObjectiveSpec:
    """Build one spec from registry metadata, falling back to the raw name."""
    try:
        objective = get_objective(application, name)
    except ValueError:
        return ObjectiveSpec(index=index, name=name, display_name=name)
    label = str(getattr(objective, "label", "") or name)
    return ObjectiveSpec(
        index=index,
        name=str(getattr(objective, "key", "") or name),
        display_name=label,
        direction=str(getattr(objective, "direction", "") or "") or None,
    )
