"""Service helpers for the NiceGUI EAGLE dashboard prototype."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from eagle_gui.services import analysis_service, process_service


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "eagle"
CONFIG_DIR = ROOT / "configs" / "evolution"
DEFAULT_CONFIG = CONFIG_DIR / "default.json"
GUI_WEB_PROCESS_STATE_PATH = LOG_DIR / "gui_web_process_state.json"
LOG_TAIL_LIMIT = 18_000


def timestamped_stem(prefix: str) -> str:
    """Return a filename stem with a timestamp suffix."""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def config_choices() -> list[str]:
    """Return available evolution config paths for the dashboard selector."""
    if not CONFIG_DIR.exists():
        return [str(DEFAULT_CONFIG)]
    paths = sorted(path for path in CONFIG_DIR.rglob("*.json") if path.is_file())
    if DEFAULT_CONFIG in paths:
        paths.remove(DEFAULT_CONFIG)
        paths.insert(0, DEFAULT_CONFIG)
    return [str(path) for path in paths] or [str(DEFAULT_CONFIG)]


def run_choices() -> list[str]:
    """Return EAGLE run directories newest first."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return [str(path) for path in sorted(LOG_DIR.iterdir(), reverse=True) if path.is_dir()]


def load_state() -> dict[str, Any]:
    """Load the web dashboard process state."""
    try:
        return process_service.load_process_state(GUI_WEB_PROCESS_STATE_PATH)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def monitored_pid() -> int | None:
    """Return the currently persisted process id when available."""
    return process_service.parse_optional_pid(load_state().get("pid"))


def process_running() -> bool:
    """Return whether the persisted web-dashboard process is still alive."""
    return process_service.process_is_running(monitored_pid())


def process_log_path() -> Path | None:
    """Return the persisted process log path when available."""
    state = load_state()
    value = state.get("log_path")
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def process_status_text() -> str:
    """Return compact status text for the dashboard badge."""
    pid = monitored_pid()
    if process_service.process_is_running(pid):
        return f"running pid {pid}"
    state = load_state()
    if pid is not None and state.get("status") == "running":
        process_service.mark_process_state(GUI_WEB_PROCESS_STATE_PATH, status="exited")
        return f"exited pid {pid}"
    return "not running"


def read_log_tail(limit: int = LOG_TAIL_LIMIT) -> str:
    """Read the current process log tail without loading unrelated logs."""
    path = process_log_path()
    if path is None:
        return "No process log selected."
    if not path.exists():
        return f"Log file does not exist: {path}"
    byte_limit = max(limit * 4, 4096)
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - byte_limit))
        data = handle.read()
    return data.decode("utf-8", errors="replace")[-limit:]


def start_experiment(config_path: Path) -> tuple[bool, str]:
    """Start an EAGLE experiment and persist process metadata."""
    if process_running():
        return False, "An experiment process is already running."
    selected_config = config_path.expanduser().resolve()
    if not selected_config.exists():
        return False, f"Config does not exist: {selected_config}"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"gui_web_process_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    command = [sys.executable, "-m", "eagle.main", "--config", str(selected_config)]
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    log_handle.write("Command: " + " ".join(command) + "\n\n")
    log_handle.flush()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process_service.write_process_state(
        GUI_WEB_PROCESS_STATE_PATH,
        pid=int(process.pid),
        command=command,
        cwd=ROOT,
        log_path=log_path,
        config_path=selected_config,
    )
    return True, f"Started PID {process.pid}"


def stop_experiment() -> str:
    """Terminate the persisted experiment process tree."""
    pid = monitored_pid()
    if pid is None or not process_service.process_is_running(pid):
        return "No running process."
    process_service.mark_process_state(GUI_WEB_PROCESS_STATE_PATH, status="stopping")
    process_service.terminate_process_tree(pid)
    return f"Stopping PID {pid}"


def build_analysis(run_dir: Path | None) -> tuple[str, str]:
    """Build the existing live-analysis report for one run."""
    if run_dir is None:
        return "No run selected", ""
    report = analysis_service.build_live_analysis_report(run_dir)
    return str(report.summary), str(report.body)


def load_prompt_records(run_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Load prompt records through the existing desktop analysis service."""
    return analysis_service.load_prompts(run_dir)


def prompt_record_label(record_id: str, record: dict[str, Any]) -> str:
    """Return a compact selector label for one prompt record."""
    generation = record.get("generation", "")
    individual = record.get("individual_id", "")
    mode = record.get("evaluation_mode", "")
    return f"gen {generation} | {individual} | {mode} | {record_id}"
