"""Utilities for replaying and evaluating one saved generation on demand."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from ..config import EAConfig, clone_config, load_config_from_json
from ..main import OPPONENT_LIST
from ..project import DEFAULT_FINAL_TEST_CONFIG_PATH
from ..utils.component_pool import ComponentPool
from ..utils.ea_log_parse import parse_individuals_from_ea_log
from .evaluator import Evaluator

# CLI examples:
# `py -m eagle.evaluation.generation_replay --log-dir logs/eagle/20260409_123456 --generation 20`
# `py -m eagle.evaluation.generation_replay --log-dir logs/eagle/20260409_123456 --generation 20 --config configs/evaluation/final_test.json`


def parse_max_front_arg(raw_value: str) -> int | None:
    """Parse CLI front-cutoff values such as `1`, `3`, or `all`."""
    normalized = str(raw_value).strip().lower()
    if normalized == "all":
        return None

    value = int(normalized)
    if value < 1:
        raise argparse.ArgumentTypeError("max front must be >= 1, or use 'all'.")
    return value


def resolve_generation_log_path(log_dir: str | Path, generation: int) -> Path:
    """Resolve the saved generation log path for one NSGA-II generation."""
    log_dir_path = Path(log_dir)
    return log_dir_path / f"generation_{generation}_mo.txt"


def _load_final_test_override_payload(config_path: str | Path | None = None) -> dict:
    """Load the optional replay/final-test override JSON payload."""
    candidate_path = Path(config_path) if config_path is not None else DEFAULT_FINAL_TEST_CONFIG_PATH
    if not candidate_path.exists():
        return {}
    return json.loads(candidate_path.read_text(encoding="utf-8"))


def load_run_config(log_dir: str | Path, config_path: str | Path | None = None) -> EAConfig:
    """Load the saved run config and then overlay test-specific runtime settings."""
    run_config = load_config_from_json(log_dir)
    payload = _load_final_test_override_payload(config_path)
    resolved = clone_config(run_config)
    if "run_time_per_game_sec" in payload:
        resolved.run_time_per_game_sec = int(payload["run_time_per_game_sec"])
    if "llm_interval" in payload:
        resolved.llm_interval = int(payload["llm_interval"])
    resolved.validate()
    return resolved


def build_interval_runs(config_path: str | Path | None, fallback_llm_interval: int) -> list[dict[str, int | str]]:
    """Resolve the replay llm-interval sweep from config or fallback value."""
    payload = _load_final_test_override_payload(config_path)
    configured_intervals = payload.get("llm_intervals")
    if configured_intervals is None:
        configured_intervals = [int(fallback_llm_interval)]

    interval_runs: list[dict[str, int | str]] = []
    seen_intervals: set[int] = set()
    for llm_interval in configured_intervals:
        interval_value = int(llm_interval)
        if interval_value in seen_intervals:
            continue
        seen_intervals.add(interval_value)
        interval_runs.append(
            {
                "label": f"interval_{interval_value}",
                "llm_interval": interval_value,
            }
        )
    return interval_runs


def extract_individual_ids_up_to_front(
    generation_log_path: str | Path,
    max_front: int | None,
) -> list[str]:
    """Extract ids that belong to Pareto Front 1 up to the requested front."""
    if max_front is None:
        return []
    if max_front < 1:
        raise ValueError("max_front must be >= 1 or None.")

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
    return parse_individuals_from_ea_log(str(generation_log_path))


def build_result_record(
    individual,
    opponent: str,
    fitness_score: list[float],
    log_path: str,
) -> dict:
    """Convert one replay result into the JSON-friendly output schema."""
    if fitness_score[0] == 1.0:
        result = "Win"
    elif fitness_score[0] == 0.0:
        result = "Loss"
    else:
        result = "Draw"

    return {
        "individual_id": individual.id,
        "opponent": opponent,
        "result": result,
        "fitness": fitness_score,
        "win_score": fitness_score[0] if len(fitness_score) > 0 else 0.0,
        "game_round_score": fitness_score[1] if len(fitness_score) > 1 else 0.0,
        "resource_advantage_score": fitness_score[2] if len(fitness_score) > 2 else 0.0,
        "log_path": log_path,
    }


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

    runtime_config = load_run_config(log_dir_path, config_path)
    evaluator = Evaluator(
        ComponentPool.from_json(str(component_pool_path)),
        runtime_config,
    )
    generation_log_path = resolve_generation_log_path(log_dir_path, generation)
    individuals = load_generation_individuals(log_dir_path, generation)
    allowed_individual = individuals
    for i, front in enumerate(individuals):
        print(f"Front {i} has {len(front)} individuals.")

    if max_front is not None:
        allowed_individual = individuals[:max_front] if max_front <= len(individuals) else individuals

    # Flatten the list of fronts into a single list of individuals
    flattened = []
    for front in allowed_individual:
        flattened.extend(front)
    allowed_individual = flattened

    print(allowed_individual)
    selected_individuals = filter_individuals(
        allowed_individual,
        individual_id=individual_id,
        only_winning_individuals=only_winning_individuals,
    )

    interval_runs = build_interval_runs(config_path, runtime_config.llm_interval)
    resolved_opponents = list(opponents or OPPONENT_LIST)
    results = {
        "generation": generation,
        "log_dir": str(log_dir_path),
        "individual_count": len(selected_individuals),
        "max_front": max_front,
        "opponents": resolved_opponents,
        "test_config_path": str(Path(config_path) if config_path is not None else DEFAULT_FINAL_TEST_CONFIG_PATH),
        "run_time_per_game_sec": int(runtime_config.run_time_per_game_sec),
        "interval_runs": interval_runs,
        "results": {},
    }

    for individual in selected_individuals:
        prompt = evaluator.construct_prompt(individual)
        evaluator.save_prompt(prompt)

        for interval_run in interval_runs:
            llm_interval = int(interval_run["llm_interval"])
            evaluator.set_llm_interval(llm_interval)

            for opponent in resolved_opponents:
                print(
                    f"Testing generation {generation}, individual {individual.id} "
                    f"against opponent: {opponent} (llm_interval={llm_interval})"
                )
                evaluator.set_opponent(opponent)
                fitness_score, metadata = evaluator.simulate_games(opponent, {})
                results["results"].setdefault(individual.id, [])
                result_record = build_result_record(
                    individual,
                    opponent,
                    fitness_score,
                    str(metadata.get("log_path")),
                )
                result_record["interval_mode"] = str(interval_run["label"])
                result_record["llm_interval"] = llm_interval
                results["results"][individual.id].append(result_record)

                destination = (
                    Path(output_path)
                    if output_path is not None
                    else log_dir_path / f"generation_{generation}_front_{max_front if max_front is not None else 'all'}_result_test.json"
                )
                with open(destination, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=4)

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
