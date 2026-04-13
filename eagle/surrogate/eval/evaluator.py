"""Evaluate prompts through surrogate game-round or policy-based pipelines."""

from __future__ import annotations

from pathlib import Path

from ...utils.llm import LLM
from ...utils.log_parse import sample_recent_dynamic_prompts
from ...utils.fitness_utils import normalize_fitness
from .single_round import evaluate_eagle_single_round

# The original prompt-only LLM surrogate path is intentionally disabled.
# It is kept commented out as reference.
#
# import random
# from .llm import LLM
#
#
# def build_surrogate_examples(fitness_recorder) -> list[list[str]]:
#     """Sample a few historical prompt/fitness pairs for in-context surrogate scoring."""
#     examples: list[list[str]] = []
#     if fitness_recorder is None or not getattr(fitness_recorder, "records", None):
#         return examples
#
#     sampled = random.sample(
#         fitness_recorder.records,
#         min(len(fitness_recorder.records), 3),
#     )
#     for record in sampled:
#         prompt = record.get("prompt")
#         fitness = record.get("fitness", record.get("fitness_score"))
#         if prompt is None or fitness is None:
#             continue
#         examples.append([prompt, str(fitness)])
#     return examples
#
#
# def adjust_surrogate_scores(surrogate_scores: list[float]) -> list[float]:
#     """Apply the uncertainty penalty used by the prompt-only surrogate."""
#     estimated_power, uncertainty, simplicity, clarity = surrogate_scores
#     print(
#         "Surrogate evaluation - "
#         f"Estimated Power: {estimated_power}, "
#         f"Uncertainty: {uncertainty}, "
#         f"Simplicity: {simplicity}, "
#         f"Clarity: {clarity}"
#     )
#
#     adjusted_power = max(-1.0, min(1.0, estimated_power * 0.8 - 0.3 * uncertainty))
#     print(f"Adjusted Power after uncertainty penalty: {adjusted_power}")
#     return [adjusted_power, uncertainty, simplicity, clarity]
#
#
# def surrogate_evaluation_llm(prompt: str, fitness_recorder=None) -> list[float]:
#     """Score a prompt using the prompt-only LLM surrogate."""
#     examples = build_surrogate_examples(fitness_recorder)
#     surrogate_scores = LLM.ollama_evaluate_fitness(prompt, example=examples)
#     adjusted = adjust_surrogate_scores(surrogate_scores)
#     return [adjusted[0], 0.0]


def _resolve_surrogate_logs_dir(repo_root: Path, config) -> Path:
    """Resolve the log directory used for sampled Dynamic Prompt surrogate rounds."""
    configured = Path(str(getattr(config, "surrogate_log_dir", "logs")))
    if configured.is_absolute():
        return configured
    return repo_root / configured


def estimate_llm_game_round_score(
    prompt: str,
    repo_root: Path,
    config,
) -> float:
    """Estimate instruction accuracy from sampled Dynamic Prompt states with the LLM."""
    logs_dir = _resolve_surrogate_logs_dir(repo_root, config)
    sampled_dynamic_prompts = sample_recent_dynamic_prompts(
        logs_dir,
        recent_count=max(1, int(getattr(config, "surrogate_recent_match_window", 10))),
        sample_count=max(1, int(getattr(config, "surrogate_round_samples_per_match", 10))),
    )
    if not sampled_dynamic_prompts:
        print("No recent Dynamic Prompt samples found for LLM game-round surrogate; using 0.0.")
        return 0.0

    scores: list[float] = []
    for sample in sampled_dynamic_prompts:
        dynamic_prompt_text = str(sample.get("text", "")).strip()
        if not dynamic_prompt_text:
            continue
        round_result = evaluate_eagle_single_round(prompt, dynamic_prompt_text)
        scores.append(float(round_result["game_round_score"]))

    if not scores:
        print("LLM game-round surrogate produced no valid sampled scores; using 0.0.")
        return 0.0

    return sum(scores) / len(scores)


def compose_three_part_surrogate_fitness(
    prompt: str,
    repo_root: Path,
    config,
    java_fitness: list[float],
) -> list[float]:
    """Combine Java-agent surrogate objectives with LLM round-accuracy scoring."""
    normalized_java = normalize_fitness(java_fitness)
    llm_game_round_score = estimate_llm_game_round_score(prompt, repo_root, config)
    return normalize_fitness(
        [
            normalized_java[0],
            llm_game_round_score,
            normalized_java[2],
        ]
    )


def surrogate_evaluation_game_round(
    prompt: str,
    repo_root: Path,
    config,
    opponent: str | None,
    *,
    simulate_surrogate_games_fn,
) -> list[float]:
    """Score a prompt with Java-agent win/resource signals plus LLM round accuracy."""
    java_fitness, metadata = simulate_surrogate_games_fn(
        repo_root,
        config,
        prompt,
        opponent,
        {},
    )
    fitness = compose_three_part_surrogate_fitness(prompt, repo_root, config, java_fitness)
    print(
        "Surrogate Java-agent evaluation: "
        f"win_score={fitness[0] if fitness else 0.0}, "
        f"game_round_score={fitness[1] if len(fitness) > 1 else 0.0}, "
        f"resource_advantage_score={fitness[2] if len(fitness) > 2 else 0.0}, "
        f"log={metadata.get('log_path') if metadata else None}"
    )
    return fitness


def surrogate_evaluation_policy(
    prompt: str,
    repo_root: Path,
    config,
    opponent: str | None,
    *,
    simulate_policy_surrogate_games_fn,
) -> list[float]:
    """Score a prompt with policy Java-agent win/resource signals plus LLM round accuracy."""
    java_fitness, metadata = simulate_policy_surrogate_games_fn(
        repo_root,
        config,
        prompt,
        opponent,
        {},
    )
    fitness = compose_three_part_surrogate_fitness(prompt, repo_root, config, java_fitness)
    compiled_policy = metadata.get("compiled_policy") if metadata else None
    print(
        "Surrogate policy-agent evaluation: "
        f"policy={compiled_policy}, "
        f"win_score={fitness[0] if fitness else 0.0}, "
        f"game_round_score={fitness[1] if len(fitness) > 1 else 0.0}, "
        f"resource_advantage_score={fitness[2] if len(fitness) > 2 else 0.0}, "
        f"log={metadata.get('log_path') if metadata else None}"
    )
    return fitness

