import json

from .config import EAConfig
from .component_pool import ComponentPool
from .ea_log_parse import parse_individuals_from_ea_log
from .evaluate import Evaluator
from .main import OPPONENT_LIST


def run_final_test_suite(current_log_dir: str, last_gen: int):
    """Replay winning final-generation individuals against the benchmark opponents."""
    experiment_log_dir = f"{current_log_dir}"
    evaluator = Evaluator(
        ComponentPool.from_json(f"{experiment_log_dir}/component_pool.json"),
        EAConfig(),
    )

    last_generation_log_path = f"{experiment_log_dir}/generation_{last_gen}_mo.txt"
    individuals = parse_individuals_from_ea_log(last_generation_log_path)

    results = {}
    for individual in individuals:
        if individual.fitness[0] != 1.0:
            continue

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
            if fitness_score[0] == 1.0:
                result = "Win"
            elif fitness_score[0] == 0.0:
                result = "Loss"
            else:
                result = "Draw"

            results.setdefault(individual.id, [])
            results[individual.id].append(
                {
                    "opponent": opponent,
                    "result": result,
                    "resource_advantage": fitness_score[1],
                }
            )

            with open(f"{experiment_log_dir}/final_test_results.json", "w") as f:
                json.dump(results, f, indent=4)


if __name__ == "__main__":
    current_log_dir = "20240930_123456"
    last_gen = 10
    run_final_test_suite(current_log_dir, last_gen)
