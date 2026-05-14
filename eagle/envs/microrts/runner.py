"""Execution helpers for running vendored MicroRTS matches."""

from __future__ import annotations

import os
import random
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ...project import MICRORTS_LOGS_DIR, PROJECT_ROOT, ensure_project_directories
from ...utils.fitness_calculator import calculate_match_score
from .compiler import compile_microrts, locate_microrts_root
from .parser import parse_game_log


def _config_path(project_root: Path | None = None) -> Path:
    """Return the MicroRTS runtime properties file."""
    return locate_microrts_root(project_root) / "resources" / "config.properties"


def _prompt_path(project_root: Path | None = None) -> Path:
    """Return the prompt file consumed by the EAGLE Java agents."""
    return locate_microrts_root(project_root) / "prompt.txt"


def _runtime_logs_dir(project_root: Path | None = None, runtime_logs_dir: Path | None = None) -> Path:
    """Return the MicroRTS runtime log directory."""
    ensure_project_directories()
    if runtime_logs_dir is not None:
        runtime_logs_dir.mkdir(parents=True, exist_ok=True)
        return runtime_logs_dir
    return MICRORTS_LOGS_DIR if project_root is None else (project_root or PROJECT_ROOT).resolve() / "logs" / "microrts"


def _trace_logs_dir(project_root: Path | None = None, runtime_logs_dir: Path | None = None) -> Path:
    """Return the directory used for saved trace artifacts."""
    base_dir = _runtime_logs_dir(project_root, runtime_logs_dir=runtime_logs_dir)
    trace_dir = base_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    return trace_dir


def _generation_folder_name(generation: int | None) -> str:
    """Return the folder name used for one generation's match artifacts."""
    if generation is None:
        return "gen_unknown"
    display_generation = max(0, int(generation) + 1)
    return f"gen_{display_generation:02d}"


def _generation_runtime_dir(
    project_root: Path | None = None,
    runtime_logs_dir: Path | None = None,
    generation: int | None = None,
) -> Path:
    """Return the per-generation directory used for match logs and traces."""
    base_dir = _runtime_logs_dir(project_root, runtime_logs_dir=runtime_logs_dir)
    generation_dir = base_dir / _generation_folder_name(generation)
    generation_dir.mkdir(parents=True, exist_ok=True)
    return generation_dir


def _configured_map_dir(config: Any) -> str:
    """Return the configured maps/ subfolder used for gameplay evaluation."""
    raw_dir = str(getattr(config, "gameplay_map_dir", "8x8") or "8x8").strip().strip("/\\")
    return raw_dir or "8x8"


