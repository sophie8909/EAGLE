"""Comment-preserving edits for EAGLE's small canonical YAML format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


def update_minimal_yaml(path: Path, updates: Mapping[str, object], *, delete_keys: tuple[str, ...] = ()) -> None:
    """Update top-level keys without rewriting unrelated lines or comments."""
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    handled: set[str] = set()
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.lstrip()
        if raw == stripped and ":" in raw and not stripped.startswith("#"):
            key = raw.split(":", 1)[0].strip()
            if key in updates or key in delete_keys:
                index += 1
                while index < len(lines) and lines[index].lstrip().startswith("- "):
                    index += 1
                if key in updates:
                    output.extend(_render_yaml_value(key, updates[key]))
                    handled.add(key)
                continue
        output.append(raw)
        index += 1
    for key, value in updates.items():
        if key not in handled:
            if output and output[-1].strip():
                output.append("")
            output.extend(_render_yaml_value(key, value))
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _render_yaml_value(key: str, value: object) -> list[str]:
    if isinstance(value, (tuple, list)):
        lines = [f"{key}:"]
        lines.extend(f"  - {_scalar(item)}" for item in value)
        return lines
    return [f"{key}: {_scalar(value)}"]


def _scalar(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)
