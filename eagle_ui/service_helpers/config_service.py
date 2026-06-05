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


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON mapping with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

