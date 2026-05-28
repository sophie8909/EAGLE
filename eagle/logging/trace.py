"""Central trace writing for experiment events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def record(event_type: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> Path | None:
    """Append one trace event and return the written path."""
    details = dict(context or {})
    log_dir = details.get("log_dir")
    if log_dir is None:
        return None
    output_path = _event_path(Path(log_dir), event_type, payload, details)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **dict(payload),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str))
        handle.write("\n")
    return output_path


def _event_path(log_dir: Path, event_type: str, payload: dict[str, Any], context: dict[str, Any]) -> Path:
    """Resolve the existing trace layout for one event."""
    if event_type == "llm_call":
        generation = context.get("generation", payload.get("generation", "unknown"))
        return log_dir / "llm_calls" / f"generation_{_safe_generation_name(generation)}.jsonl"
    if event_type == "aggressiveness_judgment":
        generation = context.get("generation", payload.get("generation", "unknown"))
        return log_dir / "llm_calls" / "aggressiveness" / f"gen_{_safe_generation_name(generation)}.jsonl"
    if event_type == "checkpoint":
        return log_dir / "checkpoints.jsonl"
    return log_dir / "trace" / f"{_safe_generation_name(event_type)}.jsonl"


def _safe_generation_name(value: Any) -> str:
    """Return a filesystem-safe generation suffix."""
    text = str(value).strip()
    if not text:
        return "unknown"
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text)