def select_random_map_location(project_root: Path | None, config: Any) -> str:
    """Select one XML map from the configured MicroRTS map folder."""
    map_dir_name = _configured_map_dir(config)
    maps_dir = locate_microrts_root(project_root) / "maps" / map_dir_name
    candidates = sorted(path for path in maps_dir.glob("*.xml") if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No MicroRTS XML maps found under maps/{map_dir_name}.")
    selected = random.choice(candidates)
    return f"maps/{map_dir_name}/{selected.name}"


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


def _make_log_path(
    project_root: Path | None = None,
    prefix: str = "run",
    runtime_logs_dir: Path | None = None,
) -> Path:
    """Create a timestamped runtime log path under the shared log directory."""
    logs_dir = _runtime_logs_dir(project_root, runtime_logs_dir=runtime_logs_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    normalized_prefix = str(prefix or "run").strip().lower()
    if normalized_prefix == "run":
        filename = f"run_{timestamp}.log"
    elif normalized_prefix == "run_test":
        filename = f"run_{timestamp}_test.log"
    elif normalized_prefix == "run_surrogate":
        filename = f"run_{timestamp}_surrogate.log"
    elif normalized_prefix == "run_test_surrogate":
        filename = f"run_{timestamp}_test_surrogate.log"
    elif normalized_prefix == "run_eagle_policy":
        filename = f"run_{timestamp}_eaglePolicy.log"
    elif normalized_prefix == "run_test_eagle_policy":
        filename = f"run_{timestamp}_test_eaglePolicy.log"
    elif normalized_prefix == "run_eagle_java":
        filename = f"run_{timestamp}_eagleJava.log"
    elif normalized_prefix == "run_test_eagle_java":
        filename = f"run_{timestamp}_test_eagleJava.log"
    else:
        filename = f"{normalized_prefix}_{timestamp}.log"
    return logs_dir / filename


def _make_trace_prefix(
    project_root: Path | None = None,
    prefix: str = "run_test",
    runtime_logs_dir: Path | None = None,
    generation: int | None = None,
) -> Path:
    """Create a timestamped output prefix for one recorded trace."""
    trace_dir = _generation_runtime_dir(project_root, runtime_logs_dir=runtime_logs_dir, generation=generation)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    normalized_prefix = str(prefix or "run_test").strip().lower()
    return trace_dir / f"{normalized_prefix}_{timestamp}"


def launch_java_match(
    *,
    project_root: Path | None,
    tick_limit: int,
    log_path: Path,
    ai1_class: str | None = None,
    ai2_class: str | None = None,
    prompt_path: Path | None = None,
    llm_interval: int | None = None,
    llm_call_limit: int | None = None,
    max_game_ticks: int | None = None,
    trace_path: Path | None = None,
    map_location: str | None = None,
) -> tuple[int, bool, str, float]:
    """Launch one Java MicroRTS game and capture its combined log output."""
    microrts_root = locate_microrts_root(project_root)
    bin_dir = microrts_root / "bin"
    lib_dir = microrts_root / "lib"
    classpath = f"{lib_dir / '*'}{os.pathsep}{bin_dir}"
    command = ["java"]
    if prompt_path is not None:
        command.append(f"-Dmicrorts.prompt={prompt_path}")
    if llm_interval is not None:
        command.append(f"-Dmicrorts.llm_interval={int(llm_interval)}")
    if llm_call_limit is not None:
        command.append(f"-Dmicrorts.llm_call_limit={int(llm_call_limit)}")
    if max_game_ticks is not None:
        command.append(f"-Dmicrorts.tick_limit={int(max_game_ticks)}")
    if trace_path is not None:
        command.append(f"-Dmicrorts.trace.path={trace_path}")
    command.extend(["-cp", classpath, "rts.MicroRTS"])
    command.extend(["--headless", "true"])
    if max_game_ticks is not None:
        command.extend(["-c", str(int(max_game_ticks))])
    if map_location is not None:
        command.extend(["-m", map_location])
    if ai1_class is not None:
        command.extend(["--ai1", ai1_class])
    if ai2_class is not None:
        command.extend(["--ai2", ai2_class])

    print(
        "[DEBUG] microrts launch "
        f"cwd={microrts_root} max_ticks={max_game_ticks or tick_limit} log={log_path} "
        f"map={map_location} ai1={ai1_class} ai2={ai2_class}",
        flush=True,
    )
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            cwd=microrts_root,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ.copy(), "EAGLE_FORCE_EXIT_ON_GAME_OVER": "1"},
        )
        timed_out = False
        wall_clock_safety_sec = max(3600, int(tick_limit) * 30)
        try:
            exit_code = process.wait(timeout=wall_clock_safety_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            exit_code = process.wait()
            with log_path.open("a", encoding="utf-8") as append_stream:
                append_stream.write(
                    f"\n[python-runner] wall-clock safety stop after {wall_clock_safety_sec} seconds.\n"
                )
    elapsed = time.perf_counter() - started
    print(
        "[DEBUG] microrts complete "
        f"exit_code={exit_code} timed_out={timed_out} elapsed={elapsed:.2f}s log={log_path}",
        flush=True,
    )
    return exit_code, timed_out, str(log_path), elapsed


def record_java_match_trace(
    *,
    project_root: Path | None,
    ai1_class: str,
    ai2_class: str,
    output_prefix: Path,
    max_cycles: int,
    map_location: str,
) -> dict[str, str] | None:
    """Record one additional trace file for later GUI replay."""
    microrts_root = locate_microrts_root(project_root)
    bin_dir = microrts_root / "bin"
    lib_dir = microrts_root / "lib"
    classpath = f"{lib_dir / '*'}{os.pathsep}{bin_dir}"
    command = [
        "java",
        "-cp",
        classpath,
        "tests.trace.RecordLLMGame",
        ai1_class,
        ai2_class,
        str(output_prefix),
        str(int(max_cycles)),
        str(map_location),
    ]
    try:
        subprocess.run(
            command,
            cwd=microrts_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    xml_path = output_prefix.with_suffix(".xml")
    json_path = output_prefix.with_suffix(".json")
    result: dict[str, str] = {}
    if xml_path.exists():
        result["trace_xml_path"] = str(xml_path)
    if json_path.exists():
        result["trace_json_path"] = str(json_path)
    return result or None


def detect_timeout(log_content: str) -> bool:
    """Heuristically detect whether the match log indicates timeout termination."""
    lowered = log_content.lower()
    return "wall-clock safety stop" in lowered


def detect_tick_timeout(parsed_log: dict[str, Any], max_game_ticks: int) -> bool:
    """Return whether MicroRTS ended by reaching the configured tick budget."""
    summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else {}
    final_tick = summary.get("final_tick")
    if final_tick is None:
        resource_history = list(summary.get("resource_history") or [])
        if resource_history:
            final_tick = resource_history[-1].get("time")
    try:
        return int(final_tick) >= int(max_game_ticks)
    except (TypeError, ValueError):
        return False


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
    runtime_logs_dir: Path | None = None,
    record_trace: bool = False,
    generation: int | None = None,
    individual_id: Any | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Run one MicroRTS game with explicit Java agent classes."""
    project_root = (project_root or PROJECT_ROOT).resolve()
    microrts_root = locate_microrts_root(project_root)
    print(
        "[DEBUG] gameplay setup "
        f"ai1={ai1_class} opponent={opponent} compile_first={compile_first} prefix={log_prefix}",
        flush=True,
    )
    compile_time_sec = 0.0
    if compile_first:
        compile_started = time.perf_counter()
        compile_microrts(project_root)
        compile_time_sec = time.perf_counter() - compile_started

    prompt_path: Path | None = None
    if prompt is not None:
        generation_dir = _generation_runtime_dir(project_root, runtime_logs_dir=runtime_logs_dir, generation=generation)
        prompt_dir = generation_dir / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        safe_ai_name = _target_agent_name(ai1_class)
        prompt_path = prompt_dir / f"prompt_{safe_ai_name}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
    try:
        generation_runtime_dir = _generation_runtime_dir(
            project_root,
            runtime_logs_dir=runtime_logs_dir,
            generation=generation,
        )
        log_path = _make_log_path(project_root, prefix=log_prefix, runtime_logs_dir=generation_runtime_dir)
        trace_stem_parts = [
            str(log_prefix or "run"),
            f"ind_{individual_id}" if individual_id is not None else "ind_unknown",
            _target_agent_name(ai1_class),
            datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f"),
        ]
        trace_path = generation_runtime_dir / ("trace_" + "_".join(trace_stem_parts) + ".xml")
        max_game_ticks = int(getattr(config, "tick_limit", 5000))
        map_location = select_random_map_location(project_root, config)
        exit_code, timed_out, log_path_str, game_time_sec = launch_java_match(
            project_root=project_root,
            tick_limit=max_game_ticks,
            log_path=log_path,
            ai1_class=ai1_class,
            ai2_class=opponent,
            prompt_path=prompt_path,
            llm_interval=config.active_llm_interval(),
            llm_call_limit=int(getattr(config, "llm_call_limit", 50)),
            max_game_ticks=max_game_ticks,
            trace_path=trace_path,
            map_location=map_location,
        )
        log_content = Path(log_path_str).read_text(encoding="utf-8", errors="replace")
        parsed_log = parse_game_log(log_content, target_agent=_target_agent_name(ai1_class))
        match_score = calculate_match_score(
            log_content,
            resource_advantage_weights=config.resource_advantage_weights,
            parsed_log=parsed_log,
        )
        metadata = {
            "parsed_log": parsed_log,
            "winner": parsed_log.get("summary", {}).get("winner"),
            "timeout": bool(timed_out or detect_timeout(log_content) or detect_tick_timeout(parsed_log, max_game_ticks)),
            "timeout_type": "tick" if detect_tick_timeout(parsed_log, max_game_ticks) else "wall_clock" if timed_out else None,
            "log_path": log_path_str,
            "trace_xml_path": str(trace_path) if trace_path.exists() else None,
            "map_location": map_location,
            "gameplay_map_dir": _configured_map_dir(config),
            "tick_limit": max_game_ticks,
            "llm_call_limit": int(getattr(config, "llm_call_limit", 50)),
            "llm_calls": parsed_log.get("summary", {}).get(
                "llm_call_count",
                parsed_log.get("summary", {}).get("segment_count", 0),
            ),
            "exit_code": exit_code,
            "game_time_sec": game_time_sec,
            "compile_time_sec": compile_time_sec,
            "microrts_root": str(microrts_root),
            "prompt_path": str(prompt_path) if prompt_path is not None else None,
        }
        summary = parsed_log.get("summary", {})
        print(
            "[DEBUG] gameplay parsed "
            f"ai1={ai1_class} opponent={opponent} winner={metadata['winner']} "
            f"timeout={metadata['timeout']} score={match_score} "
            f"resource_rows={len(summary.get('resource_history') or [])} "
            f"feature_rows={len(summary.get('feature_history') or [])}",
            flush=True,
        )
        return match_score, metadata
    finally:
        pass


def run_prompt_based_game(
    *,
    project_root: Path | None,
    config,
    prompt: str,
    opponent: str | None,
    test: bool = False,
    runtime_logs_dir: Path | None = None,
    generation: int | None = None,
    individual_id: Any | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Run one gameplay EAGLE-vs-opponent match driven by the prompt file."""
    return run_java_agent_game(
        project_root=project_root,
        config=config,
        ai1_class="ai.abstraction.EAGLE",
        opponent=opponent,
        prompt=prompt,
        compile_first=True,
        log_prefix="run" if not test else "run_test",
        runtime_logs_dir=runtime_logs_dir,
        record_trace=True,
        generation=generation,
        individual_id=individual_id,
    )
