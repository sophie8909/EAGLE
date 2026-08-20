"""Canonical compact-artifact loader and run-folder resolution."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

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
    schema = manifest.get("schema_version")
    if schema != RUN_SCHEMA_VERSION:
        raise ValueError(f"Unsupported run manifest schema in {manifest_path}.")
    if not (run_dir / "config.yaml").is_file():
        raise ValueError(f"Run folder has no supported resolved configuration: {run_dir}")
    if manifest.get("latest_generation") is not None and not isinstance(manifest.get("latest_generation"), int):
        raise ValueError(f"Run manifest has invalid latest_generation: {manifest_path}")
    return manifest


def load_run(run_dir: Path) -> RunData:
    manifest = validate_run_dir(run_dir)
    generations = [
        _read_json(path) or {}
        for path in sorted((run_dir / "generations").glob("generation_*.json"))
    ] if (run_dir / "generations").is_dir() else []
    config = _read_yaml(run_dir / "config.yaml")
    generations = [_materialize_generation(run_dir, item) for item in generations]
    metrics = [
        {**dict(item.get("metrics") or {}), "aos": item.get("aos")}
        for item in generations
    ]
    final_population = {
        "schema_version": "eagle-final-population-reference-v1",
        "population": list(generations[-1].get("population") or []),
    } if generations else None
    errors = _read_jsonl(run_dir / "archives" / "error_memory.jsonl")
    return RunData(
        run_dir=run_dir,
        manifest=manifest,
        resolved_config=config,
        generation_metrics=metrics,
        generations=generations,
        final_population=final_population,
        timing=_read_jsonl(run_dir / "timing.jsonl"),
        errors=errors,
    )


def _materialize_generation(run_dir: Path, generation: dict[str, Any]) -> dict[str, Any]:
    """Resolve compact v3 candidate references into bounded analysis records."""

    population = generation.get("population") or []
    if not isinstance(population, list):
        return generation
    return {
        **generation,
        "population": [
            _materialize_candidate(run_dir, item)
            for item in population
            if isinstance(item, dict)
        ],
    }


def _materialize_candidate(run_dir: Path, reference: dict[str, Any]) -> dict[str, Any]:
    candidate_id = reference.get("candidate_id") or reference.get("id")
    if not candidate_id:
        return dict(reference)
    candidate_dir = run_dir / "candidates" / str(candidate_id)
    stored = _read_json(candidate_dir / "candidate.json") or {}
    candidate = {**reference, **stored}
    artifacts = candidate.get("artifacts") if isinstance(candidate.get("artifacts"), dict) else {}

    if not isinstance(candidate.get("game_eval_result"), dict):
        game = _read_json(_candidate_artifact_path(candidate_dir, artifacts, "game_performance", "evaluation/game_performance.json"))
        if game is not None:
            candidate["game_eval_result"] = _compact_game_result(game)
    if not isinstance(candidate.get("code_quality_result"), dict):
        quality = _read_json(_candidate_artifact_path(candidate_dir, artifacts, "code_quality", "evaluation/code_quality.json"))
        if quality is not None:
            candidate["code_quality_result"] = {
                "code_quality": quality.get("code_quality", quality.get("score")),
                "failure_stage": quality.get("failure_stage"),
            }
    return candidate


def _candidate_artifact_path(
    candidate_dir: Path,
    artifacts: dict[str, Any],
    key: str,
    default: str,
) -> Path:
    relative = Path(str(artifacts.get(key) or default))
    if relative.is_absolute():
        return candidate_dir / default
    resolved = (candidate_dir / relative).resolve()
    try:
        resolved.relative_to(candidate_dir.resolve())
    except ValueError:
        return candidate_dir / default
    return resolved


def _compact_game_result(game: dict[str, Any]) -> dict[str, Any]:
    """Keep analysis fields without retaining every raw per-match payload in memory."""

    keys = (
        "game_performance", "objective", "win_rate", "wins", "draws", "losses",
        "expected_match_count", "completed_match_count", "missing_match_count",
        "opponent_results", "opponent_scores", "evaluation_maps", "rounds_per_map",
        "swap_player_sides",
    )
    return {key: game.get(key) for key in keys if key in game}


def _manifest_time(manifest: dict[str, Any], run_dir: Path) -> float:
    value = manifest.get("updated_at") or manifest.get("last_update_time")
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


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Run config must contain a YAML mapping: {path}")
    return value
