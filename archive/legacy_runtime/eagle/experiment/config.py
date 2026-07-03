"""YAML-backed experiment configuration loading."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import EAConfig, config_to_payload, load_config_payload, normalize_algorithm_name

_EA_FIELD_NAMES = set(EAConfig.__dataclass_fields__)


@dataclass
class ExperimentConfig:
    """Config envelope for selecting framework components by name."""

    algorithm: str = "nsga2"
    evaluator: str = "gameplay"
    ea: EAConfig = field(default_factory=EAConfig)
    evaluator_params: dict[str, Any] = field(default_factory=dict)
    opponents: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical serialized experiment-config shape."""
        return {
            "algorithm": self.algorithm,
            "evaluator": self.evaluator,
            "evaluator_params": dict(self.evaluator_params),
            "opponents": list(self.opponents),
            "ea": config_to_payload(self.ea),
        }


def load_experiment_config(path: str | Path | None) -> ExperimentConfig:
    """Load an experiment YAML/JSON file or return defaults when omitted."""
    if path is None:
        return ExperimentConfig()
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Experiment config not found: {config_path}")
    payload = _read_mapping(config_path)
    return experiment_config_from_payload(payload)


def experiment_config_from_payload(payload: dict[str, Any] | None) -> ExperimentConfig:
    """Build an experiment config from a plain mapping."""
    data = dict(payload or {})
    ea_payload = _ea_payload_from_experiment_payload(data)
    if "algorithm" in data and "algorithm" not in ea_payload:
        ea_payload["algorithm"] = normalize_algorithm_name(
            data["algorithm"],
            evaluator=data.get("evaluator"),
            surrogate=data.get("surrogate") or ea_payload.get("surrogate"),
            warn=True,
        )
    evaluator_value = data.get("evaluator")
    evaluator = str(
        (evaluator_value.get("name") if isinstance(evaluator_value, dict) else evaluator_value)
        or data.get("evaluator_name")
        or ea_payload.get("evaluator")
        or "gameplay"
    ).strip().lower()
    if "evaluator" not in ea_payload:
        ea_payload["evaluator"] = evaluator
    ea_config = load_config_payload(ea_payload)
    algorithm = normalize_algorithm_name(
        data.get("algorithm") or ea_config.algorithm,
        evaluator=evaluator,
        surrogate=getattr(ea_config, "surrogate", None),
        warn=True,
    )
    opponents = list(data.get("opponents") or ea_config.gameplay_opponents or [])
    evaluator_params = dict(data.get("evaluator_params") or {})
    if isinstance(evaluator_value, dict):
        evaluator_params.update(dict(evaluator_value.get("params") or {}))
    return ExperimentConfig(
        algorithm=algorithm,
        evaluator=evaluator,
        ea=ea_config,
        evaluator_params=evaluator_params,
        opponents=opponents,
    )


def save_experiment_config(config: ExperimentConfig, path: str | Path) -> Path:
    """Save one experiment config as YAML when PyYAML is available, otherwise JSON."""
    output_path = Path(path)
    payload = config.to_payload()
    try:
        import yaml

        output_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    except ImportError:
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def _read_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML or JSON mapping from disk."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml

        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Experiment config must be a mapping: {path}")
        return loaded
    except ImportError:
        return json.loads(text)


def _ea_payload_from_experiment_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Extract EA settings from canonical or flat legacy config JSON."""
    if isinstance(data.get("ea"), dict):
        return dict(data["ea"])
    return {
        key: value
        for key, value in data.items()
        if key in _EA_FIELD_NAMES
    }
