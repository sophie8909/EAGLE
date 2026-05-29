"""Batch final-test replay helpers for existing EAGLE runs."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from eagle.config import load_config_from_json
from eagle.main import OPPONENT_LIST
from eagle.project import PROJECT_ROOT, ensure_directory
from eagle.representation.fitness import fitness_sort_key
from eagle.envs.microrts.runner import MicroRTSBackendError
from eagle.utils.component_pool import ComponentPool
from eagle.utils.checkpoint import CheckpointManager, deserialize_individual
from eagle.evolution.component.log_parse import parse_individuals_from_ea_log, parse_population_snapshot_from_ea_log
from .full_game_evaluator import FullGameEvaluator
from .generation_replay import extract_individual_ids_up_to_front


FINAL_TEST_REPEATS = 10


class FinalTestBackendError(RuntimeError):
    """Raised when Final Test cannot reach the configured LLM backend."""


@dataclass(frozen=True)
class FinalTestBackendSettings:
    """Explicit LLM backend settings used for Final Test gameplay."""

    model: str
    base_url: str


def resolve_final_test_backend_settings(config: Any) -> FinalTestBackendSettings:
    """Resolve the selected Final Test LLM backend from env overrides and config."""
    model = str(os.getenv("LLAMA_CPP_MODEL") or getattr(config, "llm_model", "local") or "local").strip()
    base_url = _normalize_llm_base_url(
        os.getenv("LLAMA_CPP_BASE_URL") or getattr(config, "llm_base_url", "http://127.0.0.1:8080/v1")
    )
    return FinalTestBackendSettings(model=model, base_url=base_url)


def validate_final_test_backend(settings: FinalTestBackendSettings, *, timeout_sec: float = 3.0) -> None:
    """Fail fast if the configured OpenAI-compatible LLM endpoint is unreachable."""
    models_url = urljoin(settings.base_url.rstrip("/") + "/", "models")
    request = Request(models_url, method="GET")
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            status = int(getattr(response, "status", 200))
    except HTTPError as exc:
        status = int(exc.code)
    except (OSError, URLError) as exc:
        raise FinalTestBackendError(f"LLM backend is not reachable: {settings.base_url}") from exc
    if status < 200 or status >= 500:
        raise FinalTestBackendError(f"LLM backend is not reachable: {settings.base_url}")


def run_final_test_batch(
    run_dir: str | Path,
    *,
    map_folder: str = "all",
    opponent: str = "all",
    repeats: int = FINAL_TEST_REPEATS,
) -> dict[str, Any]:
    """Replay one saved run into a timestamped raw final-test results JSON payload."""
    resolved_run_dir = Path(run_dir).resolve()
    if not (resolved_run_dir / "config.json").exists():
        raise FileNotFoundError(f"Selected run is missing config.json: {resolved_run_dir / 'config.json'}")

    config = load_config_from_json(resolved_run_dir)
    backend_settings = resolve_final_test_backend_settings(config)
    validate_final_test_backend(backend_settings)
    final_test_mode, generation_log_path, candidate_individuals = _select_candidates(resolved_run_dir, config)
    selected_individuals = _select_final_test_individuals(final_test_mode, generation_log_path, candidate_individuals)
    if not selected_individuals:
        raise ValueError(f"No final-test candidates found under {resolved_run_dir}.")

    map_records = _resolve_map_records(map_folder)
    opponents = _resolve_opponents(opponent)
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
            "maps": [record["map"] for record in map_records],
            "opponents": list(opponents),
            "repeats": int(repeats),
        },
        "results": [],
    }

    for individual in selected_individuals:
        prompt = evaluator._construct_prompt(individual)
        for map_record in map_records:
            for opponent in opponents:
                for repeat in range(repeats):
                    llm_interval = int(config.active_llm_interval())
                    interval_mode = f"interval_{llm_interval}"
                    try:
                        result = evaluator.run_prompt_based_agent(
                            individual=individual,
                            prompt=prompt,
                            opponent=opponent,
                            test=True,
                            llm_call_limit=None,
                            llm_interval=llm_interval,
                            llm_model=backend_settings.model,
                            llm_base_url=backend_settings.base_url,
                            llm_strict_errors=True,
                            interval_mode=interval_mode,
                            map_location=map_record["runtime_map"],
                        )
                    except MicroRTSBackendError as exc:
                        payload["results"].append(
                            _build_failed_result_record(
                                individual_id=individual.id,
                                map_folder=map_record["map_folder"],
                                map_path=map_record["map"],
                                opponent=opponent,
                                repeat=repeat,
                                error=str(exc),
                                log_path=exc.log_path,
                                interval_mode=interval_mode,
                                llm_interval=llm_interval,
                                model=backend_settings.model,
                                base_url=backend_settings.base_url,
                            )
                        )
                        _write_results(output_path, payload)
                        continue
                    match_score = dict(result.get("match_score") or {})
                    simulation_meta = dict(result.get("simulation_meta") or {})
                    simulation_meta["interval_mode"] = interval_mode
                    simulation_meta["llm_interval"] = llm_interval
                    simulation_meta["llm_model"] = backend_settings.model
                    simulation_meta["llm_base_url"] = backend_settings.base_url
                    raw_result = _load_result_json(simulation_meta.get("result_json_path"))
                    payload["results"].append(
                        _build_raw_result_record(
                            individual_id=individual.id,
                            map_folder=map_record["map_folder"],
                            map_path=map_record["map"],
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


def _resolve_map_records(map_folder: str) -> list[dict[str, str]]:
    """Return map records for all folders or one selected map folder."""
    maps_root = PROJECT_ROOT / "third_party" / "microrts" / "maps"
    if not maps_root.exists():
        raise FileNotFoundError(f"MicroRTS maps directory does not exist: {maps_root}.")
    selected_folder = str(map_folder or "all").strip().strip("/\\") or "all"
    folders = [path for path in sorted(maps_root.iterdir()) if path.is_dir()]
    if selected_folder != "all":
        selected_path = maps_root / selected_folder
        if not selected_path.is_dir():
            raise FileNotFoundError(f"MicroRTS map folder does not exist: maps/{selected_folder}.")
        folders = [selected_path]

    records: list[dict[str, str]] = []
    for folder in folders:
        for path in sorted(folder.rglob("*.xml")):
            relative_path = path.relative_to(maps_root).as_posix()
            records.append(
                {
                    "map_folder": folder.name,
                    "map": relative_path,
                    "runtime_map": f"maps/{relative_path}",
                }
            )
    if not records:
        folder_text = selected_folder if selected_folder != "all" else "all map folders"
        raise FileNotFoundError(f"No MicroRTS maps found under {folder_text}.")
    return records


def _resolve_opponents(opponent: str) -> list[str]:
    """Return all supported opponents or one selected opponent."""
    selected_opponent = str(opponent or "all").strip()
    if selected_opponent == "all":
        return list(OPPONENT_LIST)
    if selected_opponent not in OPPONENT_LIST:
        raise ValueError(f"Unsupported final-test opponent: {selected_opponent}")
    return [selected_opponent]


def _build_raw_result_record(
    *,
    individual_id: str,
    map_folder: str,
    map_path: str,
    opponent: str,
    repeat: int,
    match_score: dict[str, float],
    raw_result: dict[str, Any] | None,
    simulation_meta: dict[str, Any],
) -> dict[str, Any]:
    """Convert one replay result into the requested raw JSON schema."""
    target_side = _result_target_side(raw_result, simulation_meta)
    result_label, win_score = _result_label_and_win_score(raw_result, simulation_meta, target_side)
    ally_snapshot, enemy_snapshot = _result_snapshots(raw_result, target_side)
    return {
        "individual_id": individual_id,
        "map_folder": map_folder,
        "map": map_path,
        "opponent": opponent,
        "repeat": int(repeat),
        "result": result_label,
        "raw": {
            "win_score": win_score,
            "score": _raw_result_score(raw_result, target_side, match_score),
            "ally": ally_snapshot,
            "enemy": enemy_snapshot,
        },
        "paths": {
            "log": str(simulation_meta.get("log_path")) if simulation_meta.get("log_path") else "",
            "trace_xml": str(simulation_meta.get("trace_xml_path")) if simulation_meta.get("trace_xml_path") else "",
            "trace_json": str(simulation_meta.get("trace_json_path")) if simulation_meta.get("trace_json_path") else None,
        },
        "runtime": {
            "interval_mode": str(simulation_meta.get("interval_mode") or ""),
            "llm_interval": simulation_meta.get("llm_interval"),
            "model": str(simulation_meta.get("llm_model") or ""),
            "base_url": str(simulation_meta.get("llm_base_url") or ""),
        },
    }


def _build_failed_result_record(
    *,
    individual_id: str,
    map_folder: str,
    map_path: str,
    opponent: str,
    repeat: int,
    error: str,
    log_path: str | None,
    interval_mode: str,
    llm_interval: int,
    model: str,
    base_url: str,
) -> dict[str, Any]:
    """Build one failed Final Test repeat without turning it into game outcome."""
    ally_empty = _normalize_snapshot({})
    enemy_empty = _normalize_snapshot({})
    return {
        "individual_id": individual_id,
        "map_folder": map_folder,
        "map": map_path,
        "opponent": opponent,
        "repeat": int(repeat),
        "result": "Failed",
        "status": "failed",
        "error": error,
        "raw": {
            "win_score": 0.0,
            "score": 0.0,
            "ally": ally_empty,
            "enemy": enemy_empty,
        },
        "paths": {
            "log": str(log_path or ""),
            "trace_xml": "",
            "trace_json": None,
        },
        "runtime": {
            "interval_mode": interval_mode,
            "llm_interval": int(llm_interval),
            "model": model,
            "base_url": base_url,
        },
    }


def _result_label_and_win_score(
    raw_result: dict[str, Any] | None,
    simulation_meta: dict[str, Any],
    target_side: str,
) -> tuple[str, float]:
    """Return the ally outcome label and canonical win score."""
    winner = None
    if isinstance(raw_result, dict):
        winner = raw_result.get("winner")
    if winner is None:
        summary = dict(simulation_meta.get("parsed_log") or {}).get("summary", {})
        if isinstance(summary, dict):
            winner = summary.get("winner")

    if winner is None or str(winner) in {"", "-1", "None", "none", "null"}:
        return "Draw", 0.0
    if str(winner) == str(target_side):
        return "Win", 1.0
    return "Loss", -1.0


def _raw_result_score(
    raw_result: dict[str, Any] | None,
    target_side: str,
    match_score: dict[str, float],
) -> float:
    """Return an unweighted terminal score when the raw game payload provides one."""
    scoreboard = raw_result.get("final_scoreboard") if isinstance(raw_result, dict) else None
    if isinstance(scoreboard, dict):
        try:
            p0_eval = float(scoreboard.get("p0_eval", 0.0))
            p1_eval = float(scoreboard.get("p1_eval", 0.0))
        except (TypeError, ValueError):
            pass
        else:
            return p1_eval - p0_eval if str(target_side) == "1" else p0_eval - p1_eval
    try:
        return float(match_score.get("raw_resource_advantage_score", 0.0))
    except (TypeError, ValueError):
        return 0.0


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
    return {
        "resources": resources,
        "base_count": base,
        "barracks_count": barracks,
        "worker_count": worker,
        "light_count": light,
        "heavy_count": heavy,
        "ranged_count": ranged,
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


def _normalize_llm_base_url(raw_url: Any) -> str:
    """Normalize the OpenAI-compatible LLM API base URL."""
    base_url = str(raw_url or "http://127.0.0.1:8080/v1").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        base_url = "http://" + base_url
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return base_url


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

