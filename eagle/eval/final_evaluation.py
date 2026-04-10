"""Replay saved individuals for final benchmark evaluation and result logging."""

import json
from pathlib import Path

from ..tools.config import EAConfig
from ..tools.component_pool import ComponentPool
from ..tools.ea_log_parse import parse_individuals_from_ea_log
from .evaluate import Evaluator
from ..algorithm.main import OPPONENT_LIST
from .result_test import build_result_record, extract_individual_ids_up_to_front


def _resolve_final_test_max_front(config: EAConfig) -> int | None:
    """Default missing final-test front limits to Pareto Front 1."""
    configured_value = getattr(config, "final_test_max_front", 1)
    if configured_value is None:
        return 1
    return configured_value


def _resolve_final_generation_log_path(current_log_dir: str | Path, last_gen: int) -> Path:
    """Resolve the saved generation log for the final replay step.

    Older call sites pass the internal zero-based generation index, while the
    saved filenames are one-based (`generation_1_mo.txt`, ...). We accept both
    to keep final-test replay stable across existing callers.
    """
    log_dir = Path(current_log_dir)
    exact_match = log_dir / f"generation_{last_gen}_mo.txt"
    if exact_match.exists():
        return exact_match

    one_based_match = log_dir / f"generation_{last_gen + 1}_mo.txt"
    if one_based_match.exists():
        return one_based_match

    raise FileNotFoundError(
        f"Final generation log not found under {log_dir} for generation index {last_gen}."
    )


def _build_final_test_interval_runs(config: EAConfig) -> list[dict[str, int | str]]:
    """Return the two final-test interval variants that should always be evaluated."""

    configured_interval = int(getattr(config, "llm_interval", 1))
    return [
        {"label": "config", "llm_interval": configured_interval},
        {"label": "interval_1", "llm_interval": 1},
    ]


def run_final_test_suite(
    current_log_dir: str,
    last_gen: int,
    config: EAConfig | None = None,
):
    """Replay final-generation individuals up to the configured Pareto front cutoff."""
    experiment_log_dir = Path(current_log_dir)
    config = config or EAConfig()
    evaluator = Evaluator(
        ComponentPool.from_json(str(experiment_log_dir / "component_pool.json")),
        config,
    )
    final_test_max_front = _resolve_final_test_max_front(config)

    generation_log_path = _resolve_final_generation_log_path(experiment_log_dir, last_gen)
    individuals = parse_individuals_from_ea_log(str(generation_log_path))
    selected_front_ids = set(
        extract_individual_ids_up_to_front(
            generation_log_path,
            final_test_max_front,
        )
    )
    selected_individuals = [
        individual
        for individual in individuals
        if individual.id in selected_front_ids
    ]

    results = {
        "generation_log": generation_log_path.name,
        "selected_individual_count": len(selected_individuals),
        "selection_rule": f"pareto_front_1_to_{final_test_max_front}",
        "interval_runs": _build_final_test_interval_runs(config),
        "results": {},
    }
    for individual in selected_individuals:
        prompt = evaluator.construct_prompt(individual)
        evaluator.save_prompt(prompt)

        for interval_run in results["interval_runs"]:
            llm_interval = int(interval_run["llm_interval"])
            evaluator.set_llm_interval(llm_interval)

            for opponent in OPPONENT_LIST:
                print(
                    "Testing against opponent: "
                    f"{opponent} (mode={interval_run['label']}, llm_interval={llm_interval})"
                )
                evaluator.set_opponent(opponent)

                process = evaluator.launch_simulation(test=True)
                evaluator.wait_for_simulation(process)

                latest_log_file = evaluator.get_latest_log_file()
                if not latest_log_file:
                    continue

                print(f"Testing parse_fitness with log file: {latest_log_file}")
                with open(latest_log_file, "r", encoding="utf-8") as f:
                    log_content = f.read()

                fitness_score = evaluator.calculate_fitness_score(log_content)
                result_record = build_result_record(
                    individual,
                    opponent,
                    fitness_score,
                    str(latest_log_file),
                )
                result_record["interval_mode"] = str(interval_run["label"])
                result_record["llm_interval"] = llm_interval

                results["results"].setdefault(individual.id, [])
                results["results"][individual.id].append(result_record)

                with open(experiment_log_dir / "final_test_results.json", "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=4)
