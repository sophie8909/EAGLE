"""Compatibility wrappers over the MicroRTS adapter layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..envs.microrts.adapter import (
    detect_timeout,
    get_latest_log_file,
    run_prompt_based_game,
    run_surrogate_validation_case,
    save_prompt,
    set_ai1,
    set_llm_interval,
    set_opponent,
)
from ..surrogate.compiler import compile_prompt_to_surrogate_spec
from .profiler import timer


def launch_simulation(repo_root: Path, config, test: bool = False):
    """Legacy API retained for backward compatibility."""
    raise RuntimeError(
        "launch_simulation is deprecated. Use eagle.envs.microrts.runner.run_java_agent_game instead."
    )


def wait_for_simulation(process):
    """Legacy API retained for backward compatibility."""
    raise RuntimeError(
        "wait_for_simulation is deprecated. Use eagle.envs.microrts.runner.run_java_agent_game instead."
    )


def simulate_games(
    repo_root: Path,
    config,
    opponent: str | None,
    stats: dict[str, float],
    *,
    test: bool = False,
) -> tuple[list[float], dict[str, Any]]:
    """Run one prompt-driven EAGLE match through the adapter layer."""
    with timer("game_play_time", stats):
        return run_prompt_based_game(
            project_root=repo_root,
            config=config,
            prompt=(repo_root / "third_party" / "microrts" / "prompt.txt").read_text(encoding="utf-8")
            if (repo_root / "third_party" / "microrts" / "prompt.txt").exists()
            else "",
            opponent=opponent,
            test=test,
        )


def simulate_surrogate_games(
    repo_root: Path,
    config,
    prompt: str,
    opponent: str | None,
    stats: dict[str, float],
    ai1_class: str = "ai.abstraction.EAGLESurrogate",
    surrogate_spec: dict[str, object] | None = None,
    *,
    test: bool = False,
) -> tuple[list[float], dict[str, Any]]:
    """Run one surrogate Java-agent match through the adapter layer."""
    with timer("game_play_time", stats):
        return run_surrogate_validation_case(
            project_root=repo_root,
            config=config,
            prompt=prompt,
            opponent=opponent,
            ai1_class=ai1_class,
            surrogate_spec=surrogate_spec,
            test=test,
        )


def simulate_policy_surrogate_games(
    repo_root: Path,
    config,
    prompt: str,
    opponent: str | None,
    stats: dict[str, float],
    *,
    test: bool = False,
) -> tuple[list[float], dict[str, Any]]:
    """Compile one prompt into a policy surrogate and run the validation match."""
    policy, surrogate_spec = compile_prompt_to_surrogate_spec(prompt)
    fitness, metadata = simulate_surrogate_games(
        repo_root,
        config,
        prompt,
        opponent,
        stats,
        surrogate_spec=surrogate_spec,
        test=test,
    )
    metadata["compiled_policy"] = policy
    return fitness, metadata
