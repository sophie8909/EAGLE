"""Run prompt-level benchmark batches comparing EAGLE vs surrogate Java-agent matches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import EAConfig, load_config_from_json
from ..envs.microrts import locate_microrts_root
from ..main import OPPONENT_LIST, _resolve_component_pool_path
from ..project import DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH, EAGLE_LOGS_DIR
from ..surrogate.compiler import compile_prompt_to_surrogate_spec
from ..utils.component_pool import ComponentPool
from ..utils.fitness_recorder import FitnessRecorder
from ..utils.individual import Individual
from .evaluator import Evaluator
DEFAULT_SURROGATE_VALIDATION_TIMEOUT_SEC = 60
DEFAULT_QUICK_RUN_OPPONENT = "ai.PassiveAI"


def _build_random_prompt_artifacts(component_pool: ComponentPool, config: EAConfig) -> tuple[Individual, str]:
    """Create one random EA-style individual and render its prompt."""
    individual = Individual()
    individual.initialize_randomly(component_pool)
    evaluator = Evaluator(component_pool, config)
    prompt = evaluator.construct_prompt(individual)
    return individual, prompt


def _make_experiment_log_dir() -> Path:
    """Create the output directory for one surrogate-validation experiment run."""
    log_dir = EAGLE_LOGS_DIR / f"surrogate_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _make_smoke_log_dir() -> Path:
    """Create the output directory for one fast surrogate smoke-test run."""
    log_dir = EAGLE_LOGS_DIR / f"surrogate_validation_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _prompt_digest(prompt: str) -> str:
    """Build a stable digest for the rendered prompt text."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _average(values: list[float]) -> float | None:
    """Return the arithmetic mean when at least one value is present."""
    if not values:
        return None
    return sum(values) / len(values)


def _safe_float(value: Any) -> float | None:
    """Convert one optional numeric-ish value into float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_final_tick(parsed_log: dict[str, Any] | None) -> int | None:
    """Infer the last observed game tick from parsed log structures."""
    if not isinstance(parsed_log, dict):
        return None

    candidates: list[int] = []
    for row in list(parsed_log.get("resource_history") or []):
        time_value = row.get("time")
        if isinstance(time_value, int):
            candidates.append(time_value)
    for row in list(parsed_log.get("feature_history") or []):
        time_value = row.get("time")
        if isinstance(time_value, int):
            candidates.append(time_value)
    for segment in list(parsed_log.get("segments") or []):
        current_time = segment.get("current_time")
        if isinstance(current_time, int):
            candidates.append(current_time)
    return max(candidates) if candidates else None


def _build_mode_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one benchmark mode into compact summary statistics."""
    if not records:
        return {
            "match_count": 0,
            "cached_match_count": 0,
            "avg_win_score": None,
            "avg_resource_advantage_score": None,
            "avg_game_time_sec": None,
            "avg_final_tick": None,
            "win_count": 0,
            "draw_count": 0,
            "loss_count": 0,
        }

    return {
        "match_count": len(records),
        "cached_match_count": sum(1 for record in records if record.get("cached")),
        "avg_win_score": _average([float(record.get("win_score", 0.0)) for record in records]),
        "avg_resource_advantage_score": _average(
            [float(record.get("resource_advantage_score", 0.0)) for record in records]
        ),
        "avg_game_time_sec": _average(
            [float(record.get("game_time_sec", 0.0)) for record in records if record.get("game_time_sec") is not None]
        ),
        "avg_final_tick": _average(
            [float(record.get("final_tick", 0.0)) for record in records if record.get("final_tick") is not None]
        ),
        "win_count": sum(1 for record in records if record.get("result") == "Win"),
        "draw_count": sum(1 for record in records if record.get("result") == "Draw"),
        "loss_count": sum(1 for record in records if record.get("result") == "Loss"),
    }


def _result_label_from_fitness(fitness: list[float]) -> str:
    """Map the first objective to the familiar Win/Draw/Loss labels."""
    if fitness and fitness[0] == 1.0:
        return "Win"
    if fitness and fitness[0] == 0.0:
        return "Loss"
    return "Draw"


