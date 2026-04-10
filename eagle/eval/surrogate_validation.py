"""Run one prompt-level benchmark comparing EAGLE vs surrogate Java-agent matches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import EAConfig
from ..main import OPPONENT_LIST, _resolve_component_pool_path
from ..tools.component_pool import ComponentPool
from ..tools.fitness_recorder import FitnessRecorder
from ..tools.individual import Individual
from ..tools.simulation_runner import (
    set_ai1,
    simulate_surrogate_games,
    simulate_games,
)
from .evaluate import Evaluator


def _build_random_prompt_artifacts(config: EAConfig) -> tuple[ComponentPool, Individual, str]:
    """Create one random EA-style individual and render its prompt."""
    component_pool = ComponentPool.from_json(_resolve_component_pool_path())
    individual = Individual()
    individual.initialize_randomly(component_pool)
    evaluator = Evaluator(component_pool, config)
    prompt = evaluator.construct_prompt(individual)
    return component_pool, individual, prompt


def _make_experiment_log_dir() -> Path:
    """Create the output directory for one surrogate-validation experiment run."""
    repo_root = Path(__file__).resolve().parents[2]
    log_dir = repo_root / "eagle" / "logs" / f"surrogate_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
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


def _build_mode_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one benchmark mode into compact summary statistics."""
    if not records:
        return {
            "match_count": 0,
            "cached_match_count": 0,
            "avg_win_score": None,
            "avg_game_round_score": None,
            "avg_resource_advantage_score": None,
            "avg_game_time_sec": None,
            "win_count": 0,
            "draw_count": 0,
            "loss_count": 0,
        }

    return {
        "match_count": len(records),
        "cached_match_count": sum(1 for record in records if record.get("cached")),
        "avg_win_score": _average([float(record.get("win_score", 0.0)) for record in records]),
        "avg_game_round_score": _average([float(record.get("game_round_score", 0.0)) for record in records]),
        "avg_resource_advantage_score": _average(
            [float(record.get("resource_advantage_score", 0.0)) for record in records]
        ),
        "avg_game_time_sec": _average(
            [float(record.get("game_time_sec", 0.0)) for record in records if record.get("game_time_sec") is not None]
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


def _write_match_results_csv(log_dir: Path, results: dict[str, Any]) -> None:
    """Write one flat per-match CSV for downstream plotting and spreadsheet analysis."""
    rows: list[dict[str, Any]] = []
    for mode_name, records in dict(results.get("modes") or {}).items():
        for record in records:
            rows.append(
                {
                    "experiment_type": results.get("experiment_type"),
                    "timestamp": results.get("timestamp"),
                    "prompt_digest": results.get("prompt_digest"),
                    "individual_id": dict(results.get("individual") or {}).get("id"),
                    "mode": mode_name,
                    "benchmark_mode": record.get("benchmark_mode"),
                    "opponent": record.get("opponent"),
                    "result": record.get("result"),
                    "win_score": record.get("win_score"),
                    "game_round_score": record.get("game_round_score"),
                    "resource_advantage_score": record.get("resource_advantage_score"),
                    "game_time_sec": record.get("game_time_sec"),
                    "winner": record.get("winner"),
                    "timeout": record.get("timeout"),
                    "llm_calls": record.get("llm_calls"),
                    "llm_interval": record.get("llm_interval"),
                    "run_time_per_game_sec": record.get("run_time_per_game_sec"),
                    "ai1": record.get("ai1"),
                    "ai2": record.get("ai2"),
                    "cached": record.get("cached"),
                    "log_path": record.get("log_path"),
                }
            )

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
        "game_round_score",
        "resource_advantage_score",
        "game_time_sec",
        "winner",
        "timeout",
        "llm_calls",
        "llm_interval",
        "run_time_per_game_sec",
        "ai1",
        "ai2",
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
        "mode",
        "match_count",
        "cached_match_count",
        "avg_win_score",
        "avg_game_round_score",
        "avg_resource_advantage_score",
        "avg_game_time_sec",
        "win_count",
        "draw_count",
        "loss_count",
    ]
    output_path = log_dir / "surrogate_validation_mode_summary.csv"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for mode_name, summary in summaries.items():
            writer.writerow(
                {
                    "experiment_type": results.get("experiment_type"),
                    "timestamp": results.get("timestamp"),
                    "prompt_digest": results.get("prompt_digest"),
                    "mode": mode_name,
                    **summary,
                }
            )


def _history_record_to_result(
    *,
    opponent: str,
    benchmark_mode: str,
    history_record: dict[str, Any],
) -> dict[str, Any]:
    """Convert one cached history row into the experiment result schema."""
    fitness = list(history_record.get("fitness_score") or [0.0, 0.0, 0.0])
    return {
        "opponent": opponent,
        "benchmark_mode": benchmark_mode,
        "fitness": fitness,
        "result": _result_label_from_fitness(fitness),
        "win_score": fitness[0] if len(fitness) > 0 else 0.0,
        "game_round_score": fitness[1] if len(fitness) > 1 else 0.0,
        "resource_advantage_score": fitness[2] if len(fitness) > 2 else 0.0,
        "game_time_sec": history_record.get("game_time_sec"),
        "log_path": history_record.get("log_path"),
        "winner": history_record.get("winner"),
        "timeout": history_record.get("timeout"),
        "llm_calls": history_record.get("llm_calls"),
        "parsed_summary": history_record.get("parsed_summary"),
        "stats": history_record.get("stats"),
        "llm_interval": history_record.get("llm_interval"),
        "run_time_per_game_sec": history_record.get("run_time_per_game_sec"),
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
) -> dict[str, Any]:
    """Persist one benchmark match so future reruns can reuse its result."""
    metadata = dict(metadata or {})
    parsed_log = metadata.get("parsed_log") if isinstance(metadata.get("parsed_log"), dict) else None
    parsed_summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else None
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
        "log_path": log_path,
        "winner": metadata.get("winner"),
        "timeout": metadata.get("timeout"),
        "llm_calls": metadata.get("llm_calls"),
        "parsed_summary": parsed_summary,
        "stats": dict(stats or {}),
        "llm_interval": llm_interval,
        "run_time_per_game_sec": int(recorder.config.run_time_per_game_sec),
        "ai1": ai1,
        "ai2": ai2,
        "components": {},
    }
    recorder.record_fitness(record)
    return {
        "opponent": opponent,
        "benchmark_mode": benchmark_mode,
        "fitness": list(fitness),
        "result": _result_label_from_fitness(fitness),
        "win_score": fitness[0] if len(fitness) > 0 else 0.0,
        "game_round_score": fitness[1] if len(fitness) > 1 else 0.0,
        "resource_advantage_score": fitness[2] if len(fitness) > 2 else 0.0,
        "game_time_sec": float(game_time_sec),
        "log_path": log_path,
        "winner": metadata.get("winner"),
        "timeout": metadata.get("timeout"),
        "llm_calls": metadata.get("llm_calls"),
        "parsed_summary": parsed_summary,
        "stats": dict(stats or {}),
        "llm_interval": llm_interval,
        "run_time_per_game_sec": int(recorder.config.run_time_per_game_sec),
        "ai1": ai1,
        "ai2": ai2,
        "cached": False,
    }


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

    evaluator.save_prompt(prompt)
    original_interval = evaluator.config.llm_interval
    evaluator.config.llm_interval = llm_interval
    stats: dict[str, float] = {}
    started = time.perf_counter()
    set_ai1(evaluator.repo_root, ai1)
    fitness, metadata = simulate_games(
        repo_root=evaluator.repo_root,
        config=evaluator.config,
        opponent=opponent,
        stats=stats,
        test=True,
    )
    elapsed = time.perf_counter() - started
    evaluator.config.llm_interval = original_interval
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

    original_interval = evaluator.config.llm_interval
    evaluator.config.llm_interval = llm_interval
    stats: dict[str, float] = {}
    started = time.perf_counter()
    set_ai1(evaluator.repo_root, ai1)
    fitness, metadata = simulate_surrogate_games(
        repo_root=evaluator.repo_root,
        config=evaluator.config,
        prompt=prompt,
        opponent=opponent,
        stats=stats,
        test=True,
    )
    elapsed = time.perf_counter() - started
    evaluator.config.llm_interval = original_interval

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
    )


