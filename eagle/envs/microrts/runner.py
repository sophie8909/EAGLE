"""Execution helpers for running vendored MicroRTS matches."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ...project import MICRORTS_LOGS_DIR, PROJECT_ROOT, ensure_project_directories
from ...utils.fitness_calculator import calculate_fitness_score
from .compiler import compile_microrts, locate_microrts_root
from .parser import parse_game_log


def _config_path(project_root: Path | None = None) -> Path:
    """Return the MicroRTS runtime properties file."""
    return locate_microrts_root(project_root) / "resources" / "config.properties"


def _prompt_path(project_root: Path | None = None) -> Path:
    """Return the prompt file consumed by the EAGLE Java agents."""
    return locate_microrts_root(project_root) / "prompt.txt"


def _runtime_logs_dir(project_root: Path | None = None) -> Path:
    """Return the MicroRTS runtime log directory."""
    ensure_project_directories()
    return MICRORTS_LOGS_DIR if project_root is None else (project_root or PROJECT_ROOT).resolve() / "logs" / "microrts"


def save_prompt(project_root: Path | None, prompt: str) -> Path:
    """Write the rendered EAGLE prompt for the next MicroRTS run."""
    prompt_path = _prompt_path(project_root)
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def read_config_properties(project_root: Path | None = None) -> dict[str, str]:
    """Read `config.properties` into a plain dictionary."""
    properties: dict[str, str] = {}
    for raw_line in _config_path(project_root).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def set_config_property(project_root: Path | None, key: str, value: str) -> Path:
    """Update one runtime property in the vendored MicroRTS config."""
    config_path = _config_path(project_root)
    lines = config_path.read_text(encoding="utf-8").splitlines()
    updated = False
    rendered: list[str] = []
    for line in lines:
        if line.startswith(f"{key}="):
            rendered.append(f"{key}={value}")
            updated = True
        else:
            rendered.append(line)
    if not updated:
        rendered.append(f"{key}={value}")
    config_path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    return config_path


def set_ai1(project_root: Path | None, ai1: str) -> Path:
    """Set the MicroRTS player-one Java agent class."""
    return set_config_property(project_root, "AI1", ai1)


def set_opponent(project_root: Path | None, opponent: str) -> Path:
    """Set the MicroRTS player-two Java agent class."""
    return set_config_property(project_root, "AI2", opponent)


def set_llm_interval(project_root: Path | None, llm_interval: int) -> Path:
    """Set the runtime LLM refresh interval for EAGLE Java agents."""
    return set_config_property(project_root, "llm_interval", str(int(llm_interval)))


def _target_agent_name(ai1_class: str | None) -> str:
    """Convert a fully qualified Java class name into the short log target name."""
    if not ai1_class:
        return "EAGLE"
    return str(ai1_class).split(".")[-1]


def _make_log_path(project_root: Path | None = None, prefix: str = "run") -> Path:
    """Create a timestamped runtime log path under the shared log directory."""
    logs_dir = _runtime_logs_dir(project_root)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return logs_dir / f"{prefix}_{timestamp}.log"


def launch_java_match(
    *,
    project_root: Path | None,
    run_time_per_game_sec: int,
    log_path: Path,
) -> tuple[int, bool, str]:
    """Launch one Java MicroRTS game and capture its combined log output."""
    microrts_root = locate_microrts_root(project_root)
    bin_dir = microrts_root / "bin"
    lib_dir = microrts_root / "lib"
    classpath = f"{lib_dir / '*'}{os.pathsep}{bin_dir}"
    command = ["java", "-cp", classpath, "rts.MicroRTS"]

    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            cwd=microrts_root,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        timed_out = False
        try:
            exit_code = process.wait(timeout=max(1, int(run_time_per_game_sec)))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            exit_code = process.wait()
            with log_path.open("a", encoding="utf-8") as append_stream:
                append_stream.write(
                    f"\n[python-runner] timed out after {run_time_per_game_sec} seconds.\n"
                )
    elapsed = time.perf_counter() - started
    return exit_code, timed_out, str(log_path), elapsed


def detect_timeout(log_content: str) -> bool:
    """Heuristically detect whether the match log indicates timeout termination."""
    lowered = log_content.lower()
    return "timed out" in lowered or "timeout" in lowered


def get_latest_log_file(project_root: Path | None = None) -> Path | None:
    """Return the newest shared runtime log file."""
    logs_dir = _runtime_logs_dir(project_root)
    log_files = sorted(logs_dir.glob("run_*.log"))
    return log_files[-1] if log_files else None


def run_java_agent_game(
    *,
    project_root: Path | None,
    config,
    ai1_class: str,
    opponent: str | None,
    prompt: str | None = None,
    compile_first: bool = True,
    log_prefix: str = "run",
) -> tuple[list[float], dict[str, Any]]:
    """Run one MicroRTS game with explicit Java agent classes."""
    project_root = (project_root or PROJECT_ROOT).resolve()
    microrts_root = locate_microrts_root(project_root)
    if compile_first:
        compile_microrts(project_root)

    original_config = _config_path(project_root).read_text(encoding="utf-8")
    try:
        if prompt is not None:
            save_prompt(project_root, prompt)
        set_ai1(project_root, ai1_class)
        if opponent is not None:
            set_opponent(project_root, opponent)
        set_llm_interval(project_root, config.llm_interval)

        log_path = _make_log_path(project_root, prefix=log_prefix)
        exit_code, timed_out, log_path_str, game_time_sec = launch_java_match(
            project_root=project_root,
            run_time_per_game_sec=int(config.run_time_per_game_sec),
            log_path=log_path,
        )
        log_content = Path(log_path_str).read_text(encoding="utf-8", errors="replace")
        parsed_log = parse_game_log(log_content, target_agent=_target_agent_name(ai1_class))
        fitness = calculate_fitness_score(
            log_content,
            resource_advantage_alpha=config.resource_advantage_alpha,
            resource_advantage_weights=config.resource_advantage_weights,
            parsed_log=parsed_log,
        )
        metadata = {
            "parsed_log": parsed_log,
            "winner": parsed_log.get("summary", {}).get("winner"),
            "timeout": bool(timed_out or detect_timeout(log_content)),
            "log_path": log_path_str,
            "llm_calls": parsed_log.get("summary", {}).get("segment_count", 0),
            "exit_code": exit_code,
            "game_time_sec": game_time_sec,
            "microrts_root": str(microrts_root),
        }
        return fitness, metadata
    finally:
        _config_path(project_root).write_text(original_config, encoding="utf-8")


def run_prompt_based_game(
    *,
    project_root: Path | None,
    config,
    prompt: str,
    opponent: str | None,
    test: bool = False,
) -> tuple[list[float], dict[str, Any]]:
    """Run one real EAGLE-vs-opponent match driven by the prompt file."""
    return run_java_agent_game(
        project_root=project_root,
        config=config,
        ai1_class="ai.abstraction.EAGLE",
        opponent=opponent,
        prompt=prompt,
        compile_first=True,
        log_prefix="run" if not test else "run_test",
    )
