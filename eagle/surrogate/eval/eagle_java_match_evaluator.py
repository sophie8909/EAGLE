"""Evaluate prompts by generating and running the eagleJava agent."""

from __future__ import annotations

from pathlib import Path

from ...envs.microrts.runner import run_java_agent_game
from ...project import PROJECT_ROOT
from ..java.eagle_java_compiler import compile_eagle_java_agent
from ..java.eagle_java_renderer import EAGLE_JAVA_CLASS_NAME, render_eagle_java_from_prompt


def very_low_fitness() -> dict[str, float]:
    """Return the worst eagleJava match score used for fail-closed execution."""
    return {
        "win_score": 0.0,
        "raw_resource_advantage_score": 0.0,
    }


def _cache_root(repo_root: Path) -> Path:
    """Return the filesystem location used for generated eagleJava source."""
    cache_root = repo_root / "logs" / "eagle_java"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def evaluate_with_eagle_java(
    prompt: str,
    repo_root: Path | None = None,
    config=None,
    opponent: str | None = None,
) -> dict[str, float]:
    """
    Full pipeline:
    prompt -> strategy slots -> eagleJava.java -> compile -> run -> fitness
    """
    resolved_repo_root = (repo_root or PROJECT_ROOT).resolve()
    cache_root = _cache_root(resolved_repo_root)

    try:
        java_code = render_eagle_java_from_prompt(prompt)
        success = compile_eagle_java_agent(java_code, str(cache_root))
        if not success:
            return very_low_fitness()

        match_score, metadata = run_java_agent_game(
            project_root=resolved_repo_root,
            config=config,
            ai1_class=f"ai.abstraction.{EAGLE_JAVA_CLASS_NAME}",
            opponent=opponent,
            prompt=prompt,
            compile_first=False,
            log_prefix="run_eagle_java",
            runtime_logs_dir=getattr(config, "runtime_logs_dir", None),
            record_trace=bool(getattr(config, "save_trace_on_test", False)),
        )
        if metadata.get("exit_code", 1) != 0:
            return very_low_fitness()
        return match_score
    except Exception:
        return very_low_fitness()