def _collect_match_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten all individual/mode match results into one table."""
    rows: list[dict[str, Any]] = []
    for individual_result in list(results.get("individual_results") or []):
        individual_info = dict(individual_result.get("individual") or {})
        for mode_name, records in dict(individual_result.get("modes") or {}).items():
            for record in records:
                rows.append(
                    {
                        "experiment_type": results.get("experiment_type"),
                        "timestamp": results.get("timestamp"),
                        "prompt_digest": individual_result.get("prompt_digest"),
                        "individual_id": individual_info.get("id"),
                        "mode": mode_name,
                        "benchmark_mode": record.get("benchmark_mode"),
                        "opponent": record.get("opponent"),
                        "result": record.get("result"),
                        "win_score": record.get("win_score"),
                        "resource_advantage_score": record.get("resource_advantage_score"),
                        "game_time_sec": record.get("game_time_sec"),
                        "final_tick": record.get("final_tick"),
                        "max_cycles": record.get("max_cycles"),
                        "winner": record.get("winner"),
                        "timeout": record.get("timeout"),
                        "llm_calls": record.get("llm_calls"),
                        "llm_interval": record.get("llm_interval"),
                        "run_time_per_game_sec": record.get("run_time_per_game_sec"),
                        "runner_script": record.get("runner_script"),
                        "ai1": record.get("ai1"),
                        "ai2": record.get("ai2"),
                        "java_match_win_score": record.get("java_match_win_score"),
                        "java_match_resource_advantage_score": record.get("java_match_resource_advantage_score"),
                        "cached": record.get("cached"),
                        "log_path": record.get("log_path"),
                    }
                )
    return rows


def _write_match_results_csv(log_dir: Path, results: dict[str, Any]) -> None:
    """Write one flat per-match CSV for downstream plotting and spreadsheet analysis."""
    rows = _collect_match_rows(results)

    fieldnames = [
        "experiment_type",
        "timestamp",
        "prompt_digest",
        "individual_id",
        "mode",
        "benchmark_mode",
        "opponent",
        "result",
        "win_score",
        "resource_advantage_score",
        "game_time_sec",
        "final_tick",
        "max_cycles",
        "winner",
        "timeout",
        "llm_calls",
        "llm_interval",
        "run_time_per_game_sec",
        "runner_script",
        "ai1",
        "ai2",
        "java_match_win_score",
        "java_match_resource_advantage_score",
        "cached",
        "log_path",
    ]

    output_path = log_dir / "surrogate_validation_matches.csv"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_mode_summary_csv(log_dir: Path, results: dict[str, Any]) -> None:
    """Write one compact per-mode summary CSV for quick experiment comparison."""
    summaries = dict(results.get("mode_summaries") or {})
    fieldnames = [
        "experiment_type",
        "timestamp",
        "prompt_digest",
        "individual_id",
        "mode",
        "match_count",
        "cached_match_count",
        "runner_script",
        "avg_win_score",
        "avg_resource_advantage_score",
        "avg_game_time_sec",
        "avg_final_tick",
        "win_count",
        "draw_count",
        "loss_count",
    ]
    output_path = log_dir / "surrogate_validation_mode_summary.csv"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for individual_result in list(results.get("individual_results") or []):
            summaries = dict(individual_result.get("mode_summaries") or {})
            individual_info = dict(individual_result.get("individual") or {})
            for mode_name, summary in summaries.items():
                writer.writerow(
                    {
                        "experiment_type": results.get("experiment_type"),
                        "timestamp": results.get("timestamp"),
                        "prompt_digest": individual_result.get("prompt_digest"),
                        "individual_id": individual_info.get("id"),
                        "mode": mode_name,
                        "runner_script": "RunLoop_5000.sh",
                        **summary,
                    }
                )


def _build_alignment_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Build per-individual/per-opponent Java-vs-surrogate alignment rows."""
    rows: list[dict[str, Any]] = []
    for individual_result in list(results.get("individual_results") or []):
        individual_info = dict(individual_result.get("individual") or {})
        eagle_by_opponent = {
            row.get("opponent"): row
            for row in list(dict(individual_result.get("modes") or {}).get("eagle_final_test") or [])
            if row.get("opponent")
        }
        surrogate_by_opponent = {
            row.get("opponent"): row
            for row in list(dict(individual_result.get("modes") or {}).get("surrogate_java_final_test") or [])
            if row.get("opponent")
        }
        for opponent in sorted(set(eagle_by_opponent) | set(surrogate_by_opponent)):
            eagle_record = eagle_by_opponent.get(opponent, {})
            surrogate_record = surrogate_by_opponent.get(opponent, {})
            eagle_fitness = list(eagle_record.get("fitness") or [])
            surrogate_fitness = list(surrogate_record.get("fitness") or [])
            win_gap = None
            resource_gap = None
            if eagle_fitness and surrogate_fitness:
                if len(eagle_fitness) > 0 and len(surrogate_fitness) > 0:
                    win_gap = abs(float(eagle_fitness[0]) - float(surrogate_fitness[0]))
                if len(eagle_fitness) > 1 and len(surrogate_fitness) > 1:
                    resource_gap = abs(float(eagle_fitness[1]) - float(surrogate_fitness[1]))
            gap_values = [value for value in [win_gap, resource_gap] if value is not None]
            rows.append(
                {
                    "experiment_type": results.get("experiment_type"),
                    "timestamp": results.get("timestamp"),
                    "prompt_digest": individual_result.get("prompt_digest"),
                    "individual_id": individual_info.get("id"),
                    "opponent": opponent,
                    "eagle_result": eagle_record.get("result"),
                    "surrogate_result": surrogate_record.get("result"),
                    "eagle_win_score": eagle_record.get("win_score"),
                    "surrogate_win_score": surrogate_record.get("win_score"),
                    "eagle_resource_advantage_score": eagle_record.get("resource_advantage_score"),
                    "surrogate_resource_advantage_score": surrogate_record.get("resource_advantage_score"),
                    "win_score_abs_gap": win_gap,
                    "resource_advantage_score_abs_gap": resource_gap,
                    "mean_abs_gap": _average(gap_values),
                    "same_result_label": eagle_record.get("result") == surrogate_record.get("result")
                    if eagle_record and surrogate_record
                    else None,
                }
            )
    return rows


