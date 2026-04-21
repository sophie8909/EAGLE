"""Thin compatibility layer between EAGLE modules and vendored MicroRTS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...project import PROJECT_ROOT
from ...surrogate.compiler import compile_prompt_to_surrogate_spec
from ...surrogate.eval.agent_generator import render_surrogate_agent
from .compiler import compile_microrts, locate_microrts_root
from .runner import (
    detect_timeout,
    get_latest_log_file,
    read_config_properties,
    run_java_agent_game,
    run_prompt_based_game,
    save_prompt,
    set_ai1,
    set_llm_interval,
    set_opponent,
)


def run_surrogate_validation_case(
    *,
    project_root: Path | None,
    config,
    prompt: str,
    opponent: str | None,
    ai1_class: str = "ai.abstraction.EAGLESurrogate",
    surrogate_spec: dict[str, object] | None = None,
    test: bool = False,
    runtime_logs_dir: Path | None = None,
) -> tuple[list[float], dict[str, Any]]:
    """Render one surrogate Java agent and run a validation match."""
    root = (project_root or PROJECT_ROOT).resolve()
    surrogate_spec = surrogate_spec or compile_prompt_to_surrogate_spec(prompt)[1]
    render_surrogate_agent(root, prompt, surrogate_spec)
    return run_java_agent_game(
        project_root=root,
        config=config,
        ai1_class=ai1_class,
        opponent=opponent,
        prompt=prompt,
        compile_first=True,
        log_prefix="run_surrogate" if not test else "run_test_surrogate",
        runtime_logs_dir=runtime_logs_dir,
    )


__all__ = [
    "compile_microrts",
    "detect_timeout",
    "get_latest_log_file",
    "locate_microrts_root",
    "read_config_properties",
    "run_java_agent_game",
    "run_prompt_based_game",
    "run_surrogate_validation_case",
    "save_prompt",
    "set_ai1",
    "set_llm_interval",
    "set_opponent",
]
