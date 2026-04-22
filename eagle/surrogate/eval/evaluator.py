"""Evaluate prompts through surrogate game-round or policy-based pipelines."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ...envs.microrts.runner import run_java_agent_game
from ...project import PROJECT_ROOT
from ...utils.log_parse import sample_recent_dynamic_prompts
from ...utils.fitness_utils import normalize_fitness
from ..java.compiler import compile_java_agent
from ..java.renderer import render_java_agent
from ..strategy.extractor import extract_strategy
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
    configured = Path(str(config.surrogate_log_dir))
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
        recent_count=max(1, int(config.surrogate_recent_match_window)),
        sample_count=max(1, int(config.surrogate_round_samples_per_match)),
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
    fitness = evaluate_with_java_surrogate(
        prompt,
        repo_root=repo_root,
        config=config,
        opponent=opponent,
    )
    print(
        "Surrogate policy-agent evaluation: "
        f"win_score={fitness[0] if fitness else 0.0}, "
        f"game_round_score={fitness[1] if len(fitness) > 1 else 0.0}, "
        f"resource_advantage_score={fitness[2] if len(fitness) > 2 else 0.0}, "
        "log=java_template_pipeline"
    )
    return fitness


_COMPILED_AGENT_CACHE: dict[str, dict[str, str]] = {}


def very_low_fitness() -> list[float]:
    """Return the worst surrogate fitness used for fail-closed execution."""
    return [0.0, 0.0, 0.0]


def generate_unique_class_name(prompt: str) -> str:
    """Build one deterministic generated class name from the prompt contents."""
    digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]
    return f"EAGLETemplateAgent_{digest}"


def _cache_root(repo_root: Path) -> Path:
    """Return the filesystem location used for generated Java agent caching."""
    cache_root = repo_root / "logs" / "surrogate_java_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def _cached_class_available(repo_root: Path, class_name: str) -> bool:
    """Return whether the compiled class already exists in the MicroRTS output tree."""
    class_file = repo_root / "third_party" / "microrts" / "bin" / "ai" / "abstraction" / f"{class_name}.class"
    return class_file.exists()


def evaluate_with_java_surrogate(
    prompt: str,
    repo_root: Path | None = None,
    config=None,
    opponent: str | None = None,
) -> list[float]:
    """
    Full pipeline:
    prompt → strategy → Java → compile → run → fitness
    """
    resolved_repo_root = (repo_root or PROJECT_ROOT).resolve()
    cache_key = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
    cache_root = _cache_root(resolved_repo_root)

    try:
        cached_entry = _COMPILED_AGENT_CACHE.get(cache_key)
        if cached_entry is not None and _cached_class_available(resolved_repo_root, cached_entry["class_name"]):
            class_name = cached_entry["class_name"]
        else:
            strategy = extract_strategy(prompt)
            class_name = generate_unique_class_name(prompt)
            java_code = render_java_agent(strategy, class_name)
            tmp_dir = cache_root / cache_key
            success = compile_java_agent(java_code, class_name, str(tmp_dir))
            if not success:
                return very_low_fitness()
            _COMPILED_AGENT_CACHE[cache_key] = {
                "class_name": class_name,
                "tmp_dir": str(tmp_dir),
            }

        java_fitness, metadata = run_java_agent_game(
            project_root=resolved_repo_root,
            config=config,
            ai1_class=f"ai.abstraction.{class_name}",
            opponent=opponent,
            prompt=prompt,
            compile_first=False,
            log_prefix="run_surrogate",
            runtime_logs_dir=getattr(config, "runtime_logs_dir", None),
        )
        if metadata.get("exit_code", 1) != 0:
            return very_low_fitness()
        return compose_three_part_surrogate_fitness(prompt, resolved_repo_root, config, normalize_fitness(java_fitness))
    except Exception:
        return very_low_fitness()

