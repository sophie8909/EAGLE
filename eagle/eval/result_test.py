"""Utilities for replaying and evaluating one saved generation on demand.

Usage summary:
- This module replays individuals saved in one `generation_<N>_mo.txt` log.
- By default it only replays Pareto Front 1.
- Use `--max-front N` to replay Pareto Front 1..N.
- Use `--all-fronts` to ignore Pareto-front filtering and replay every saved individual.
- Use `--individual-id <id>` to replay only one specific individual.
- Use repeated `--opponent <name>` flags to override the default benchmark opponent list.

Default output:
- If `--output` is not provided, results are written to
  `generation_<N>_front_<front>.json` under the run log directory.
- When `--all-fronts` is used, the output filename uses `front_all`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from ..tools.component_pool import ComponentPool
from ..config import EAConfig, load_config_from_json
from ..tools.ea_log_parse import parse_individuals_from_ea_log
from .evaluate import Evaluator
from ..main import OPPONENT_LIST

# CLI examples:
# `py -m eagle.eval.result_test --log-dir eagle/logs/20260409_123456 --generation 20`
#   Replay only Pareto Front 1 from generation 20.
#
# `py -m eagle.eval.result_test --log-dir eagle/logs/20260409_123456 --generation 20 --max-front 3`
#   Replay Pareto Front 1, 2, and 3 from generation 20.
#
# `py -m eagle.eval.result_test --log-dir eagle/logs/20260409_123456 --generation 20 --all-fronts`
#   Replay every individual stored in generation 20.
#
# `py -m eagle.eval.result_test --log-dir eagle/logs/20260409_123456 --generation 20 --individual-id <id>`
#   Replay only one specific individual from generation 20.
#
# `py -m eagle.eval.result_test --log-dir eagle/logs/20260409_123456 --generation 20 --opponent ai.RandomAI --opponent ai.PassiveAI`
#   Replay against a custom opponent subset instead of the default benchmark list.


def parse_max_front_arg(raw_value: str) -> int | None:
    """Parse CLI front-cutoff values such as `1`, `3`, or `all`.

    Returns:
    - `None` when the caller explicitly requests `all`
    - an integer `>= 1` for a bounded Pareto-front cutoff
    """
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


def load_run_config(log_dir: str | Path) -> EAConfig:
    """Load the saved run config when available, falling back to defaults.

    This keeps manual replay aligned with the original run settings instead of
    replaying under today's default `EAConfig()`.
    """
    return load_config_from_json(log_dir)


def extract_individual_ids_up_to_front(
    generation_log_path: str | Path,
    max_front: int | None,
) -> list[str]:
    """Extract ids that belong to Pareto Front 1 up to the requested front.

    Notes:
    - The EA generation log stores fronts in human-readable text form.
    - This helper scans that file and collects `id=` values from every front
      whose front number is `<= max_front`.
    - When `max_front is None`, callers are expected to skip front filtering.
    """
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
    """Load all serialized individuals stored in one saved generation log.

    This reads the structured individual payloads from
    `generation_<generation>_mo.txt`.
    """
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
    """Convert one replay result into the JSON-friendly output schema.

    Result labels are derived from the first objective:
    - `1.0` -> `Win`
    - `0.0` -> `Loss`
    - anything else -> `Draw`
    """
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
    allowed_individual_ids: set[str] | None = None,
):
    """Filter generation individuals by id and/or their stored first objective.

    Filtering order:
    1. Pareto-front filter (`allowed_individual_ids`)
    2. explicit `individual_id`
    3. optional `only_winning_individuals`
    """
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
    max_front: int | None = 1,
    output_path: str | Path | None = None,
) -> dict:
    """Replay one saved generation and write per-opponent evaluation results.

    Parameters:
    - `log_dir`: one EA run directory containing `component_pool.json`,
      `config.json`, and `generation_<N>_mo.txt`
    - `generation`: saved generation number to replay
    - `opponents`: optional custom opponent list; defaults to `OPPONENT_LIST`
    - `individual_id`: optional single-individual override
    - `only_winning_individuals`: optional extra filter on stored objective 0
    - `max_front`: replay Pareto Front 1..N; `None` means no front filtering
    - `output_path`: optional explicit JSON output destination

    Returns:
    - a JSON-serializable dictionary containing replay metadata and results
    """
    log_dir_path = Path(log_dir)
    component_pool_path = log_dir_path / "component_pool.json"
    if not component_pool_path.exists():
        raise FileNotFoundError(f"Component pool not found: {component_pool_path}")

    evaluator = Evaluator(
        ComponentPool.from_json(str(component_pool_path)),
        load_run_config(log_dir_path),
    )
    generation_log_path = resolve_generation_log_path(log_dir_path, generation)
    individuals = load_generation_individuals(log_dir_path, generation)
    allowed_individual_ids: set[str] | None = None
    if max_front is not None:
        allowed_individual_ids = set(extract_individual_ids_up_to_front(generation_log_path, max_front))

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
        "max_front": max_front,
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
                else log_dir_path / f"generation_{generation}_front_{max_front if max_front is not None else 'all'}_result_test.json"
            )
            with open(destination, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4)

    return results


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI used for replaying one saved generation."""
    parser = argparse.ArgumentParser(description="Replay one saved generation and collect result-test outputs.")
    # Required:
    # --log-dir <run_log_dir>
    # --generation <saved_generation_number>
    #
    # Optional:
    # --max-front <N>         replay Pareto Front 1..N
    # --all-fronts            replay all individuals regardless of front
    # --individual-id <id>    replay one specific individual only
    # --opponent <name>       override opponents; repeat flag to add more
    # --only-winning-individuals
    #                         add an extra filter requiring stored objective 0 == 1.0
    # --output <json_path>    write results to a custom JSON path
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
    )


if __name__ == "__main__":
    main()
