"""Local LLM server lifecycle owned by the EAGLE runtime.

The server manager owns model discovery, command construction, process
identity, readiness, output capture, and role association. It does not own GUI
state or evolutionary configuration. Remote endpoints are represented as
external server records and are tested, not launched, by this process.
"""

from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .process_logs import ProcessLogBuffer, ProcessLogRecord


SEMANTIC_ROLES = ("reflector", "rewriter", "generator")
SUPPORTED_LOCAL_MODELS = ("qwen3", "qwen3.5", "llama3.1")
RUNTIME_STATE_PATH = Path("experiment_env/runtime/runtime_state.local.json")


class ServerLifecycleError(RuntimeError):
    """Expected server lifecycle failure with actionable context."""


@dataclass(frozen=True)
class ServerSpec:
    server_id: str
    model_path: Path
    server_path: Path | str
    model_id: str
    host: str
    port: int
    context_size: int = 32768
    roles: tuple[str, ...] = ()

    @property
    def endpoint(self) -> str:
        advertised_host = "127.0.0.1" if self.host == "0.0.0.0" else self.host
        return f"http://{advertised_host}:{self.port}/v1"


@dataclass
class ServerStatus:
    server_id: str
    state: str
    endpoint: str
    model_id: str
    roles: tuple[str, ...]
    command: tuple[str, ...] = ()
    pid: int | None = None
    output: tuple[str, ...] = ()
    logs: tuple[ProcessLogRecord, ...] = ()
    error: str | None = None


@dataclass
class _ManagedServer:
    spec: ServerSpec
    process: subprocess.Popen[str]
    logs: ProcessLogBuffer = field(default_factory=ProcessLogBuffer)
    readers: list[threading.Thread] = field(default_factory=list)


