"""Utilities for replaying and evaluating one saved generation on demand."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from ...main import OPPONENT_LIST
from ...project import DEFAULT_FINAL_TEST_CONFIG_PATH
from ...utils.component_pool import ComponentPool
from ...evolution.component.log_parse import parse_individuals_from_ea_log, parse_population_snapshot_from_ea_log
from .full_game_evaluator import FullGameEvaluator
from .replay_common import (
    build_interval_runs,
    load_runtime_config,
    write_results_snapshot,
)

# CLI examples:
# `py -m eagle.eval.microrts.generation_replay --log-dir logs/eagle/20260409_123456 --generation 20`
# `py -m eagle.eval.microrts.generation_replay --log-dir logs/eagle/20260409_123456 --generation 20 --config configs/evaluation/final_test.json`


def parse_max_front_arg(raw_value: str) -> int | None:
    """Parse CLI front-cutoff values such as `1`, `3`, or `all`."""
    normalized = str(raw_value).strip().lower()
    if normalized == "all":
        return None

    value = int(normalized)
    if value < 1:
        return None
    return value


def resolve_generation_log_path(log_dir: str | Path, generation: int) -> Path:
    """Resolve the saved generation log path for one NSGA-II generation."""
    log_dir_path = Path(log_dir)
    return log_dir_path / f"generation_{generation}_mo.txt"

def extract_individual_ids_up_to_front(
    generation_log_path: str | Path,
    max_front: int | None,
) -> list[str]:
    """Extract ids that belong to Pareto Front 1 up to the requested front."""
    if max_front is None:
        max_front = float("inf")
    if max_front < 1:
        max_front = float("inf")

    generation_log = Path(generation_log_path)
    lines = generation_log.read_text(encoding="utf-8").splitlines()

    selected_ids: list[str] = []
    current_front: int | None = None
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("Pareto Front "):
            front_label = line.removeprefix("Pareto Front ").removesuffix(":").strip()
            try:
                current_front = int(front_label)
            except ValueError:
                current_front = None
            continue
        if current_front is None or current_front > max_front or not line.startswith("Individual"):
            continue

        start_idx = line.find("id=")
        if start_idx == -1:
            continue
        end_idx = line.find(",", start_idx)
        if end_idx == -1:
            end_idx = line.find(")", start_idx)
        if end_idx == -1:
            continue
        selected_ids.append(line[start_idx + len("id="):end_idx].strip())

    return selected_ids


def load_generation_individuals(log_dir: str | Path, generation: int):
    """Load all serialized individuals stored in one saved generation log."""
    generation_log_path = resolve_generation_log_path(log_dir, generation)
    if not generation_log_path.exists():
        raise FileNotFoundError(f"Generation log not found: {generation_log_path}")
    population_snapshot = parse_population_snapshot_from_ea_log(str(generation_log_path))
    if population_snapshot:
        return population_snapshot

    individuals_by_front = parse_individuals_from_ea_log(str(generation_log_path))
    seen_ids: set[str] = set()
    deduplicated: list = []
    for front in individuals_by_front:
        for individual in front:
            if individual.id in seen_ids:
                continue
            seen_ids.add(individual.id)
            deduplicated.append(individual)
    return deduplicated


def build_result_record(
    individual,
    opponent: str,
    match_score: dict,
    log_path: str,
    trace_xml_path: str | None = None,
    trace_json_path: str | None = None,
) -> dict:
    """Convert one replay result into the JSON-friendly output schema."""
    win_score = _match_win_score(match_score)
    resource_score = _match_resource_advantage_score(match_score)
    if win_score == 1.0:
        result = "Win"
    elif win_score == -1.0:
        result = "Loss"
    else:
        result = "Draw"

    return {
        "individual_id": individual.id,
        "opponent": opponent,
        "result": result,
        "raw": {
            "win_score": win_score,
            "score": resource_score,
        },
        "paths": {
            "log": log_path,
            "trace_xml": trace_xml_path,
            "trace_json": trace_json_path,
        },
    }


def _match_win_score(match_score: dict | None) -> float:
    if not isinstance(match_score, dict):
        return 0.0
    try:
        return float(match_score.get("win_score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _match_resource_advantage_score(match_score: dict | None) -> float:
    if not isinstance(match_score, dict):
        return 0.0
    try:
        return float(match_score.get("raw_resource_advantage_score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _append_result(results: dict, individual_id: str, result_record: dict) -> None:
    """Append one replay result row under the target individual id."""
    results["results"].setdefault(individual_id, [])
    results["results"][individual_id].append(result_record)


def filter_individuals(
    individuals,
    *,
    individual_id: str | None = None,
    only_winning_individuals: bool = False,
):
    """Filter generation individuals by id and/or their stored first objective."""
    filtered = []
    for individual in individuals:
        if individual_id is not None and individual.id != individual_id:
            continue
        if only_winning_individuals and individual.fitness[0] != 1.0:
            continue
        filtered.append(individual)
    return filtered


def run_generation_result_test(
    log_dir: str | Path,
    generation: int,
    *,
    opponents: Iterable[str] | None = None,
    individual_id: str | None = None,
    only_winning_individuals: bool = False,
    max_front: int | None = 1,
    output_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict:
    """Replay one saved generation and write per-opponent evaluation results."""
    log_dir_path = Path(log_dir)
    component_pool_path = log_dir_path / "component_pool.json"
    if not component_pool_path.exists():
        raise FileNotFoundError(f"Component pool not found: {component_pool_path}")

    runtime_config = load_runtime_config(log_dir_path, config_path)
    evaluator = FullGameEvaluator(
        ComponentPool.from_json(str(component_pool_path)),
        runtime_config,
    )
    generation_log_path = resolve_generation_log_path(log_dir_path, generation)
    individuals = load_generation_individuals(log_dir_path, generation)
    allowed_individual = individuals
    selected_individuals = filter_individuals(
        allowed_individual,
        individual_id=individual_id,
        only_winning_individuals=only_winning_individuals,
    )

    interval_runs = build_interval_runs(config_path, runtime_config.llm_interval)
    final_test_llm_call_limit = None
    resolved_opponents = list(opponents or OPPONENT_LIST)
    results = {
        "generation": generation,
        "log_dir": str(log_dir_path),
        "individual_count": len(selected_individuals),
        "max_front": max_front,
        "opponents": resolved_opponents,
        "test_config_path": str(Path(config_path) if config_path is not None else DEFAULT_FINAL_TEST_CONFIG_PATH),
        "tick_limit": int(runtime_config.tick_limit),
        "llm_call_limit": final_test_llm_call_limit,
        "interval_runs": interval_runs,
        "results": {},
    }

    for individual in selected_individuals:
        prompt = evaluator._construct_prompt(individual)

        for interval_run in interval_runs:
            llm_interval = int(interval_run["llm_interval"])

            for opponent in resolved_opponents:
                print(
                    f"Testing generation {generation}, individual {individual.id} "
                    f"against opponent: {opponent} (llm_interval={llm_interval})"
                )
                result = evaluator.run_prompt_based_agent(
                    prompt=prompt,
                    opponent=opponent,
                    generation=generation,
                    llm_interval=llm_interval,
                    llm_call_limit=final_test_llm_call_limit,
                    test=True,
                )
                match_score = dict(result["match_score"])
                metadata = dict(result.get("simulation_meta") or {})
                result_record = build_result_record(
                    individual,
                    opponent,
                    match_score,
                    str(metadata.get("log_path")),
                    trace_xml_path=str(metadata.get("trace_xml_path")) if metadata.get("trace_xml_path") else None,
                    trace_json_path=str(metadata.get("trace_json_path")) if metadata.get("trace_json_path") else None,
                )
                result_record["runtime"] = {
                    "interval_mode": str(interval_run["label"]),
                    "llm_interval": llm_interval,
                }
                _append_result(results, individual.id, result_record)

                destination = (
                    Path(output_path)
                    if output_path is not None
                    else log_dir_path / f"generation_{generation}_front_{max_front if max_front is not None else 'all'}_result_test.json"
                )
                write_results_snapshot(results, destination)
    
        # java agent test final result
        for opponent in resolved_opponents:
            print(
                f"Testing generation {generation}, individual {individual.id} "
                f"against opponent: {opponent} (java agent test)"
            )
            result = evaluator.run_java_based_agent(
                prompt=prompt,
                opponent=opponent,
                generation=generation,
                llm_call_limit=final_test_llm_call_limit,
                test=True,
            )
            match_score = dict(result["match_score"])
            metadata = dict(result.get("simulation_meta") or {})

            result_record = build_result_record(
                individual,
                opponent,
                match_score,
                str(metadata.get("log_path")),
                trace_xml_path=str(metadata.get("trace_xml_path")) if metadata.get("trace_xml_path") else None,
                trace_json_path=str(metadata.get("trace_json_path")) if metadata.get("trace_json_path") else None,
            )
            result_record["runtime"] = {
                "interval_mode": "java_agent_test",
                "llm_interval": None,
            }
            _append_result(results, individual.id, result_record)

            destination = (
                Path(output_path)
                if output_path is not None
                else log_dir_path / f"generation_{generation}_front_{max_front if max_front is not None else 'all'}_result_test.json"
            )
            write_results_snapshot(results, destination)

    return results


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI used for replaying one saved generation."""
    parser = argparse.ArgumentParser(description="Replay one saved generation and collect result-test outputs.")
    parser.add_argument("--log-dir", required=True, help="Path to one EA experiment log directory.")
    parser.add_argument("--generation", required=True, type=int, help="Saved generation number to replay.")
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Optional replay/final-test override JSON. Defaults to "
            f"{DEFAULT_FINAL_TEST_CONFIG_PATH.as_posix()} when present."
        ),
    )
    parser.add_argument("--opponent", action="append", default=None, help="Optional opponent override. Repeat to test multiple opponents.")
    parser.add_argument("--individual-id", default=None, help="Optional individual id to replay from the generation.")
    parser.add_argument(
        "--only-winning-individuals",
        action="store_true",
        help="Replay only individuals whose stored first objective equals 1.0.",
    )
    parser.add_argument(
        "--max-front",
        type=parse_max_front_arg,
        default=1,
        help="Replay individuals in Pareto Front 1 up to this front number, or use 'all'.",
    )
    parser.add_argument(
        "--all-fronts",
        action="store_true",
        help="Replay all individuals in the generation regardless of Pareto front.",
    )
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    return parser


def main() -> None:
    """Parse CLI arguments and run the requested generation result test."""
    parser = build_argument_parser()
    args = parser.parse_args()
    run_generation_result_test(
        args.log_dir,
        args.generation,
        opponents=args.opponent,
        individual_id=args.individual_id,
        only_winning_individuals=args.only_winning_individuals,
        max_front=None if args.all_fronts else args.max_front,
        output_path=args.output,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()
