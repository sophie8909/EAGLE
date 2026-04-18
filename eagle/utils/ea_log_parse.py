"""Parse human-readable EA logs back into prompts and Individual objects."""

from __future__ import annotations

import ast

from .individual import Individual


def extract_prompts_from_ea_log(log_file: str):
    """Extract prompt text blocks from a generation log file."""
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    prompts = []
    prompt = []
    in_prompt_section = False

    for line in lines:
        line = line.strip()
        if line.startswith("Prompt:"):
            in_prompt_section = True
        elif line.startswith("Individual") or line.startswith("Pareto Front"):
            if prompt:
                prompts.append("\n".join(prompt))
                prompt = []
        elif in_prompt_section and line:
            prompt.append(line)

    return prompts


def _split_top_level_fields(individual_str: str) -> list[str]:
    """Split a serialized Individual(...) payload without breaking nested dicts."""
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
    """Best-effort parser for literal values embedded inside log lines."""
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def parse_individuals_from_ea_log(log_file: str):
    """Parse serialized Individual records back into runtime Individual objects."""
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    
    individuals = []
    front = []
    for line in lines:
        if line.startswith("Pareto Front "):
            if front:
                individuals.append(front)
                front = []
            continue
        if not line.startswith("Individual"):
            continue

        start_idx = line.find("Individual(") + len("Individual(")
        end_idx = line.rfind(")")
        if start_idx == -1 or end_idx == -1:
            continue

        individual_str = line[start_idx:end_idx]
        components = _split_top_level_fields(individual_str)
        individual_data = {}
        for component in components:
            if "=" in component:
                key, value = component.split("=", 1)
                individual_data[key.strip()] = _parse_literal(value.strip())

        individual = Individual(**individual_data)
        fitness_start = line.find("Fitness:")
        if fitness_start != -1:
            fitness_segment = line[fitness_start + len("Fitness:"):].strip()
            eval_mode_start = fitness_segment.find(" - EvalMode:")
            if eval_mode_start != -1:
                fitness_segment = fitness_segment[:eval_mode_start].strip()
            if fitness_segment.startswith("[") and fitness_segment.endswith("]"):
                individual.fitness = _parse_literal(fitness_segment)

        front.append(individual)

    if front:
        individuals.append(front)

    return individuals
