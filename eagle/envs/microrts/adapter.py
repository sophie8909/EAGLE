"""MicroRTS runtime adapter used by evaluation and surrogate validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...project import PROJECT_ROOT
from ...surrogate.compiler.eagle_policy_spec import compile_prompt_to_eagle_policy_spec
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
    ai1_class: str = "ai.abstraction.eaglePolicy",
    eagle_policy_spec: dict[str, object] | None = None,
    test: bool = False,
    runtime_logs_dir: Path | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Render one eaglePolicy Java agent and run a validation match."""
    from ...surrogate.eval.eagle_policy_renderer import render_eagle_policy_agent

    root = (project_root or PROJECT_ROOT).resolve()
    eagle_policy_spec = eagle_policy_spec or compile_prompt_to_eagle_policy_spec(prompt)[1]
    render_eagle_policy_agent(root, prompt, eagle_policy_spec)
    return run_java_agent_game(
        project_root=root,
        config=config,
        ai1_class=ai1_class,
        opponent=opponent,
        prompt=prompt,
        compile_first=True,
        log_prefix="run_eagle_policy" if not test else "run_test_eagle_policy",
        runtime_logs_dir=runtime_logs_dir,
        record_trace=bool(test and getattr(config, "save_trace_on_test", False)),
        llm_call_limit=int(getattr(config, "llm_call_limit", 50)),
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
