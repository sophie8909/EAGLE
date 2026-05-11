"""YAML-backed experiment configuration loading."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import EAConfig, load_config_payload


@dataclass
class ExperimentConfig:
    """Config envelope for selecting framework components by name."""

    algorithm: str = "round_nsga2"
    evaluator: str = "gameplay"
    ea: EAConfig = field(default_factory=EAConfig)
    evaluator_params: dict[str, Any] = field(default_factory=dict)
    opponents: list[str] = field(default_factory=list)


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
    ea_payload = dict(data.get("ea") or {})
    if "algorithm" in data and "algorithm" not in ea_payload:
        ea_payload["algorithm"] = str(data["algorithm"]).strip().lower().replace("-", "_")
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
    algorithm = str(data.get("algorithm") or ea_config.algorithm)
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
    payload = {
        "algorithm": config.algorithm,
        "evaluator": config.evaluator,
        "evaluator_params": dict(config.evaluator_params),
        "opponents": list(config.opponents),
        "ea": {
            key: getattr(config.ea, key)
            for key in config.ea.__dataclass_fields__
        },
    }
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
