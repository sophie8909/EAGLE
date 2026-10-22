"""Recognition and validation for generated experiment run indices."""
from __future__ import annotations

from pathlib import Path

import yaml


EXPERIMENT_INDEX_SCHEMA_VERSION = "eagle-experiment-index-v1"


def is_experiment_run_index(path: Path) -> bool:
    """Return whether ``experiment.yaml`` is a generated config-to-run index."""

    if path.name != "experiment.yaml":
        return False
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if isinstance(payload, dict) and str(payload.get("schema_version", "")).startswith("eagle-experiment-index-"):
        decode_experiment_run_index(payload, path)
        return True
    return (
        isinstance(payload, dict)
        and "schema_version" not in payload
        and all(
            isinstance(name, str)
            and Path(name).suffix.lower() in {".yaml", ".yml"}
            and isinstance(run_dir, str)
            for name, run_dir in payload.items()
        )
    )


def decode_experiment_run_index(payload: object, index_path: Path) -> dict[str, list[str]]:
    """Read versioned replicate lists or migrate the legacy single-run mapping."""

    if not isinstance(payload, dict):
        raise ValueError(f"Experiment run index must contain a YAML mapping: {index_path}")
    if "schema_version" in payload:
        if payload["schema_version"] != EXPERIMENT_INDEX_SCHEMA_VERSION:
            raise ValueError(f"Unsupported experiment run index schema: {payload['schema_version']}")
        entries = payload.get("runs")
    else:
        entries = {name: [run_dir] for name, run_dir in payload.items()}
    if not isinstance(entries, dict) or any(
        not isinstance(name, str)
        or Path(name).suffix.lower() not in {".yaml", ".yml"}
        or not isinstance(run_dirs, list)
        or not run_dirs
        or any(not isinstance(folder, str) or not folder for folder in run_dirs)
        for name, run_dirs in entries.items()
    ):
        raise ValueError(f"Invalid experiment run index entries: {index_path}")
    return entries
