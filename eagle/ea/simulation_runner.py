from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path
from typing import Any

from .fitness_calculator import calculate_fitness_score
from .llm import LLM
from .log_parse import parse_log
from .profiler import timer
from .surrogate_agent_generator import render_surrogate_agent


def save_prompt(repo_root: Path, prompt: str) -> None:
    """Write the rendered prompt to the file consumed by the game runner."""
    prompt_path = repo_root / "prompt.txt"
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)


def set_opponent(repo_root: Path, opponent: str) -> None:
    """Patch `config.properties` so the next run uses the selected opponent AI."""
    _set_config_property(repo_root, "AI2", opponent)


def set_ai1(repo_root: Path, ai1: str) -> None:
    """Patch `config.properties` so the next run uses the requested player-1 AI."""
    _set_config_property(repo_root, "AI1", ai1)


def set_llm_interval(repo_root: Path, llm_interval: int) -> None:
    """Patch `config.properties` so Java agents can read the configured LLM interval."""
    _set_config_property(repo_root, "llm_interval", str(int(llm_interval)))


def _set_config_property(repo_root: Path, key: str, value: str) -> None:
    """Update or append one key-value pair inside `config.properties`."""
    config_path = repo_root / "resources" / "config.properties"
    with open(config_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    updated = False
    with open(config_path, "w", encoding="utf-8") as f:
        for line in lines:
            if line.startswith(f"{key}="):
                f.write(f"{key}={value}\n")
                updated = True
            else:
                f.write(line)
        if not updated:
            if lines and not lines[-1].endswith("\n"):
                f.write("\n")
            f.write(f"{key}={value}\n")


def launch_simulation(repo_root: Path, config, test: bool = False) -> subprocess.Popen[str]:
    """Start the shell script that launches one MicroRTS match."""
    run_loop = repo_root / ("RunLoop_5000.sh" if test else "RunLoop.sh")
    env = os.environ.copy()
    env["RUN_TIME_PER_GAME_SEC"] = str(config.run_time_per_game_sec)
    return subprocess.Popen(
        [str(run_loop)],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def wait_for_simulation(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Wait for the launched process to finish and return stdout/stderr."""
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        print(f"Simulation process exited with code {process.returncode}")
        if stderr:
            print(f"Simulation error output:\n{stderr}")
    return stdout, stderr


def get_latest_log_file(repo_root: Path) -> Path | None:
    """Return the most recent `run_*.log` file from the logs directory."""
    log_files = glob.glob(str(repo_root / "logs" / "run_*.log"))
    if not log_files:
        return None
    return Path(sorted(log_files)[-1])


def detect_timeout(log_content: str) -> bool:
    """Heuristically detect timeout-related termination markers in a log."""
    lower_content = log_content.lower()
    return "timeout" in lower_content or "timed out" in lower_content


def simulate_games(
    repo_root: Path,
    config,
    opponent: str | None,
    stats: dict[str, float],
) -> tuple[list[float], dict[str, Any]]:
    """Run one full match, parse the resulting log, and compute real fitness."""
    with timer("bookkeeping_time", stats):
        set_llm_interval(repo_root, config.llm_interval)
        if opponent is not None:
            set_opponent(repo_root, opponent)

    with timer("game_launch_time", stats):
        process = launch_simulation(repo_root, config)

    with timer("game_play_time", stats):
        _, stderr = wait_for_simulation(process)
        if process.returncode != 0:
            if stderr:
                print(stderr)
            return [0.0, 0.0], {
                "parsed_log": None,
                "winner": None,
                "timeout": True,
                "log_path": None,
                "llm_calls": 0,
            }

    latest_log_file = get_latest_log_file(repo_root)
    if latest_log_file is None:
        return [0.0, 0.0], {
            "parsed_log": None,
            "winner": None,
            "timeout": True,
            "log_path": None,
            "llm_calls": 0,
        }

    print(f"Testing parse_fitness with log file: {latest_log_file}")
    with open(latest_log_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    with timer("log_parse_time", stats):
        parsed_log = parse_log(log_content)

    fitness = calculate_fitness_score(
        log_content,
        resource_advantage_alpha=config.resource_advantage_alpha,
        resource_advantage_weights=config.resource_advantage_weights,
        parsed_log=parsed_log,
    )
    metadata = {
        "parsed_log": parsed_log,
        "winner": parsed_log.get("summary", {}).get("winner"),
        "timeout": detect_timeout(log_content),
        "log_path": str(latest_log_file),
        "llm_calls": parsed_log.get("summary", {}).get("segment_count", 0),
    }
    return fitness, metadata


def simulate_surrogate_games(
    repo_root: Path,
    config,
    prompt: str,
    opponent: str | None,
    stats: dict[str, float],
    ai1_class: str = "ai.abstraction.EAGLESurrogate",
) -> tuple[list[float], dict[str, Any]]:
    """Run one match using the generated surrogate Java agent for player 1."""
    config_path = repo_root / "resources" / "config.properties"
    original_config = config_path.read_text(encoding="utf-8")
    surrogate_spec = LLM.ollama_generate_surrogate_strategy_spec(prompt)
    render_surrogate_agent(repo_root, prompt, surrogate_spec)

    try:
        with timer("bookkeeping_time", stats):
            set_llm_interval(repo_root, config.llm_interval)
            set_ai1(repo_root, ai1_class)
            if opponent is not None:
                set_opponent(repo_root, opponent)

        with timer("game_launch_time", stats):
            process = launch_simulation(repo_root, config)

        with timer("game_play_time", stats):
            _, stderr = wait_for_simulation(process)
            if process.returncode != 0:
                if stderr:
                    print(stderr)
                return [0.0, 0.0], {
                    "parsed_log": None,
                    "winner": None,
                    "timeout": True,
                    "log_path": None,
                    "llm_calls": 0,
                }

        latest_log_file = get_latest_log_file(repo_root)
        if latest_log_file is None:
            return [0.0, 0.0], {
                "parsed_log": None,
                "winner": None,
                "timeout": True,
                "log_path": None,
                "llm_calls": 0,
            }

        with open(latest_log_file, "r", encoding="utf-8") as f:
            log_content = f.read()

        with timer("log_parse_time", stats):
            parsed_log = parse_log(log_content)

        fitness = calculate_fitness_score(
            log_content,
            resource_advantage_alpha=config.resource_advantage_alpha,
            resource_advantage_weights=config.resource_advantage_weights,
            parsed_log=parsed_log,
        )
        metadata = {
            "parsed_log": parsed_log,
            "winner": parsed_log.get("summary", {}).get("winner"),
            "timeout": detect_timeout(log_content),
            "log_path": str(latest_log_file),
            "llm_calls": 0,
        }
        return fitness, metadata
    finally:
        config_path.write_text(original_config, encoding="utf-8")
