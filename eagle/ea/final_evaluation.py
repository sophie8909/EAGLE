import json
from pathlib import Path

from .config import EAConfig
from .component_pool import ComponentPool
from .ea_log_parse import parse_individuals_from_ea_log
from .evaluate import Evaluator
from .main import OPPONENT_LIST
from .result_test import build_result_record, extract_individual_ids_up_to_front


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

    generation_log_path = _resolve_final_generation_log_path(experiment_log_dir, last_gen)
    individuals = parse_individuals_from_ea_log(str(generation_log_path))
    selected_front_ids = set(
        extract_individual_ids_up_to_front(
            generation_log_path,
            config.final_test_max_front,
        )
    )
    selected_individuals = [
        individual
        for individual in individuals
        if not selected_front_ids or individual.id in selected_front_ids
    ]

    results = {
        "generation_log": generation_log_path.name,
        "selected_individual_count": len(selected_individuals),
        "selection_rule": (
            f"pareto_front_1_to_{config.final_test_max_front}"
            if config.final_test_max_front is not None
            else "all_fronts"
        ),
        "results": {},
    }
    for individual in selected_individuals:
        prompt = evaluator.construct_prompt(individual)
        evaluator.save_prompt(prompt)

        for opponent in OPPONENT_LIST:
            print(f"Testing against opponent: {opponent}")
            evaluator.set_opponent(opponent)

            process = evaluator.launch_simulation(test=True)
            evaluator.wait_for_simulation(process)

            latest_log_file = evaluator.get_latest_log_file()
            if not latest_log_file:
                continue

            print(f"Testing parse_fitness with log file: {latest_log_file}")
            with open(latest_log_file, "r") as f:
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

            with open(experiment_log_dir / "final_test_results.json", "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4)


if __name__ == "__main__":
    current_log_dir = "20240930_123456"
    last_gen = 10
    run_final_test_suite(current_log_dir, last_gen)
