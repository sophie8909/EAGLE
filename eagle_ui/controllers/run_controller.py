"""Non-blocking lifecycle wrapper around the canonical EAGLE CLI."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from datetime import datetime
from urllib.parse import urlparse

from eagle.config import ExperimentConfig
from eagle.llm_profiles import load_role_profiles
from eagle_ui.controllers.config_controller import update_minimal_yaml

from eagle_ui.state import RunState
from eagle.runtime.process_logs import ProcessLogRecord


PROGRESS_PATTERN = re.compile(
    r"\[gen\s+(?P<generation>\d+)\s+cand\s+(?P<index>\d+)/(?P<total>\d+)\]\s+"
    r"(?P<candidate>\S+)\s+(?:stage=(?P<stage>\S+)\s+)?status=(?P<status>\S+)"
)
RUN_DIR_PATTERN = re.compile(r"^run_dir=(?P<path>.+)$")
BEST_PATTERN = re.compile(
    r"^best_candidate=(?P<candidate>\S+) objectives=\{'game_performance': (?P<game>-?[0-9.eE+]+), 'code_quality': (?P<quality>-?[0-9.eE+]+)\}$"
)


@dataclass(frozen=True)
class EALLMConnection:
    """LLM values the selected EA configuration will resolve at startup."""

    mode: str
    topology_path: Path | None
    endpoints: tuple[str, ...]
    ports: tuple[int, ...]
    models: tuple[str, ...]

    @property
    def endpoint_text(self) -> str:
        return "mock" if self.mode == "mock" else ", ".join(self.endpoints)

    @property
    def port_text(self) -> str:
        return "mock" if self.mode == "mock" else ", ".join(str(port) for port in self.ports)

    @property
    def model_text(self) -> str:
        return "mock" if self.mode == "mock" else ", ".join(self.models)


class RunController:
    """Own exactly one child CLI process and its reader thread."""

    def __init__(self, repository_root: Path, state: RunState) -> None:
        self.repository_root = repository_root
        self.state = state
        self._process: subprocess.Popen[str] | None = None
        self._readers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._process_kind = "evolution"
        self._stop_requested = False

    def config_choices(self) -> list[Path]:
        return sorted((self.repository_root / "configs").glob("*.yaml"))

    def validate(self, path: Path) -> ExperimentConfig:
        config = ExperimentConfig.from_file(path)
        config.validate()
        return config

    def load_fields(self, path: Path) -> dict[str, object]:
        config = ExperimentConfig.from_file(path)
        return {
            "population_size": config.population_size,
            "generations": config.generations,
            "random_seed": config.random_seed,
            "opponent": config.opponent,
            "map_path": config.map_path,
            "runs_dir": str(config.runs_dir),
        }

    def resolve_llm_connection(self, path: Path, *, mock: bool = False) -> EALLMConnection:
        """Resolve the same topology endpoint, port, and model used by the EA."""

        config = ExperimentConfig.from_file(path)
        if mock or config.generation_backend == "mock":
            return EALLMConnection(
                mode="mock",
                topology_path=None,
                endpoints=(),
                ports=(),
                models=(),
            )
        profiles = load_role_profiles(config.llm_role_topology_path)
        endpoints = tuple(dict.fromkeys(profile.base_url for profile in profiles.values()))
        ports = tuple(
            dict.fromkeys(
                parsed.port
                for endpoint in endpoints
                if (parsed := urlparse(endpoint)).port is not None
            )
        )
        models = tuple(dict.fromkeys(profile.model for profile in profiles.values()))
        return EALLMConnection(
            mode="openai",
            topology_path=config.llm_role_topology_path,
            endpoints=endpoints,
            ports=ports,
            models=models,
        )

    def save_fields(self, path: Path, values: dict[str, object]) -> ExperimentConfig:
        """Atomically save supported CLI config fields after canonical validation."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=path.suffix,
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(path.read_text(encoding="utf-8"))
        try:
            update_minimal_yaml(temporary, values)
            config = ExperimentConfig.from_file(temporary)
            config.validate()
            temporary.replace(path)
            return ExperimentConfig.from_file(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def map_choices(self) -> list[str]:
        maps_root = self.repository_root / "third_party" / "microrts"
        return sorted(str(path.relative_to(maps_root)) for path in (maps_root / "maps").rglob("*.xml"))

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
        self.state.best_candidate_id = None
        self.state.completed_candidates = 0
        self.state.failed_candidates = 0
        runs_dir = config.runs_dir if config.runs_dir.is_absolute() else self.repository_root / config.runs_dir
        self.state.effective_run_dir = runs_dir / run_id
        self.state.logs.clear()
        self._process_kind = "evolution"
        self._stop_requested = False
        self.state.logs.append(ProcessLogRecord.create(source="experiment", stream="system", process="eagle", message="launch: " + " ".join(command)))
        self._process = subprocess.Popen(
            command,
            cwd=self.repository_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._readers = [threading.Thread(target=self._read_stream, args=(self._process.stdout, "stdout"), name="eagle-gui-run-stdout"), threading.Thread(target=self._read_stream, args=(self._process.stderr, "stderr"), name="eagle-gui-run-stderr")]
        for reader in self._readers:
            reader.start()
        threading.Thread(target=self._wait_for_exit, name="eagle-gui-run-wait", daemon=True).start()

    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def shutdown(self) -> None:
        """Ensure GUI shutdown cannot leave a hidden child process alive."""
        self.stop()

    def stop(self) -> None:
        """Stop the active EA child process from the GUI."""
        self._stop_requested = True
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for reader in self._readers:
            if reader.is_alive():
                reader.join(timeout=2)

    def _read_stream(self, stream, name: str) -> None:
        process = self._process
        if process is None or stream is None:
            return
        for raw_line in stream:
            line = raw_line.rstrip("\r\n")
            with self._lock:
                self.state.logs.append(ProcessLogRecord.create(source="experiment", stream=name, process="eagle", message=line))
                if name == "stdout":
                    self._apply_progress(line)
            self._notify()

    def _wait_for_exit(self) -> None:
        process = self._process
        if process is None:
            return
        process_kind = self._process_kind
        returncode = process.wait()
        with self._lock:
            self.state.returncode = returncode
            self.state.running = False
            if returncode == 0 and process_kind == "evolution" and not self._stop_requested:
                self.state.logs.append(ProcessLogRecord.create(source="experiment", stream="system", process="eagle", message="successful end", severity="info"))
            self.state.logs.append(ProcessLogRecord.create(source="experiment", stream="system", process=process_kind, message=f"process exited with code {returncode}", severity="error" if returncode else "info"))
            if process_kind == "evolution" and returncode == 2:
                self.state.logs.append(ProcessLogRecord.create(source="experiment", stream="system", process="eagle", message="llm server error", severity="error"))
        self._notify()
        if (
            process_kind == "evolution"
            and returncode == 0
            and not self._stop_requested
            and not self.state.mock
            and self.state.effective_run_dir is not None
            and self.state.best_candidate_id is not None
        ):
            self._start_final_test()

    def _start_final_test(self) -> None:
        assert self.state.effective_run_dir is not None
        assert self.state.best_candidate_id is not None
        command = [
            sys.executable,
            "scripts/run_final_test.py",
            "--run-dir",
            str(self.state.effective_run_dir),
            "--candidate-id",
            self.state.best_candidate_id,
            "--config",
            str(self.repository_root / "configs" / "final_test_champions.yaml"),
        ]
        environment = dict(os.environ)
        environment["PYTHONUNBUFFERED"] = "1"
        try:
            process = subprocess.Popen(
                command,
                cwd=self.repository_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self.state.logs.append(ProcessLogRecord.create(source="final_test", stream="system", process="final_test", message=f"launch failed: {exc}", severity="error"))
            self._notify()
            return
        self._process_kind = "final_test"
        self._process = process
        self.state.running = True
        self.state.returncode = None
        self.state.logs.append(ProcessLogRecord.create(source="final_test", stream="system", process="final_test", message="launch: " + " ".join(command)))
        self._readers = [
            threading.Thread(target=self._read_stream, args=(process.stdout, "stdout"), name="final-test-stdout"),
            threading.Thread(target=self._read_stream, args=(process.stderr, "stderr"), name="final-test-stderr"),
        ]
        for reader in self._readers:
            reader.start()
        threading.Thread(target=self._wait_for_exit, name="final-test-wait", daemon=True).start()
    def _apply_progress(self, line: str) -> None:
        match = PROGRESS_PATTERN.search(line)
        if match:
            self.state.current_generation = int(match.group("generation"))
            self.state.current_candidate = match.group("candidate")
            if match.group("status") == "started":
                return
            if match.group("status") == "failed":
                self.state.failed_candidates += 1
            else:
                self.state.completed_candidates += 1
            return
        run_match = RUN_DIR_PATTERN.match(line)
        if run_match:
            path = Path(run_match.group("path"))
            self.state.effective_run_dir = path if path.is_absolute() else self.repository_root / path
            return
        best_match = BEST_PATTERN.match(line)
        if best_match:
            if float(best_match.group("game")) > -1000.0 and float(best_match.group("quality")) > -1000.0:
                self.state.best_candidate_id = best_match.group("candidate")

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()