def _write_alignment_csv(log_dir: Path, results: dict[str, Any]) -> None:
    """Write per-individual/per-opponent Java-vs-surrogate alignment rows."""
    rows = _build_alignment_rows(results)
    fieldnames = [
        "experiment_type",
        "timestamp",
        "prompt_digest",
        "individual_id",
        "opponent",
        "eagle_result",
        "surrogate_result",
        "eagle_win_score",
        "surrogate_win_score",
        "eagle_resource_advantage_score",
        "surrogate_resource_advantage_score",
        "win_score_abs_gap",
        "resource_advantage_score_abs_gap",
        "mean_abs_gap",
        "same_result_label",
    ]
    output_path = log_dir / "surrogate_validation_alignment.csv"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_alignment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate alignment quality across all individuals and opponents."""
    if not rows:
        return {
            "pair_count": 0,
            "same_result_rate": None,
            "avg_win_score_abs_gap": None,
            "avg_resource_advantage_score_abs_gap": None,
            "avg_mean_abs_gap": None,
        }
    same_result_flags = [bool(row.get("same_result_label")) for row in rows if row.get("same_result_label") is not None]
    return {
        "pair_count": len(rows),
        "same_result_rate": _average([1.0 if flag else 0.0 for flag in same_result_flags]) if same_result_flags else None,
        "avg_win_score_abs_gap": _average(
            [value for value in [_safe_float(row.get("win_score_abs_gap")) for row in rows] if value is not None]
        ),
        "avg_resource_advantage_score_abs_gap": _average(
            [value for value in [_safe_float(row.get("resource_advantage_score_abs_gap")) for row in rows] if value is not None]
        ),
        "avg_mean_abs_gap": _average(
            [value for value in [_safe_float(row.get("mean_abs_gap")) for row in rows] if value is not None]
        ),
    }


def run_surrogate_validation_smoke_test(
    *,
    config: EAConfig | None = None,
    num_individuals: int = 1,
) -> dict[str, Any]:
    """Run a fast surrogate smoke test without launching full Java matches."""
    config = config or EAConfig()
    log_dir = _make_smoke_log_dir()
    component_pool = ComponentPool.from_json(_resolve_component_pool_path())
    microrts_root = locate_microrts_root()
    results: dict[str, Any] = {
        "experiment_type": "surrogate_validation_smoke",
        "timestamp": datetime.now().isoformat(),
        "log_dir": str(log_dir),
        "component_pool_path": _resolve_component_pool_path(),
        "microrts_root": str(microrts_root),
        "num_individuals": int(num_individuals),
        "individual_results": [],
    }

    required_java_files = {
        "eagle_java": microrts_root / "src" / "ai" / "abstraction" / "EAGLE.java",
        "eagle_surrogate_java": microrts_root / "src" / "ai" / "abstraction" / "EAGLESurrogate.java",
        "config_properties": microrts_root / "resources" / "config.properties",
    }

    for individual_index in range(max(1, int(num_individuals))):
        individual, prompt = _build_random_prompt_artifacts(component_pool, config)
        policy, surrogate_spec = compile_prompt_to_surrogate_spec(prompt)
        individual_dir = log_dir / f"individual_{individual_index:03d}_{individual.id}"
        individual_dir.mkdir(parents=True, exist_ok=True)
        (individual_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (individual_dir / "policy.json").write_text(
            json.dumps(policy, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (individual_dir / "surrogate_spec.json").write_text(
            json.dumps(surrogate_spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (individual_dir / "individual.json").write_text(
            json.dumps(
                {
                    "id": individual.id,
                    "game_rule": individual.game_rule,
                    "strategy": dict(individual.strategy),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        results["individual_results"].append(
            {
                "individual_index": individual_index,
                "prompt_digest": _prompt_digest(prompt),
                "prompt_line_count": len(prompt.splitlines()),
                "individual": {
                    "id": individual.id,
                    "game_rule": individual.game_rule,
                    "strategy": dict(individual.strategy),
                },
                "compiled_policy": policy,
                "surrogate_spec": surrogate_spec,
                "checks": {
                    "microrts_root_exists": microrts_root.exists(),
                    "required_java_files": {
                        name: path.exists()
                        for name, path in required_java_files.items()
                    },
                },
            }
        )

    (log_dir / "surrogate_validation_smoke_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results


def _history_record_to_result(
    *,
    opponent: str,
    benchmark_mode: str,
    history_record: dict[str, Any],
) -> dict[str, Any]:
    """Convert one cached history row into the experiment result schema."""
    fitness = list(history_record.get("fitness_score") or [0.0, 0.0])
    return {
        "opponent": opponent,
        "benchmark_mode": benchmark_mode,
        "fitness": fitness,
        "result": _result_label_from_fitness(fitness),
        "win_score": fitness[0] if len(fitness) > 0 else 0.0,
        "resource_advantage_score": fitness[1] if len(fitness) > 1 else 0.0,
        "game_time_sec": history_record.get("game_time_sec"),
        "log_path": history_record.get("log_path"),
        "winner": history_record.get("winner"),
        "timeout": history_record.get("timeout"),
        "llm_calls": history_record.get("llm_calls"),
        "parsed_summary": history_record.get("parsed_summary"),
        "stats": history_record.get("stats"),
        "llm_interval": history_record.get("llm_interval"),
        "run_time_per_game_sec": history_record.get("run_time_per_game_sec"),
        "runner_script": history_record.get("runner_script"),
        "ai1": history_record.get("ai1"),
        "ai2": history_record.get("ai2"),
        "history_key": history_record.get("history_key"),
        "cached": True,
    }


def _maybe_reuse_cached_match(
    recorder: FitnessRecorder,
    *,
    prompt: str,
    opponent: str,
    benchmark_mode: str,
) -> dict[str, Any] | None:
    """Reuse a prior prompt/opponent/mode match when history already has it."""
    matches = recorder.find_matching_history(prompt, opponent)
    for match in reversed(matches):
        if match.get("benchmark_mode") != benchmark_mode:
            continue
        if match.get("game_time_sec") is None:
            continue
        return _history_record_to_result(
            opponent=opponent,
            benchmark_mode=benchmark_mode,
            history_record=match,
        )
    return None


def _record_match(
    recorder: FitnessRecorder,
    *,
    prompt: str,
    opponent: str,
    benchmark_mode: str,
    fitness: list[float],
    game_time_sec: float,
    log_path: str | None,
    metadata: dict[str, Any] | None = None,
    stats: dict[str, float] | None = None,
    llm_interval: int | None = None,
    ai1: str | None = None,
    runner_script: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one benchmark match so future reruns can reuse its result."""
    metadata = dict(metadata or {})
    parsed_log = metadata.get("parsed_log") if isinstance(metadata.get("parsed_log"), dict) else None
    parsed_summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else None
    final_tick = _infer_final_tick(parsed_log)
    ai2 = opponent
    record = {
        "individual_id": None,
        "generation": None,
        "prompt": prompt,
        "fitness": list(fitness),
        "fitness_score": list(fitness),
        "opponent": opponent,
        "evaluation_mode": "real",
        "benchmark_mode": benchmark_mode,
        "evaluation_time": float(game_time_sec),
        "game_time_sec": float(game_time_sec),
        "final_tick": final_tick,
        "max_cycles": parsed_summary.get("max_cycles") if isinstance(parsed_summary, dict) else None,
        "log_path": log_path,
        "winner": metadata.get("winner"),
        "timeout": metadata.get("timeout"),
        "llm_calls": metadata.get("llm_calls"),
        "parsed_summary": parsed_summary,
        "stats": dict(stats or {}),
        "llm_interval": llm_interval,
        "run_time_per_game_sec": int(recorder.config.run_time_per_game_sec),
        "runner_script": runner_script,
        "ai1": ai1,
        "ai2": ai2,
        "components": {},
    }
    if isinstance(extra, dict):
        record.update(extra)
    recorder.record_fitness(record)
    result = {
        "opponent": opponent,
        "benchmark_mode": benchmark_mode,
        "fitness": list(fitness),
        "result": _result_label_from_fitness(fitness),
        "win_score": fitness[0] if len(fitness) > 0 else 0.0,
        "resource_advantage_score": fitness[1] if len(fitness) > 1 else 0.0,
        "game_time_sec": float(game_time_sec),
        "final_tick": final_tick,
        "max_cycles": parsed_summary.get("max_cycles") if isinstance(parsed_summary, dict) else None,
        "log_path": log_path,
        "winner": metadata.get("winner"),
        "timeout": metadata.get("timeout"),
        "llm_calls": metadata.get("llm_calls"),
        "parsed_summary": parsed_summary,
        "stats": dict(stats or {}),
        "llm_interval": llm_interval,
        "run_time_per_game_sec": int(recorder.config.run_time_per_game_sec),
        "runner_script": runner_script,
        "ai1": ai1,
        "ai2": ai2,
        "trace_xml_path": metadata.get("trace_xml_path"),
        "trace_json_path": metadata.get("trace_json_path"),
        "cached": False,
    }
    if isinstance(extra, dict):
        result.update(extra)
    return result


