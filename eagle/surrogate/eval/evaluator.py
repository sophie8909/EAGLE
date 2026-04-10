from __future__ import annotations

from pathlib import Path

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


def surrogate_evaluation_game_round(
    prompt: str,
    repo_root: Path,
    config,
    opponent: str | None,
    *,
    simulate_surrogate_games_fn,
) -> list[float]:
    """Score a prompt by running the generated surrogate Java agent in-game."""
    fitness, metadata = simulate_surrogate_games_fn(
        repo_root,
        config,
        prompt,
        opponent,
        {},
    )
    print(
        "Surrogate Java-agent evaluation: "
        f"win_score={fitness[0] if fitness else 0.0}, "
        f"game_round_score={fitness[1] if len(fitness) > 1 else 0.0}, "
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
    """Score a prompt by compiling it into a fixed policy surrogate and running one match."""
    fitness, metadata = simulate_policy_surrogate_games_fn(
        repo_root,
        config,
        prompt,
        opponent,
        {},
    )
    compiled_policy = metadata.get("compiled_policy") if metadata else None
    print(
        "Surrogate policy-agent evaluation: "
        f"policy={compiled_policy}, "
        f"win_score={fitness[0] if fitness else 0.0}, "
        f"game_round_score={fitness[1] if len(fitness) > 1 else 0.0}, "
        f"log={metadata.get('log_path') if metadata else None}"
    )
    return fitness
