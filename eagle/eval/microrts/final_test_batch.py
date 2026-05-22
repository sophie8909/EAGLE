"""Batch final-test replay helpers for existing EAGLE runs."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ...config import load_config_from_json
from ...main import OPPONENT_LIST
from ...project import PROJECT_ROOT, ensure_directory
from ...representation.fitness import fitness_sort_key
from ...utils.component_pool import ComponentPool
from ...utils.checkpoint import CheckpointManager, deserialize_individual
from ...evolution.component.log_parse import parse_individuals_from_ea_log, parse_population_snapshot_from_ea_log
from .full_game_evaluator import FullGameEvaluator
from .generation_replay import extract_individual_ids_up_to_front


FINAL_TEST_REPEATS = 10


def run_final_test_batch(
    run_dir: str | Path,
    *,
    map_selection: str = "single",
    opponent_selection: str = "single",
    repeats: int = FINAL_TEST_REPEATS,
) -> dict[str, Any]:
    """Replay one saved run into a timestamped raw final-test results JSON payload."""
    resolved_run_dir = Path(run_dir).resolve()
    if not (resolved_run_dir / "config.json").exists():
        raise FileNotFoundError(f"Selected run is missing config.json: {resolved_run_dir / 'config.json'}")

    config = load_config_from_json(resolved_run_dir)
    final_test_mode, generation_log_path, candidate_individuals = _select_candidates(resolved_run_dir, config)
    selected_individuals = _select_final_test_individuals(final_test_mode, generation_log_path, candidate_individuals)
    if not selected_individuals:
        raise ValueError(f"No final-test candidates found under {resolved_run_dir}.")

    map_locations = _resolve_map_locations(config, map_selection)
    opponents = _resolve_opponents(config, opponent_selection)
    if repeats < 1:
        raise ValueError("repeats must be >= 1.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = ensure_directory(resolved_run_dir / "final_test" / timestamp)
    runtime_logs_dir = ensure_directory(output_dir / "microrts")
    evaluator = FullGameEvaluator(
        ComponentPool.from_json(str(resolved_run_dir / "component_pool.json")),
        config,
        runtime_logs_dir=runtime_logs_dir,
    )
    output_path = output_dir / "results.json"

    payload: dict[str, Any] = {
        "source_run_dir": str(resolved_run_dir),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": final_test_mode,
        "selection": {
            "type": "front_1" if final_test_mode == "MO" else "best",
            "individual_ids": [individual.id for individual in selected_individuals],
        },
        "config": {
            "maps": list(map_locations),
            "opponents": list(opponents),
            "repeats": int(repeats),
        },
        "results": [],
    }

    for individual in selected_individuals:
        prompt = evaluator._construct_prompt(individual)
        for map_location in map_locations:
            for opponent in opponents:
                for repeat in range(repeats):
                    result = evaluator.run_prompt_based_agent(
                        individual=individual,
                        prompt=prompt,
                        opponent=opponent,
                        test=True,
                        llm_call_limit=None,
                        map_location=map_location,
                    )
                    match_score = dict(result.get("match_score") or {})
                    simulation_meta = dict(result.get("simulation_meta") or {})
                    raw_result = _load_result_json(simulation_meta.get("result_json_path"))
                    payload["results"].append(
                        _build_raw_result_record(
                            individual_id=individual.id,
                            map_location=map_location,
                            opponent=opponent,
                            repeat=repeat,
                            match_score=match_score,
                            raw_result=raw_result,
                            simulation_meta=simulation_meta,
                        )
                    )
                    _write_results(output_path, payload)

    return payload


def _select_candidates(
    run_dir: Path,
    config: Any,
) -> tuple[str, Path | None, list[Any]]:
    """Resolve the final-generation candidate population and run mode."""
    mo_logs = sorted(run_dir.glob("generation_*_mo.txt"), key=_extract_generation_number)
    ga_logs = sorted(
        [path for path in run_dir.glob("generation_*.txt") if not path.name.endswith("_mo.txt")],
        key=_extract_generation_number,
    )
    if mo_logs:
        generation_log_path = mo_logs[-1]
        mode = "MO"
    elif ga_logs:
        generation_log_path = ga_logs[-1]
        mode = "SO"
    else:
        generation_log_path = None
        mode = _mode_from_config(config)

    if generation_log_path is None:
        candidates = _load_checkpoint_population(run_dir)
    else:
        candidates = _load_generation_candidates(generation_log_path)
    return mode, generation_log_path, candidates


def _select_final_test_individuals(
    mode: str,
    generation_log_path: Path | None,
    candidate_individuals: list[Any],
) -> list[Any]:
    """Select Front 1 or the best individual from the final population."""
    if not candidate_individuals:
        return []
    if mode == "MO" and generation_log_path is not None:
        selected_ids = set(extract_individual_ids_up_to_front(generation_log_path, 1))
        return [individual for individual in candidate_individuals if individual.id in selected_ids]
    return [_best_individual(candidate_individuals)]


def _best_individual(individuals: list[Any]) -> Any:
    """Return the highest-fitness individual from one population snapshot."""
    return max(
        individuals,
        key=lambda individual: fitness_sort_key(getattr(individual, "fitness", {})),
    )


def _load_generation_candidates(generation_log_path: Path) -> list[Any]:
    """Load the final candidate population from one generation log."""
    population_snapshot = parse_population_snapshot_from_ea_log(str(generation_log_path))
    if population_snapshot:
        return population_snapshot

    fronts = parse_individuals_from_ea_log(str(generation_log_path))
    seen_ids: set[str] = set()
    individuals: list[Any] = []
    for front in fronts:
        for individual in front:
            if individual.id in seen_ids:
                continue
            seen_ids.add(individual.id)
            individuals.append(individual)
    return individuals


def _load_checkpoint_population(run_dir: Path) -> list[Any]:
    """Load the latest checkpoint population when text logs are unavailable."""
    checkpoint_state = CheckpointManager(run_dir).load_state()
    if not checkpoint_state or not checkpoint_state.get("population"):
        return []
    return [
        deserialize_individual(payload)
        for payload in list(checkpoint_state.get("population") or [])
        if isinstance(payload, dict)
    ]


def _resolve_map_locations(config: Any, map_selection: str) -> list[str]:
    """Return one deterministic map or every map in the configured folder."""
    map_dir = str(getattr(config, "gameplay_map_dir", "8x8") or "8x8").strip().strip("/\\") or "8x8"
    maps_root = PROJECT_ROOT / "third_party" / "microrts" / "maps" / map_dir
    candidates = sorted(path for path in maps_root.glob("*.xml") if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No MicroRTS maps found under maps/{map_dir}.")
    if str(map_selection).strip().lower() == "all":
        return [f"maps/{map_dir}/{path.name}" for path in candidates]
    return [f"maps/{map_dir}/{candidates[0].name}"]


def _resolve_opponents(config: Any, opponent_selection: str) -> list[str]:
    """Return one deterministic opponent or the full configured list."""
    configured = [str(item) for item in list(getattr(config, "gameplay_opponents", []) or []) if str(item).strip()]
    opponents = configured or list(OPPONENT_LIST)
    if str(opponent_selection).strip().lower() == "all":
        return opponents
    return [opponents[0]]


def _build_raw_result_record(
    *,
    individual_id: str,
    map_location: str,
    opponent: str,
    repeat: int,
    match_score: dict[str, float],
    raw_result: dict[str, Any] | None,
    simulation_meta: dict[str, Any],
) -> dict[str, Any]:
    """Convert one replay result into the requested raw JSON schema."""
    win_score = float(match_score.get("win_score", 0.0))
    target_side = _result_target_side(raw_result, simulation_meta)
    ally_snapshot, enemy_snapshot = _result_snapshots(raw_result, target_side)
    return {
        "individual_id": individual_id,
        "map": map_location,
        "opponent": opponent,
        "repeat": int(repeat),
        "win": bool(win_score >= 1.0),
        "score": float(match_score.get("raw_resource_advantage_score", 0.0)),
        "ally": ally_snapshot,
        "enemy": enemy_snapshot,
    }


def _result_target_side(raw_result: dict[str, Any] | None, simulation_meta: dict[str, Any]) -> str:
    """Return the target side used by the game result JSON."""
    if isinstance(raw_result, dict):
        target_side = raw_result.get("target_side")
        if target_side is not None:
            return str(target_side)
        summary = raw_result.get("summary")
        if isinstance(summary, dict) and summary.get("target_side") is not None:
            return str(summary.get("target_side"))
    summary = dict(simulation_meta.get("parsed_log") or {}).get("summary", {})
    if isinstance(summary, dict) and summary.get("target_side") is not None:
        return str(summary.get("target_side"))
    return "0"


def _result_snapshots(
    raw_result: dict[str, Any] | None,
    target_side: str,
) -> tuple[dict[str, int], dict[str, int]]:
    """Return ally and enemy snapshots from the raw MicroRTS result payload."""
    if isinstance(raw_result, dict):
        players = raw_result.get("players")
        if isinstance(players, dict):
            p0 = dict(players.get("p0") or {})
            p1 = dict(players.get("p1") or {})
            if target_side == "1":
                return _normalize_snapshot(p1), _normalize_snapshot(p0)
            return _normalize_snapshot(p0), _normalize_snapshot(p1)
        ally = dict(raw_result.get("ally") or {})
        enemy = dict(raw_result.get("enemy") or {})
        return _normalize_snapshot(ally), _normalize_snapshot(enemy)
    empty = _normalize_snapshot({})
    return empty, empty


def _normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    """Normalize one raw player snapshot into the requested counter fields."""
    unit_types = snapshot.get("unit_types", {}) if isinstance(snapshot, dict) else {}
    base = int(_safe_int(unit_types, "Base"))
    barracks = int(_safe_int(unit_types, "Barracks"))
    worker = int(_safe_int(unit_types, "Worker"))
    light = int(_safe_int(unit_types, "Light"))
    heavy = int(_safe_int(unit_types, "Heavy"))
    ranged = int(_safe_int(unit_types, "Ranged"))
    resources = int(_safe_int(snapshot, "resource_total", fallback_keys=("player_resources", "resources")))
    total_units = base + barracks + worker + light + heavy + ranged
    return {
        "resources": resources,
        "base_count": base,
        "barracks_count": barracks,
        "worker_count": worker,
        "light_count": light,
        "heavy_count": heavy,
        "ranged_count": ranged,
        "total_units": total_units,
    }


def _safe_int(mapping: dict[str, Any], key: str, *, fallback_keys: tuple[str, ...] = ()) -> int:
    """Read one integer-like field from a nested result payload."""
    candidates = (key, *fallback_keys)
    for candidate in candidates:
        try:
            value = mapping.get(candidate)
            if value is not None:
                return int(value)
        except (TypeError, ValueError, AttributeError):
            continue
    return 0


def _mode_from_config(config: Any) -> str:
    """Infer the final-test mode from the saved run config."""
    algorithm = str(getattr(config, "algorithm", "")).strip().lower()
    return "MO" if algorithm in {"nsga2", "nsga2_surrogate"} else "SO"


def _extract_generation_number(path: Path) -> int:
    """Extract the numeric generation suffix from a saved log path."""
    match = re.match(r"generation_(\d+)(?:_mo)?\.txt$", path.name)
    return int(match.group(1)) if match else -1


def _load_result_json(result_json_path: Any) -> dict[str, Any] | None:
    """Load one Java result JSON payload when present."""
    if not result_json_path:
        return None
    path = Path(str(result_json_path))
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_results(output_path: Path, payload: dict[str, Any]) -> None:
    """Persist the current final-test payload to disk."""
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
