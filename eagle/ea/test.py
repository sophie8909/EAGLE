import ast
import json
from .config import EAConfig
from .component_pool import ComponentPool
from .evaluate import Evaluator
from .individual import Individual

from .main import OPPONENT_LIST

def parse_ea_log_to_prompt(log_file: str):
    with open(log_file, "r") as f:
        lines = f.readlines()
    prompts = []
    prompt = []
    isPromptSection = False
    # Split the log into sections for each individual (starting with "Individual", end until the next "Individual" or end of file)
    for line in lines:
        line = line.strip()
        if line.startswith("Prompt:"):
            isPromptSection = True
        elif line.startswith("Individual") or line.startswith("Pareto Front"):
            if prompt:
                prompts.append("\n".join(prompt))
                prompt = []
        elif isPromptSection:
            if line:  # Only add non-empty lines to the prompt
                prompt.append(line)
     

    return prompts




def _split_top_level_fields(individual_str: str) -> list[str]:
    fields = []
    start = 0
    depth = 0
    in_string = False
    string_quote = ""
    escaped = False

    for i, char in enumerate(individual_str):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            continue

        if char in ("'", '"'):
            in_string = True
            string_quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            fields.append(individual_str[start:i].strip())
            start = i + 1

    tail = individual_str[start:].strip()
    if tail:
        fields.append(tail)
    return fields


def _parse_literal(value: str):
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def parse_ea_log(log_file: str):
    with open(log_file, "r") as f:
        lines = f.readlines()
    individuals = []
    # Extract the Individuals
    for line in lines:
        if line.startswith("Individual"):
            # print(line.strip())
            # Extract the part after "Individual(" and before the closing ")"
            start_idx = line.find("Individual(") + len("Individual(")
            end_idx = line.rfind(")")
            if start_idx != -1 and end_idx != -1:
                individual_str = line[start_idx:end_idx]
                # Split key-value pairs only on top-level commas so nested
                # dictionaries such as strategy={...} stay intact.
                components = _split_top_level_fields(individual_str)
                individual_data = {}
                for component in components:
                    if "=" in component:
                        key, value = component.split("=", 1)
                        individual_data[key.strip()] = _parse_literal(value.strip())
            individual = Individual(**individual_data)
            line.find("Fitness:") + len("Fitness:")
            fitness_str = line[line.find("Fitness:") + len("Fitness:"):].strip()
            if fitness_str.startswith("[") and fitness_str.endswith("]"):
                individual.fitness = _parse_literal(fitness_str)
            
            individuals.append(individual)
    return individuals

def final_test(current_log_dir: str, last_gen: int):
    experiment_log_folder = f"{current_log_dir}"  # Replace with the actual log folder name
    evaluator = Evaluator(
        ComponentPool.from_json(f"{experiment_log_folder}/component_pool.json"),
        EAConfig(),
    )
    
    last_generation_log = f"{experiment_log_folder}/generation_{last_gen}_mo.txt"  # Replace with the actual generation log file name
    individuals = parse_ea_log(last_generation_log)


    results = {}
    for individual in individuals:
        if individual.fitness[0] == 1.0:  # Only test individuals with a win score of 1.0
            # print(f"Testing individual: {individual}")
            # print(f"Fitness: {individual.fitness}")
            prompt = evaluator.construct_prompt(individual)
            # print(f"Testing prompt:\n{prompt}\n")
            for opponent in OPPONENT_LIST:
                print(f"Testing against opponent: {opponent}")
                evaluator.set_opponent(opponent)
                
                process = evaluator.launch_simulation(test=True)  # Use the test version of the RunLoop to speed up the test
                # This includes waiting for the game to complete and loading the produced log.
                evaluator.wait_for_simulation(process)

                #get run log file
                latest_log_file = evaluator.get_latest_log_file()
                if latest_log_file:
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
                    results[individual.id].append({
                        "opponent": opponent,
                        "result": result,
                        "resource_advantage": fitness_score[1],
                    })
                # save results to json file
                with open(f"{experiment_log_folder}/final_test_results.json", "w") as f:
                    json.dump(results, f, indent=4)
    



if __name__ == "__main__":
    # test final prompt
    
    current_log_dir = "20240930_123456"  # Replace with the actual log folder name
    last_gen = 10  # Replace with the actual last generation number
    final_test(current_log_dir, last_gen)
