"""Canonical compact-artifact loader and run-folder resolution."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from eagle.run_artifacts import RUN_SCHEMA_VERSION


@dataclass(frozen=True)
class RunData:
    run_dir: Path
    manifest: dict[str, Any]
    resolved_config: dict[str, Any]
    generation_metrics: list[dict[str, Any]]
    generations: list[dict[str, Any]]
    final_population: dict[str, Any] | None
    timing: list[dict[str, Any]]
    errors: list[dict[str, Any]]


def resolve_latest_run(run_root: Path) -> Path:
    if not run_root.is_dir():
        raise ValueError(f"Configured run root does not exist: {run_root}")
    valid: list[tuple[float, Path]] = []
    for child in run_root.iterdir():
        if not child.is_dir() or child.name.startswith(".") or child.name in {"analysis", "runtime", "logs"}:
            continue
        if child.name.endswith(".tmp") or child.name.startswith("tmp"):
            continue
        try:
            manifest = validate_run_dir(child)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        valid.append((_manifest_time(manifest, child), child))
    if not valid:
        raise ValueError(f"No valid canonical run exists directly under {run_root}.")
    return max(valid, key=lambda item: item[0])[1].resolve()


def resolve_explicit_run(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    validate_run_dir(resolved)
    return resolved


def validate_run_dir(run_dir: Path) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise ValueError(f"Run folder does not exist: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Run folder has no manifest.json: {run_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError(f"Unsupported run manifest schema in {manifest_path}.")
    configuration = manifest.get("configuration", "resolved_config.json")
    if not (run_dir / str(configuration)).is_file():
        raise ValueError(f"Run folder has no supported resolved configuration: {run_dir}")
    completed = manifest.get("completed_generations")
    if not isinstance(completed, list):
        raise ValueError(f"Run manifest has invalid completed_generations: {manifest_path}")
    if not completed and manifest.get("status") not in {"initialized", "running"}:
        raise ValueError(f"Run has neither a completed generation nor initialized status: {run_dir}")
    return manifest


def load_run(run_dir: Path) -> RunData:
    manifest = validate_run_dir(run_dir)
    return RunData(
        run_dir=run_dir,
        manifest=manifest,
        resolved_config=_read_json(run_dir / str(manifest.get("configuration", "resolved_config.json"))) or {},
        generation_metrics=_read_jsonl(run_dir / "generation_metrics.jsonl"),
        generations=[
            _read_json(path) or {}
            for path in sorted((run_dir / "generations").glob("generation_*.json"))
        ] if (run_dir / "generations").is_dir() else [],
        final_population=_read_json(run_dir / "final_population.json"),
        timing=_read_jsonl(run_dir / "timing.jsonl"),
        errors=_read_jsonl(run_dir / "errors.jsonl"),
    )


def _manifest_time(manifest: dict[str, Any], run_dir: Path) -> float:
    value = manifest.get("last_update_time")
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return run_dir.stat().st_mtime


def _read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
