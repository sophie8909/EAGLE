"""Central checkpoint writing helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import trace


def save_checkpoint_state(log_dir: str | Path, state: dict[str, Any]) -> None:
    """Write latest checkpoint state and append the checkpoint event."""
    resolved_log_dir = Path(log_dir)
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    state_path = resolved_log_dir / "run_state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    trace.record("checkpoint", state, {"log_dir": resolved_log_dir})
