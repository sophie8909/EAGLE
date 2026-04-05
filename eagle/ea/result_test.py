"""Utilities for replaying and evaluating one saved generation on demand."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .component_pool import ComponentPool
from .config import EAConfig
from .ea_log_parse import parse_individuals_from_ea_log
from .evaluate import Evaluator
from .main import OPPONENT_LIST


def resolve_generation_log_path(log_dir: str | Path, generation: int) -> Path:
    """Resolve the saved generation log path for one NSGA-II generation."""
    log_dir_path = Path(log_dir)
    return log_dir_path / f"generation_{generation}_mo.txt"


def extract_front_one_individual_ids(generation_log_path: str | Path) -> list[str]:
    """Extract the individual ids that belong to Pareto Front 1 in one generation log."""
    generation_log = Path(generation_log_path)
    lines = generation_log.read_text(encoding="utf-8").splitlines()

    front_one_ids: list[str] = []
    in_front_one = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("Pareto Front "):
            in_front_one = line == "Pareto Front 1:"
            continue
        if not in_front_one or not line.startswith("Individual"):
            continue

        start_idx = line.find("id=")
        if start_idx == -1:
            continue
        end_idx = line.find(",", start_idx)
        if end_idx == -1:
            end_idx = line.find(")", start_idx)
        if end_idx == -1:
            continue
        front_one_ids.append(line[start_idx + len("id="):end_idx].strip())

    return front_one_ids


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
        "resource_advantage": fitness_score[1],
        "game_round_score": fitness_score[2],
        "log_path": log_path,
    }


def filter_individuals(
    individuals,
    *,
    individual_id: str | None = None,
    only_winning_individuals: bool = False,
    allowed_individual_ids: set[str] | None = None,
):
    """Filter generation individuals by id and/or their stored first objective."""
    filtered = []
    for individual in individuals:
        if allowed_individual_ids is not None and individual.id not in allowed_individual_ids:
            continue
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
    front_only: int | None = 1,
    output_path: str | Path | None = None,
) -> dict:
    """Replay one saved generation and write per-opponent evaluation results."""
    log_dir_path = Path(log_dir)
    component_pool_path = log_dir_path / "component_pool.json"
    if not component_pool_path.exists():
        raise FileNotFoundError(f"Component pool not found: {component_pool_path}")

    evaluator = Evaluator(
        ComponentPool.from_json(str(component_pool_path)),
        EAConfig(),
    )
    generation_log_path = resolve_generation_log_path(log_dir_path, generation)
    individuals = load_generation_individuals(log_dir_path, generation)
    allowed_individual_ids: set[str] | None = None
    if front_only == 1:
        allowed_individual_ids = set(extract_front_one_individual_ids(generation_log_path))

    selected_individuals = filter_individuals(
        individuals,
        individual_id=individual_id,
        only_winning_individuals=only_winning_individuals,
        allowed_individual_ids=allowed_individual_ids,
    )

    results = {
        "generation": generation,
        "log_dir": str(log_dir_path),
        "individual_count": len(selected_individuals),
        "front_only": front_only,
        "opponents": list(opponents or OPPONENT_LIST),
        "results": {},
    }

    for individual in selected_individuals:
        prompt = evaluator.construct_prompt(individual)
        evaluator.save_prompt(prompt)

        for opponent in results["opponents"]:
            print(f"Testing generation {generation}, individual {individual.id} against opponent: {opponent}")
            evaluator.set_opponent(opponent)

            process = evaluator.launch_simulation(test=True)
            evaluator.wait_for_simulation(process)

            latest_log_file = evaluator.get_latest_log_file()
            if not latest_log_file:
                continue

            with open(latest_log_file, "r", encoding="utf-8") as f:
                log_content = f.read()

            fitness_score = evaluator.calculate_fitness_score(log_content)
            results["results"].setdefault(individual.id, [])
            results["results"][individual.id].append(
                build_result_record(
                    individual,
                    opponent,
                    fitness_score,
                    str(latest_log_file),
                )
            )

            destination = (
                Path(output_path)
                if output_path is not None
                else log_dir_path / f"generation_{generation}_front_{front_only if front_only is not None else 'all'}_result_test.json"
            )
            with open(destination, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4)

    return results


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI used for replaying one saved generation."""
    parser = argparse.ArgumentParser(description="Replay one saved generation and collect result-test outputs.")
    parser.add_argument("--log-dir", required=True, help="Path to one EA experiment log directory.")
    parser.add_argument("--generation", required=True, type=int, help="Saved generation number to replay.")
    parser.add_argument("--opponent", action="append", default=None, help="Optional opponent override. Repeat to test multiple opponents.")
    parser.add_argument("--individual-id", default=None, help="Optional individual id to replay from the generation.")
    parser.add_argument(
        "--only-winning-individuals",
        action="store_true",
        help="Replay only individuals whose stored first objective equals 1.0.",
    )
    parser.add_argument(
        "--all-fronts",
        action="store_true",
        help="Replay all individuals in the generation instead of only Pareto Front 1.",
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
        front_only=None if args.all_fronts else 1,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
