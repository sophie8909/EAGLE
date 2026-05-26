"""Process state services for detachable GUI run monitoring."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .config_service import write_json_file


def parse_optional_pid(value: Any) -> int | None:
    """Parse a positive process id from persisted GUI process state."""
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def process_is_running(pid: int | None) -> bool:
    """Return whether a process id is currently alive."""
    if pid is None:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            int(pid),
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return ctypes.windll.kernel32.GetLastError() == 5
    try:
        os.kill(int(pid), 0)
    except ValueError:
        return False
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def terminate_process_tree(pid: int) -> None:
    """Terminate a restored process id, including children where supported."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if process_is_running(pid):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                return
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return


def load_process_state(path: Path) -> dict[str, Any]:
    """Load persisted process state when it exists."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Process state JSON must be an object: {path}")
    return payload


def write_process_state(
    path: Path,
    *,
    pid: int,
    command: list[str],
    cwd: Path,
    log_path: Path,
    config_path: Path,
) -> None:
    """Persist enough process metadata for a reopened GUI to resume monitoring."""
    write_json_file(
        path,
        {
            "status": "running",
            "pid": int(pid),
            "command": list(command),
            "cwd": str(cwd),
            "log_path": str(log_path),
            "config_path": str(config_path),
            "started_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def mark_process_state(path: Path, *, status: str, returncode: int | None = None) -> None:
    """Update persisted process state with a terminal or transitional status."""
    state = load_process_state(path)
    if not state:
        return
    state["status"] = status
    state[f"{status}_at"] = datetime.now().isoformat(timespec="seconds")
    if returncode is not None:
        state["returncode"] = int(returncode)
    write_json_file(path, state)