def _run_eagle_match(
    evaluator: Evaluator,
    recorder: FitnessRecorder,
    *,
    prompt: str,
    opponent: str,
    llm_interval: int,
) -> dict[str, Any]:
    """Run one 5000-cycle benchmark match with the real EAGLE Java agent."""
    ai1 = "ai.abstraction.EAGLE"

    cached = _maybe_reuse_cached_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="eagle_final_test",
    )
    if cached is not None:
        return cached

    stats: dict[str, float] = {}
    started = time.perf_counter()
    fitness, metadata = evaluator.run_prompt_match(
        prompt=prompt,
        opponent=opponent,
        llm_interval=llm_interval,
        test=True,
        stats=stats,
    )
    elapsed = time.perf_counter() - started
    log_path = metadata.get("log_path")

    return _record_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="eagle_final_test",
        fitness=fitness,
        game_time_sec=elapsed,
        log_path=log_path,
        metadata=metadata,
        stats=stats,
        llm_interval=llm_interval,
        ai1=ai1,
        runner_script="RunLoop_5000.sh",
    )


def _run_surrogate_java_match(
    evaluator: Evaluator,
    recorder: FitnessRecorder,
    *,
    prompt: str,
    opponent: str,
    llm_interval: int,
) -> dict[str, Any]:
    """Run one 5000-cycle benchmark match with the generated surrogate Java agent."""
    ai1 = "ai.abstraction.EAGLESurrogate"

    cached = _maybe_reuse_cached_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="surrogate_java_final_test",
    )
    if cached is not None:
        return cached

    stats: dict[str, float] = {}
    started = time.perf_counter()
    java_fitness, metadata = evaluator.run_surrogate_match(
        prompt=prompt,
        opponent=opponent,
        llm_interval=llm_interval,
        stats=stats,
        test=True,
    )
    elapsed = time.perf_counter() - started
    fitness = list(java_fitness)

    return _record_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="surrogate_java_final_test",
        fitness=fitness,
        game_time_sec=elapsed,
        log_path=metadata.get("log_path"),
        metadata=metadata,
        stats=stats,
        llm_interval=llm_interval,
        ai1=ai1,
        runner_script="RunLoop_5000.sh",
        extra={
            "java_match_fitness": list(java_fitness),
            "java_match_win_score": float(java_fitness[0]) if len(java_fitness) > 0 else 0.0,
            "java_match_resource_advantage_score": float(java_fitness[1]) if len(java_fitness) > 1 else 0.0,
        },
    )


