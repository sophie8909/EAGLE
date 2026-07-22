"""Non-blocking lifecycle wrapper around the canonical EAGLE CLI."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable
from datetime import datetime

from eagle.config import ExperimentConfig

from eagle_ui.state import RunState


PROGRESS_PATTERN = re.compile(r"\[gen\s+(?P<generation>\d+)\s+cand\s+(?P<index>\d+)/(?P<total>\d+)\]\s+(?P<candidate>\S+)\s+status=(?P<status>\S+)")
RUN_DIR_PATTERN = re.compile(r"^run_dir=(?P<path>.+)$")


class RunController:
    """Own exactly one child CLI process and its reader thread."""

    def __init__(self, repository_root: Path, state: RunState) -> None:
        self.repository_root = repository_root
        self.state = state
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._listeners: list[Callable[[], None]] = []

    def config_choices(self) -> list[Path]:
        return sorted((self.repository_root / "configs").glob("*.yaml"))

    def validate(self, path: Path) -> ExperimentConfig:
        config = ExperimentConfig.from_file(path)
        config.validate()
        return config

    def start(self, config_path: Path, *, mock: bool = False) -> None:
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("An EAGLE run is already active.")
        config = self.validate(config_path)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        command = [sys.executable, "scripts/run_eagle.py", "--config", str(config_path), "--run-id", run_id]
        if mock:
            command.append("--mock")
        environment = dict(os.environ)
        environment["PYTHONUNBUFFERED"] = "1"
        self.state.config_path = config_path
        self.state.mock = mock
        self.state.running = True
        self.state.returncode = None
        self.state.current_generation = None
        self.state.current_candidate = None
        self.state.completed_candidates = 0
        self.state.failed_candidates = 0
        runs_dir = config.runs_dir if config.runs_dir.is_absolute() else self.repository_root / config.runs_dir
        self.state.effective_run_dir = runs_dir / run_id
        self.state.log_lines.clear()
        self._process = subprocess.Popen(
            command,
            cwd=self.repository_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_output, name="eagle-gui-run-reader")
        self._reader.start()

    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def shutdown(self) -> None:
        """Ensure GUI shutdown cannot leave a hidden child process alive."""
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=2)

    def _read_output(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            with self._lock:
                self.state.log_lines.append(line)
                self._apply_progress(line)
            self._notify()
        returncode = process.wait()
        with self._lock:
            self.state.returncode = returncode
            self.state.running = False
        self._notify()

    def _apply_progress(self, line: str) -> None:
        match = PROGRESS_PATTERN.search(line)
        if match:
            self.state.current_generation = int(match.group("generation"))
            self.state.current_candidate = match.group("candidate")
            if match.group("status") == "failed":
                self.state.failed_candidates += 1
            else:
                self.state.completed_candidates += 1
            return
        run_match = RUN_DIR_PATTERN.match(line)
        if run_match:
            path = Path(run_match.group("path"))
            self.state.effective_run_dir = path if path.is_absolute() else self.repository_root / path

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()
