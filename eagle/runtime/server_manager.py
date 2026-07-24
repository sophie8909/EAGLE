"""Local LLM server lifecycle owned by the EAGLE runtime.

The server manager owns model discovery, command construction, process
identity, readiness, output capture, and role association. It does not own GUI
state or evolutionary configuration. Remote endpoints are represented as
external server records and are tested, not launched, by this process.
"""

from __future__ import annotations

import os
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


SEMANTIC_ROLES = ("reflector", "rewriter", "generator")


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
    error: str | None = None


@dataclass
class _ManagedServer:
    spec: ServerSpec
    process: subprocess.Popen[str]
    output: list[str] = field(default_factory=list)
    reader: threading.Thread | None = None


class LLMServerManager:
    """Manage the actual local llama-server processes used by GUI roles."""

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self._servers: dict[str, _ManagedServer] = {}
        self._lock = threading.Lock()

    def discover_models(self) -> list[Path]:
        roots = (self.repository_root / "experiment_env" / "model", self.repository_root / "models")
        models = {path.resolve() for root in roots if root.exists() for path in root.rglob("*.gguf") if path.is_file()}
        return sorted(models, key=lambda path: str(path).lower())

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
        raise ServerLifecycleError("llama-server was not found; select an executable or set LLAMA_SERVER_BIN.")

    @staticmethod
    def build_command(spec: ServerSpec) -> list[str]:
        if not 1 <= spec.port <= 65535:
            raise ValueError("server port must be between 1 and 65535")
        if spec.context_size < 1:
            raise ValueError("server context size must be positive")
        return [
            str(spec.server_path),
            "--model", str(spec.model_path),
            "--alias", spec.model_id,
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
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            managed = _ManagedServer(spec=spec, process=process)
            self._servers[spec.server_id] = managed
            managed.reader = threading.Thread(target=self._capture_output, args=(managed,), daemon=True)
            managed.reader.start()
        try:
            self._wait_for_health(spec.endpoint, process, readiness_timeout)
        except ServerLifecycleError:
            self.stop(spec.server_id)
            raise
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
        return self.status(server_id)

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
            output=tuple(managed.output[-200:]),
            error=None if process_state == "running" else "server process exited",
        )

    def statuses(self) -> list[ServerStatus]:
        return [self.status(server_id) for server_id in sorted(self._servers)]

    def _capture_output(self, managed: _ManagedServer) -> None:
        assert managed.process.stdout is not None
        for line in managed.process.stdout:
            managed.output.append(line.rstrip())

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
