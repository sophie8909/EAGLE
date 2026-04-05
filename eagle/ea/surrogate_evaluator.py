from __future__ import annotations

from pathlib import Path
import random

from .llm import LLM
from .move_validator import combine_prompt_with_dynamic, score_game_round_response


def build_surrogate_examples(fitness_recorder) -> list[list[str]]:
    """Sample a few historical prompt/fitness pairs for in-context surrogate scoring."""
    examples: list[list[str]] = []
    if fitness_recorder is None or not getattr(fitness_recorder, "records", None):
        return examples

    sampled = random.sample(
        fitness_recorder.records,
        min(len(fitness_recorder.records), 3),
    )
    for record in sampled:
        prompt = record.get("prompt")
        fitness = record.get("fitness", record.get("fitness_score"))
        if prompt is None or fitness is None:
            continue
        examples.append([prompt, str(fitness)])
    return examples


def adjust_surrogate_scores(surrogate_scores: list[float]) -> list[float]:
    """Apply the uncertainty penalty used by the prompt-only surrogate."""
    estimated_power, uncertainty, simplicity, clarity = surrogate_scores
    print(
        "Surrogate evaluation - "
        f"Estimated Power: {estimated_power}, "
        f"Uncertainty: {uncertainty}, "
        f"Simplicity: {simplicity}, "
        f"Clarity: {clarity}"
    )

    adjusted_power = max(-1.0, min(1.0, estimated_power * 0.8 - 0.3 * uncertainty))
    print(f"Adjusted Power after uncertainty penalty: {adjusted_power}")
    return [adjusted_power, uncertainty, simplicity, clarity]


def surrogate_evaluation_llm(prompt: str, fitness_recorder=None) -> list[float]:
    """Score a prompt using the prompt-only LLM surrogate."""
    examples = build_surrogate_examples(fitness_recorder)
    surrogate_scores = LLM.ollama_evaluate_fitness(prompt, example=examples)
    return adjust_surrogate_scores(surrogate_scores)


def surrogate_evaluation_game_round(
    prompt: str,
    repo_root: Path,
    config,
    fitness_recorder=None,
    *,
    sample_recent_dynamic_prompts_fn,
    llm_generate_json_response_fn,
    surrogate_evaluation_llm_fn,
) -> list[float]:
    """Score a prompt on sampled historical rounds by generating and validating moves."""
    sampled_dynamic_prompts = sample_recent_dynamic_prompts_fn(
        repo_root / config.surrogate_log_dir,
        recent_count=config.surrogate_recent_log_window,
        sample_count=config.surrogate_game_round_samples,
    )

    if not sampled_dynamic_prompts:
        print("No recent dynamic prompt found for game_round surrogate. Falling back to llm version.")
        return surrogate_evaluation_llm_fn(prompt, fitness_recorder=fitness_recorder)

    round_scores: list[float] = []
    for sampled_dynamic in sampled_dynamic_prompts:
        dynamic_text = sampled_dynamic.get("text", "")
        sampled_time = sampled_dynamic.get("time")
        sampled_log_path = sampled_dynamic.get("log_path")
        print(
            "Using sampled dynamic prompt for game_round surrogate: "
            f"log={sampled_log_path}, turn={sampled_time}"
        )
        combined_prompt = combine_prompt_with_dynamic(prompt, dynamic_text)
        llm_response = llm_generate_json_response_fn(combined_prompt)
        round_scores.append(score_game_round_response(llm_response, dynamic_text))

    average_game_round = sum(round_scores) / len(round_scores) if round_scores else 0.0
    average_game_round = max(-1.0, min(1.0, average_game_round))
    print(f"Average surrogate game_round score from {len(round_scores)} sampled rounds: {average_game_round}")
    return [average_game_round, 0.0, 0.0, 0.0]
