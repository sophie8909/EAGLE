"""Config file services used by the EAGLE NiceGUI dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_mapping_strict(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk.

    Args:
        path: JSON file path.

    Returns:
        Parsed JSON object.

    Raises:
        json.JSONDecodeError: If the file is malformed.
        ValueError: If the JSON root is not an object.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config JSON must be an object: {path}")
    return payload


def merge_config_payload(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge config mappings while letting lists and scalars override."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_config_payload(current, value)
        else:
            merged[key] = value
    return merged


def load_complete_config_payload(config_path: Path, default_config: Path) -> dict[str, Any]:
    """Return a complete config payload using the default config as schema base.

    Args:
        config_path: User-selected config path.
        default_config: Repository default config path.

    Returns:
        A merged config object.
    """
    payload: dict[str, Any] = {}
    if default_config.exists():
        payload = merge_config_payload(payload, read_json_mapping_strict(default_config))
    if config_path.exists() and config_path.resolve() != default_config.resolve():
        payload = merge_config_payload(payload, read_json_mapping_strict(config_path))
    elif config_path.exists() and not payload:
        payload = merge_config_payload(payload, read_json_mapping_strict(config_path))
    return payload


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON mapping with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_config_reference(path_text: str, *, config_path: Path, repo_root: Path) -> Path:
    """Resolve a config-referenced file path.

    Args:
        path_text: Raw path stored in JSON.
        config_path: Config file that owns the reference.
        repo_root: Repository root used by the GUI.

    Returns:
        Existing absolute path when one candidate exists, otherwise the repo-root
        interpretation. Candidate order keeps repo-relative paths stable while
        still allowing config-local files such as `my_run_components.json`.
    """
    raw_path = Path(path_text)
    if raw_path.is_absolute():
        return raw_path
    config_candidate = config_path.parent / raw_path
    repo_candidate = repo_root / raw_path
    if config_candidate.exists():
        return config_candidate
    if repo_candidate.exists():
        return repo_candidate
    if len(raw_path.parts) == 1:
        return config_candidate
    return repo_candidate

