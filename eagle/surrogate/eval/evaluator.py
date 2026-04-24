"""Evaluate prompts through the current Java surrogate pipeline."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ...envs.microrts.runner import run_java_agent_game
from ...project import PROJECT_ROOT
from ..java.compiler import compile_java_agent
from ..java.renderer import render_java_agent
from ..strategy.extractor import extract_strategy

_COMPILED_AGENT_CACHE: dict[str, dict[str, str]] = {}


def very_low_fitness() -> dict[str, float]:
    """Return the worst surrogate match score used for fail-closed execution."""
    return {
        "win_score": 0.0,
        "raw_resource_advantage_score": 0.0,
    }


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
) -> dict[str, float]:
    """
    Full pipeline:
    prompt -> strategy -> Java -> compile -> run -> fitness
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

        match_score, metadata = run_java_agent_game(
            project_root=resolved_repo_root,
            config=config,
            ai1_class=f"ai.abstraction.{class_name}",
            opponent=opponent,
            prompt=prompt,
            compile_first=False,
            log_prefix="run_surrogate",
            runtime_logs_dir=getattr(config, "runtime_logs_dir", None),
            record_trace=bool(getattr(config, "save_trace_on_test", False)),
        )
        if metadata.get("exit_code", 1) != 0:
            return very_low_fitness()
        return match_score
    except Exception:
        return very_low_fitness()
