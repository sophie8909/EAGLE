"""Resolve experiment log directories for EA runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from eagle.project import EAGLE_LOGS_DIR
from eagle.utils.checkpoint import CheckpointManager


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


def resolve_resume_log_dir(log_dir: str | Path) -> Path:
    """Resolve a resume request to the checkpointed original experiment directory."""
    requested = Path(log_dir)
    original = CheckpointManager(requested).load_original_log_dir()
    return original if original is not None else requested


def resolve_resume_log_dir_from_config(config_path: str | Path | None) -> Path | None:
    """Resolve resume metadata when a run's saved config is used as the entrypoint."""
    if config_path is None:
        return None
    path = Path(config_path)
    parent = path if path.is_dir() else path.parent
    checkpoint_manager = CheckpointManager(parent)
    original = checkpoint_manager.load_original_log_dir()
    if original is not None:
        return original
    return parent if checkpoint_manager.load_state() is not None else None