class LLMServerManager:
    """Manage the actual local llama-server processes used by GUI roles."""

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()
        self._servers: dict[str, _ManagedServer] = {}
        self._lock = threading.Lock()

    @property
    def runtime_state_path(self) -> Path:
        return self.repository_root / RUNTIME_STATE_PATH

    def discover_models(self) -> list[Path]:
        roots = (self.repository_root / "experiment_env" / "model", self.repository_root / "models")
        discovered: dict[str, Path] = {}
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*.gguf"):
                if not path.is_file() or "llama.cpp" in path.parts:
                    continue
                model_id = canonical_local_model_id(path)
                if model_id is None:
                    continue
                candidate = path.absolute()
                current = discovered.get(model_id)
                if current is None or _model_path_priority(candidate) < _model_path_priority(current):
                    discovered[model_id] = candidate
        return [discovered[model_id] for model_id in SUPPORTED_LOCAL_MODELS if model_id in discovered]

    def resolve_server_path(self, configured: Path | str | None = None) -> Path:
        if configured:
            path = Path(configured).expanduser()
            if path.is_file():
                return path
            raise ServerLifecycleError(f"llama-server executable does not exist: {path}")
        configured_env = os.environ.get("LLAMA_SERVER_BIN", "").strip()
        candidate = shutil.which(configured_env or "llama-server")
        if candidate:
            return Path(candidate)
        for candidate_path in (
            self.repository_root / "experiment_env" / "model" / "llama.cpp" / "llama.cpp" / "build-eagle" / "bin" / "llama-server",
            self.repository_root / "experiment_env" / "model" / "llama.cpp" / "llama.cpp" / "build" / "bin" / "llama-server",
            self.repository_root / "experiment_env" / "model" / "llama.cpp" / "build" / "bin" / "llama-server",
        ):
            if candidate_path.is_file():
                return candidate_path
        registry = self.repository_root / "experiment_env" / "model" / "model_registry.local.json"
        if registry.is_file():
            try:
                configured_path = json.loads(registry.read_text(encoding="utf-8")).get("llama_server_binary")
            except (OSError, json.JSONDecodeError):
                configured_path = None
            if configured_path:
                path = Path(str(configured_path)).expanduser()
                if not path.is_absolute():
                    path = self.repository_root / path
                if path.is_file():
                    return path
        raise ServerLifecycleError("llama-server was not found; select an executable or set LLAMA_SERVER_BIN.")

    @staticmethod
    def find_available_port(preferred: int = 8080, *, attempts: int = 100) -> int:
        """Find a free local port, starting at the GUI's preferred port."""

        if not 1 <= preferred <= 65535:
            preferred = 8080
        last_port = min(65535, preferred + attempts - 1)
        for port in range(preferred, last_port + 1):
            with socket.socket() as sock:
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError:
                    continue
                return port
        raise ServerLifecycleError(f"no available local server port found from {preferred}.")

    @staticmethod
    def build_command(spec: ServerSpec) -> list[str]:
        if not 1 <= spec.port <= 65535:
            raise ValueError("server port must be between 1 and 65535")
        if spec.context_size < 1:
            raise ValueError("server context size must be positive")
        generation_threads = max(1, min(8, os.cpu_count() or 1))
        return [
            str(spec.server_path),
            "--model", str(spec.model_path),
            "--alias", spec.model_id,
            "--reasoning", "off",
            "--parallel", "1",
            "--threads", str(generation_threads),
            "--threads-batch", str(generation_threads),
            "--ctx-size", str(spec.context_size),
            "--host", spec.host,
            "--port", str(spec.port),
        ]

    def start(self, spec: ServerSpec, *, readiness_timeout: float = 30.0) -> ServerStatus:
        if spec.model_path.suffix.lower() != ".gguf" or not spec.model_path.is_file():
            raise ServerLifecycleError(f"model path must be an existing .gguf file: {spec.model_path}")
        self._validate_port_available(spec.port, spec.server_id)
        with self._lock:
            current = self._servers.get(spec.server_id)
            if current is not None and current.process.poll() is None:
                raise ServerLifecycleError(f"server {spec.server_id} is already running")
            command = self.build_command(spec)
            process = subprocess.Popen(
                command,
                cwd=self.repository_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            managed = _ManagedServer(spec=spec, process=process)
            managed.logs.append(ProcessLogRecord.create(source="server", stream="system", process=spec.server_id, message="launch: " + " ".join(command)))
            self._servers[spec.server_id] = managed
            managed.readers = [threading.Thread(target=self._capture_stream, args=(managed, process.stdout, "stdout"), daemon=True), threading.Thread(target=self._capture_stream, args=(managed, process.stderr, "stderr"), daemon=True)]
            for reader in managed.readers:
                reader.start()
        try:
            self._wait_for_health(spec.endpoint, process, readiness_timeout)
        except ServerLifecycleError:
            self.stop(spec.server_id)
            raise
        self._write_runtime_state(managed)
        return self.status(spec.server_id)

    def stop(self, server_id: str) -> ServerStatus:
        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        if managed.process.poll() is None:
            managed.process.terminate()
            try:
                managed.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                managed.process.kill()
                managed.process.wait(timeout=5)
        managed.logs.append(ProcessLogRecord.create(source="server", stream="system", process=server_id, message=f"process exited with code {managed.process.returncode}" , severity="error" if managed.process.returncode else "info"))
        self._clear_runtime_state(managed.process.pid)
        return self.status(server_id)

    def stop_all(self) -> None:
        """Stop every server owned by this manager instance."""

        for server_id in tuple(self._servers):
            managed = self._servers[server_id]
            if managed.process.poll() is None:
                self.stop(server_id)

    def shutdown(self) -> None:
        """Release local LLM processes during a normal GUI shutdown."""

        self.stop_all()

    def discover_project_server_pids(self, *, proc_root: Path = Path("/proc")) -> tuple[int, ...]:
        """Find llama-server processes whose executable and model belong to this repo."""

        if not proc_root.is_dir():
            return ()
        managed_pids = {
            managed.process.pid
            for managed in self._servers.values()
            if managed.process.poll() is None
        }
        discovered: list[int] = []
        for process_dir in proc_root.iterdir():
            if not process_dir.name.isdigit():
                continue
            pid = int(process_dir.name)
            if pid == os.getpid() or pid in managed_pids:
                continue
            try:
                command = tuple(
                    part.decode("utf-8", errors="surrogateescape")
                    for part in (process_dir / "cmdline").read_bytes().split(b"\0")
                    if part
                )
            except (OSError, PermissionError):
                continue
            if self._is_project_llama_server_command(command):
                discovered.append(pid)
        return tuple(sorted(discovered))

    def reclaim_project_servers(self, *, timeout: float = 5.0) -> tuple[int, ...]:
        """Terminate orphaned llama-server processes launched from this repo."""

        pids = self.discover_project_server_pids()
        for pid in pids:
            self._terminate_project_pid(pid, timeout=timeout)
        if pids:
            self._clear_runtime_state()
        return pids

    def restart(self, spec: ServerSpec, *, readiness_timeout: float = 30.0) -> ServerStatus:
        if spec.server_id in self._servers:
            self.stop(spec.server_id)
        return self.start(spec, readiness_timeout=readiness_timeout)

    def assign_roles(self, server_id: str, roles: tuple[str, ...]) -> ServerStatus:
        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        invalid = sorted(set(roles) - set(SEMANTIC_ROLES))
        if invalid:
            raise ValueError(f"unknown LLM roles: {', '.join(invalid)}")
        managed.spec = ServerSpec(**{**managed.spec.__dict__, "roles": tuple(dict.fromkeys(roles))})
        return self.status(server_id)

    def status(self, server_id: str) -> ServerStatus:
        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        process_state = "running" if managed.process.poll() is None else f"exited:{managed.process.returncode}"
        return ServerStatus(
            server_id=server_id,
            state=process_state,
            endpoint=managed.spec.endpoint,
            model_id=managed.spec.model_id,
            roles=managed.spec.roles,
            command=tuple(self.build_command(managed.spec)),
            pid=managed.process.pid,
            output=tuple(record.display() for record in managed.logs.snapshot()),
            logs=managed.logs.snapshot(),
            error=None if process_state == "running" else "server process exited",
        )

    def statuses(self) -> list[ServerStatus]:
        return [self.status(server_id) for server_id in sorted(self._servers)]

    def clear_logs(self, server_id: str) -> None:
        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        managed.logs.clear()

    def _capture_stream(self, managed: _ManagedServer, stream, name: str) -> None:
        if stream is None:
            return
        for line in stream:
            managed.logs.append(ProcessLogRecord.create(source="server", stream=name, process=managed.spec.server_id, message=line.rstrip("\r\n")))

    def _is_project_llama_server_command(self, command: tuple[str, ...]) -> bool:
        if not command:
            return False
        executable = Path(command[0]).expanduser()
        if executable.name != "llama-server" or not executable.is_absolute():
            return False
        try:
            executable.resolve().relative_to(self.repository_root)
        except (OSError, ValueError):
            return False
        try:
            model_index = command.index("--model") + 1
            model_path = Path(command[model_index]).expanduser()
        except (ValueError, IndexError):
            return False
        if not model_path.is_absolute():
            return False
        normalized_model_path = Path(os.path.abspath(model_path))
        try:
            normalized_model_path.relative_to(self.repository_root)
        except ValueError:
            return False
        return True

    def _terminate_project_pid(self, pid: int, *, timeout: float) -> None:
        if not self._pid_is_project_server(pid):
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._pid_is_project_server(pid):
                return
            time.sleep(0.1)
        if self._pid_is_project_server(pid):
            os.kill(pid, signal.SIGKILL)

    def _pid_is_project_server(self, pid: int) -> bool:
        try:
            command = tuple(
                part.decode("utf-8", errors="surrogateescape")
                for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                if part
            )
        except (OSError, PermissionError):
            return False
        return self._is_project_llama_server_command(command)

    def _write_runtime_state(self, managed: _ManagedServer) -> None:
        payload = {
            "version": 1,
            "pid": managed.process.pid,
            "server_id": managed.spec.server_id,
            "endpoint": managed.spec.endpoint,
            "model_id": managed.spec.model_id,
            "model_path": str(managed.spec.model_path.resolve()),
            "server_path": str(Path(managed.spec.server_path).resolve()),
            "roles": list(managed.spec.roles),
        }
        path = self.runtime_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _clear_runtime_state(self, pid: int | None = None) -> None:
        path = self.runtime_state_path
        if not path.exists():
            return
        if pid is not None:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if payload.get("pid") != pid:
                return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _validate_port_available(port: int, server_id: str) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("server port must be between 1 and 65535")
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise ServerLifecycleError(f"port {port} for server {server_id} is already occupied") from exc

    @staticmethod
    def _wait_for_health(endpoint: str, process: subprocess.Popen[str], timeout: float) -> None:
        health_url = f"{endpoint.rsplit('/v1', 1)[0]}/health"
        deadline = time.monotonic() + timeout
        last_error = "health endpoint did not respond"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ServerLifecycleError(f"server exited during startup with code {process.returncode}")
            try:
                with urllib.request.urlopen(health_url, timeout=1) as response:
                    if 200 <= response.status < 300:
                        return
                    last_error = f"health endpoint returned HTTP {response.status}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = str(exc) or type(exc).__name__
            time.sleep(0.25)
        raise ServerLifecycleError(f"server readiness timed out at {health_url}: {last_error}")


def canonical_local_model_id(path: Path) -> str | None:
    """Return one stable UI ID for a supported local model, or reject it."""

    name = path.name.lower().replace(".", "-")
    parent = path.parent.name.lower().replace(".", "-")
    value = f"{parent}-{name}"
    if "qwen3-5" in value or "qwen35" in value:
        return "qwen3.5"
    if "qwen3" in value:
        return "qwen3"
    if "llama-3-1" in value or "llama3-1" in value:
        return "llama3.1"
    return None


def _model_path_priority(path: Path) -> tuple[int, int, str]:
    """Prefer organized model files and then the shortest duplicate path."""

    return (0 if path.name == "model.gguf" else 1, len(str(path)), str(path).lower())
