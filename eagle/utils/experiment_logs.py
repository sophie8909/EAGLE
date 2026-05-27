"""Resolve experiment log directories for EA runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from eagle.project import EAGLE_LOGS_DIR


def new_experiment_log_dir(*, root: Path = EAGLE_LOGS_DIR) -> Path:
    """Create and return a fresh timestamped experiment log directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = root / timestamp
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def resolve_experiment_log_dir(log_dir: str | Path | None = None) -> Path:
    """Return an existing run directory or create a fresh timestamped one."""
    if log_dir is None:
        return new_experiment_log_dir()
    resolved = Path(log_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