def run_surrogate_validation_experiment(
    *,
    config: EAConfig | None = None,
    opponents: list[str] | None = None,
    num_individuals: int = 1,
) -> dict[str, Any]:
    """Compare multiple random EA-style prompts under final-test and surrogate-Java matches."""
    config = config or EAConfig()
    log_dir = _make_experiment_log_dir()
    component_pool = ComponentPool.from_json(_resolve_component_pool_path())
    evaluator = Evaluator(component_pool, config, runtime_logs_dir=log_dir / "microrts")
    recorder = FitnessRecorder(log_dir, config)

    opponents = list(opponents or OPPONENT_LIST)
    llm_interval = int(config.llm_interval)

    results = {
        "experiment_type": "surrogate_validation",
        "timestamp": datetime.now().isoformat(),
        "log_dir": str(log_dir),
        "llm_interval": llm_interval,
        "run_time_per_game_sec": int(config.run_time_per_game_sec),
        "population_size": int(config.population_size),
        "num_generations": int(config.num_generations),
        "num_individuals": int(num_individuals),
        "component_pool_path": _resolve_component_pool_path(),
        "opponents": opponents,
        "history_cache_schema_version": 4,
        "individual_results": [],
        "alignment_summary": {},
    }

    for individual_index in range(int(num_individuals)):
        individual, prompt = _build_random_prompt_artifacts(component_pool, config)
        individual_result = {
            "individual_index": individual_index,
            "prompt": prompt,
            "prompt_digest": _prompt_digest(prompt),
            "prompt_line_count": len(prompt.splitlines()),
            "individual": {
                "id": individual.id,
                "game_rule": individual.game_rule,
                "strategy": dict(individual.strategy),
            },
            "modes": {
                "eagle_final_test": [],
                "surrogate_java_final_test": [],
            },
            "mode_summaries": {},
        }

        individual_dir = log_dir / f"individual_{individual_index:03d}_{individual.id}"
        individual_dir.mkdir(parents=True, exist_ok=True)
        (individual_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (individual_dir / "individual.json").write_text(
            json.dumps(individual_result["individual"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        results["individual_results"].append(individual_result)

        for opponent in opponents:
            individual_result["modes"]["eagle_final_test"].append(
                _run_eagle_match(
                    evaluator,
                    recorder,
                    prompt=prompt,
                    opponent=opponent,
                    llm_interval=llm_interval,
                )
            )
            individual_result["modes"]["surrogate_java_final_test"].append(
                _run_surrogate_java_match(
                    evaluator,
                    recorder,
                    prompt=prompt,
                    opponent=opponent,
                    llm_interval=llm_interval,
                )
            )
            individual_result["mode_summaries"] = {
                mode_name: _build_mode_summary(mode_records)
                for mode_name, mode_records in individual_result["modes"].items()
            }
            alignment_rows = _build_alignment_rows(results)
            results["alignment_summary"] = _build_alignment_summary(alignment_rows)
            (log_dir / "surrogate_validation_results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _write_match_results_csv(log_dir, results)
            _write_mode_summary_csv(log_dir, results)
            _write_alignment_csv(log_dir, results)

        alignment_rows = _build_alignment_rows(results)
        results["alignment_summary"] = _build_alignment_summary(alignment_rows)
        (log_dir / "surrogate_validation_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_match_results_csv(log_dir, results)
        _write_mode_summary_csv(log_dir, results)
        _write_alignment_csv(log_dir, results)

    return results


def run_surrogate_validation_quick_run(
    *,
    config: EAConfig | None = None,
    opponents: list[str] | None = None,
) -> dict[str, Any]:
    """Run the smallest real surrogate-validation benchmark that still launches games."""
    selected_opponents = list(opponents or [DEFAULT_QUICK_RUN_OPPONENT])
    if not selected_opponents:
        selected_opponents = [DEFAULT_QUICK_RUN_OPPONENT]
    return run_surrogate_validation_experiment(
        config=config,
        opponents=selected_opponents[:1],
        num_individuals=1,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI for the surrogate-validation experiment."""
    parser = argparse.ArgumentParser(
        description="Compare one random EA-style prompt under EAGLE final-test and surrogate-Java benchmark matches.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Load one surrogate-validation config JSON file. "
            f"Defaults to {DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH.as_posix()} when present."
        ),
    )
    parser.add_argument(
        "--opponent",
        action="append",
        default=None,
        help="Optional opponent override. Repeat to benchmark multiple opponents.",
    )
    parser.add_argument(
        "--num-individuals",
        type=int,
        default=1,
        help="How many random EA-style individuals to benchmark in one experiment run.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=DEFAULT_SURROGATE_VALIDATION_TIMEOUT_SEC,
        help="Per-game timeout in seconds for surrogate-validation matches.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a fast smoke test that validates surrogate prompt/spec and MicroRTS paths without launching games.",
    )
    parser.add_argument(
        "--quick-run",
        action="store_true",
        help="Run one individual against one opponent using real matches for a minimal end-to-end benchmark.",
    )
    return parser


def main() -> None:
    """CLI entry point for the surrogate-validation experiment."""
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.config:
        config = load_config_from_json(args.config)
    elif DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH.exists():
        config = load_config_from_json(DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH)
    else:
        config = EAConfig()
    config.run_time_per_game_sec = max(1, int(args.timeout_sec))
    config.validate()
    if args.smoke_test:
        results = run_surrogate_validation_smoke_test(
            config=config,
            num_individuals=max(1, int(args.num_individuals)),
        )
    elif args.quick_run:
        results = run_surrogate_validation_quick_run(
            config=config,
            opponents=args.opponent,
        )
    else:
        results = run_surrogate_validation_experiment(
            config=config,
            opponents=args.opponent,
            num_individuals=max(1, int(args.num_individuals)),
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