def run_surrogate_validation_experiment(
    *,
    config: EAConfig | None = None,
    opponents: list[str] | None = None,
) -> dict[str, Any]:
    """Compare one random EA-style prompt under final-test and surrogate-Java matches."""
    config = config or EAConfig()
    log_dir = _make_experiment_log_dir()
    component_pool, individual, prompt = _build_random_prompt_artifacts(config)
    evaluator = Evaluator(component_pool, config)
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
        "surrogate_version": str(config.surrogate_version),
        "prompt": prompt,
        "prompt_digest": _prompt_digest(prompt),
        "prompt_line_count": len(prompt.splitlines()),
        "component_pool_path": _resolve_component_pool_path(),
        "individual": {
            "id": individual.id,
            "game_rule": individual.game_rule,
            "strategy": dict(individual.strategy),
        },
        "opponents": opponents,
        "history_cache_schema_version": 3,
        "modes": {
            "eagle_final_test": [],
            "surrogate_java_final_test": [],
        },
        "mode_summaries": {},
    }

    (log_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (log_dir / "individual.json").write_text(
        json.dumps(results["individual"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for opponent in opponents:
        results["modes"]["eagle_final_test"].append(
            _run_eagle_match(
                evaluator,
                recorder,
                prompt=prompt,
                opponent=opponent,
                llm_interval=llm_interval,
            )
        )
        results["modes"]["surrogate_java_final_test"].append(
            _run_surrogate_java_match(
                evaluator,
                recorder,
                prompt=prompt,
                opponent=opponent,
                llm_interval=llm_interval,
            )
        )
        results["mode_summaries"] = {
            mode_name: _build_mode_summary(mode_records)
            for mode_name, mode_records in results["modes"].items()
        }
        (log_dir / "surrogate_validation_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_match_results_csv(log_dir, results)
        _write_mode_summary_csv(log_dir, results)

    return results


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI for the surrogate-validation experiment."""
    parser = argparse.ArgumentParser(
        description="Compare one random EA-style prompt under EAGLE final-test and surrogate-Java benchmark matches.",
    )
    parser.add_argument(
        "--opponent",
        action="append",
        default=None,
        help="Optional opponent override. Repeat to benchmark multiple opponents.",
    )
    return parser


def main() -> None:
    """CLI entry point for the surrogate-validation experiment."""
    parser = build_argument_parser()
    args = parser.parse_args()
    results = run_surrogate_validation_experiment(
        config=EAConfig(),
        opponents=args.opponent,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
