"""Filesystem helpers for generated-agent workspaces."""

from __future__ import annotations

from pathlib import Path


def ensure_workspace(path: str | Path) -> Path:
    workspace = Path(path)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace

