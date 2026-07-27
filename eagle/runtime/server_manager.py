"""Canonical local and remote LLM server lifecycle for EAGLE.

The manager owns resolution, command construction, process identity, durable
logs, readiness, status, and stop/restart semantics.  The GUI and EA consume
the resolved values exposed here; they must not independently guess ports or
URLs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .process_logs import ProcessLogBuffer, ProcessLogRecord


SEMANTIC_ROLES = ("reflector", "rewriter", "generator")
SUPPORTED_LOCAL_MODELS = ("qwen3", "qwen3.5", "llama3.1")
RUNTIME_STATE_PATH = Path("experiment_env/runtime/runtime_state.local.json")
SERVER_LOG_ROOT = Path("experiment_env/runtime/servers")
SERVER_STATES = ("STOPPED", "STARTING", "READY", "FAILED", "STOPPING")
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
SENSITIVE_ENV_MARKERS = ("KEY", "TOKEN", "PASSWORD", "SECRET", "CREDENTIAL")


class ServerLifecycleError(RuntimeError):
    """Expected server lifecycle failure with actionable context."""


@dataclass(frozen=True)
class ServerSpec:
    """One resolved launch-and-connection contract.

    The first fields retain the historical positional constructor used by
    callers and tests.  Local specifications require model/server paths;
    remote specifications require only client host, port, and model identity.
    """

    server_id: str
    model_path: Path | str | None
    server_path: Path | str | None
    model_id: str
    host: str
    port: int
    context_size: int = 32768
    roles: tuple[str, ...] = ()
    location_type: str = "local"
    client_host: str | None = None
    gpu_layers: int | str | None = None
    gpu_required: bool = False
    device: str | None = None
    additional_args: tuple[str, ...] = ()
    environment_overrides: tuple[tuple[str, str], ...] = ()
    working_directory: Path | str | None = None
    backend: str | None = None
    fit_to_vram: bool = False

    @property
    def bind_host(self) -> str:
        return self.host

    @property
    def connection_host(self) -> str:
        if self.client_host:
            return self.client_host
        return "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host

    @property
    def endpoint(self) -> str:
        return f"http://{_url_host(self.connection_host)}:{self.port}/v1"

    @property
    def base_url(self) -> str:
        return self.endpoint

    @property
    def health_url(self) -> str:
        return f"http://{_url_host(self.connection_host)}:{self.port}/health"

    @property
    def models_url(self) -> str:
        return f"{self.endpoint}/models"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.endpoint}/chat/completions"

    @property
    def workdir(self) -> Path | None:
        return Path(self.working_directory) if self.working_directory is not None else None

    @property
    def env_overrides(self) -> dict[str, str]:
        return dict(self.environment_overrides)

    @property
    def expects_gpu(self) -> bool:
        return self.execution_backend == "cuda"

    @property
    def execution_backend(self) -> str:
        """Return the explicit backend, retaining legacy inference for old configs."""
        if self.location_type == "remote":
            return "remote"
        if self.backend is not None:
            return str(self.backend).strip().lower()
        if self.gpu_required:
            return "cuda"
        if self.gpu_layers is not None:
            return "cuda" if str(self.gpu_layers).strip().lower() not in {"", "0", "none", "off"} else "cpu"
        return "cpu"


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
    location_type: str = "local"
    executable: str | None = None
    model_path: str | None = None
    bind_host: str = ""
    client_host: str = ""
    port: int = 0
    base_url: str = ""
    api_endpoint: str = ""
    health_url: str = ""
    working_directory: str = ""
    environment_overrides: dict[str, str] = field(default_factory=dict)
    elapsed_startup_seconds: float | None = None
    last_health_check: str | None = None
    exit_code: int | None = None
    log_path: str | None = None
    gpu_expected: bool = False
    gpu_backend_available: bool | None = None
    cuda_evidence: bool = False
    backend: str = "cpu"
    detected_devices: tuple[str, ...] = ()
    executable_version: str | None = None
    offloaded_layers: int | None = None


@dataclass
class _ManagedServer:
    spec: ServerSpec
    process: subprocess.Popen[str] | None = None
    state: str = "STOPPED"
    logs: ProcessLogBuffer = field(default_factory=ProcessLogBuffer)
    readers: list[threading.Thread] = field(default_factory=list)
    started_monotonic: float | None = None
    last_health_check: str | None = None
    failure_reason: str | None = None
    exit_code: int | None = None
    log_path: Path | None = None
    gpu_backend_available: bool | None = None
    exit_recorded: bool = False
    log_lock: threading.Lock = field(default_factory=threading.Lock)


class LLMServerManager:
    """Manage the actual server records used by GUI semantic roles."""

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()
        self._servers: dict[str, _ManagedServer] = {}
        self._lock = threading.Lock()
        self._supported_options: dict[Path, frozenset[str]] = {}
        self._capabilities: dict[Path, dict[str, Any]] = {}

    @property
    def runtime_state_path(self) -> Path:
        return self.repository_root / RUNTIME_STATE_PATH

    def discover_models(self) -> list[Path]:
        roots = (
            self.repository_root / "experiment_env" / "model",
            self.repository_root / "models",
        )
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
        return [
            discovered[model_id]
            for model_id in SUPPORTED_LOCAL_MODELS
            if model_id in discovered
        ]

    def resolve_server_path(
        self, configured: Path | str | None = None, *, prefer_cuda: bool = False
    ) -> Path:
        if configured:
            expanded = os.path.expandvars(os.path.expanduser(str(configured).strip()))
            configured_path = Path(expanded)
            if configured_path.parent != Path(".") or configured_path.is_absolute():
                path = self._resolve_path(configured_path)
                return self._validate_executable(path)
            candidate = shutil.which(expanded)
            if candidate:
                return self._validate_executable(Path(candidate).resolve())
            local = self._resolve_path(configured_path)
            if local.is_file():
                return self._validate_executable(local)
            raise ServerLifecycleError(
                f"llama-server executable was not found on PATH or at {local}"
            )

        configured_env = os.environ.get("LLAMA_SERVER_BIN", "").strip()
        if configured_env:
            return self.resolve_server_path(configured_env)
        candidate = shutil.which("llama-server")
        if candidate:
            return self._validate_executable(Path(candidate).resolve())
        candidate_paths = (
            self.repository_root / "experiment_env/model/llama.cpp/llama.cpp/build-eagle-cuda-128/bin/llama-server",
            self.repository_root / "experiment_env/model/llama.cpp/llama.cpp/build-eagle-cuda/bin/llama-server",
            self.repository_root / "experiment_env/model/llama.cpp/llama.cpp/build-eagle/bin/llama-server",
            self.repository_root / "experiment_env/model/llama.cpp/llama.cpp/build/bin/llama-server",
            self.repository_root / "experiment_env/model/llama.cpp/build/bin/llama-server",
        )
        if not prefer_cuda:
            candidate_paths = candidate_paths[2:]
        for candidate_path in candidate_paths:
            if candidate_path.is_file():
                return self._validate_executable(candidate_path.resolve())
        registry = self.repository_root / "experiment_env/model/model_registry.local.json"
        if registry.is_file():
            try:
                configured_path = json.loads(registry.read_text(encoding="utf-8")).get(
                    "llama_server_binary"
                )
            except (OSError, json.JSONDecodeError):
                configured_path = None
            if configured_path:
                try:
                    return self.resolve_server_path(str(configured_path))
                except ServerLifecycleError:
                    pass
        raise ServerLifecycleError(
            "llama-server was not found; select an executable or set LLAMA_SERVER_BIN."
        )

    def resolve_spec(self, spec: ServerSpec) -> ServerSpec:
        """Resolve and validate every path/value before process creation."""

        server_id = spec.server_id.strip()
        if not server_id:
            raise ServerLifecycleError("server identifier must not be empty")
        invalid_roles = sorted(set(spec.roles) - set(SEMANTIC_ROLES))
        if invalid_roles:
            raise ServerLifecycleError(f"unknown LLM roles: {', '.join(invalid_roles)}")
        if spec.location_type not in {"local", "remote"}:
            raise ServerLifecycleError("server location_type must be 'local' or 'remote'")
        backend = spec.execution_backend
        if backend not in {"cpu", "cuda", "remote"}:
            raise ServerLifecycleError("server backend must be 'cpu', 'cuda', or 'remote'")
        if spec.location_type == "remote" and backend != "remote":
            backend = "remote"
        if not spec.model_id.strip():
            raise ServerLifecycleError("server model identity must not be empty")
        if not 1 <= int(spec.port) <= 65535:
            raise ServerLifecycleError("server port must be between 1 and 65535")
        if spec.context_size < 1:
            raise ServerLifecycleError("server context size must be positive")
        if not spec.connection_host.strip():
            raise ServerLifecycleError("server client host must not be empty")
        if spec.connection_host in {"0.0.0.0", "::"}:
            raise ServerLifecycleError(
                "client host cannot be a wildcard address; use 127.0.0.1 or a routable LAN address"
            )

        workdir = self._resolve_path(spec.workdir or self.repository_root)
        if not workdir.is_dir():
            raise ServerLifecycleError(f"server working directory does not exist: {workdir}")
        environment = tuple(
            (str(key), str(value)) for key, value in spec.environment_overrides
        )
        if spec.location_type == "remote":
            return replace(
                spec,
                server_id=server_id,
                model_id=spec.model_id.strip(),
                model_path=None,
                server_path=None,
                host=spec.host.strip(),
                client_host=spec.connection_host.strip(),
                roles=tuple(dict.fromkeys(spec.roles)),
                environment_overrides=environment,
                working_directory=workdir,
                backend="remote",
            )

        if not spec.bind_host.strip():
            raise ServerLifecycleError("local server bind host must not be empty")
        if spec.model_path is None:
            raise ServerLifecycleError("local server model path is required")
        model_path = self._resolve_path(spec.model_path)
        if model_path.suffix.lower() != ".gguf" or not model_path.is_file():
            raise ServerLifecycleError(
                f"model path must be an existing .gguf file: {model_path}"
            )
        if not os.access(model_path, os.R_OK):
            raise ServerLifecycleError(f"model file is not readable: {model_path}")
        server_path = self.resolve_server_path(
            spec.server_path, prefer_cuda=backend == "cuda"
        )
        gpu_layers = spec.gpu_layers
        fit_to_vram = bool(spec.fit_to_vram)
        if isinstance(gpu_layers, str):
            legacy_layers = gpu_layers.strip().lower()
            if legacy_layers in {"", "none", "off", "0"}:
                gpu_layers = None
            elif legacy_layers == "auto":
                gpu_layers = None
                fit_to_vram = True
            elif legacy_layers == "all":
                gpu_layers = None
            else:
                raise ServerLifecycleError(
                    "gpu_layers must be a positive integer; use fit_to_vram for automatic fitting"
                )
        if gpu_layers == 0:
            gpu_layers = None
        if gpu_layers is not None:
            if isinstance(gpu_layers, bool) or not isinstance(gpu_layers, int) or gpu_layers < 1:
                raise ServerLifecycleError("gpu_layers must be a positive integer")
        if backend == "cpu" and (spec.gpu_required or gpu_layers is not None or fit_to_vram):
            raise ServerLifecycleError("CPU backend cannot use GPU layer or VRAM-fit settings")
        resolved = replace(
            spec,
            server_id=server_id,
            model_path=model_path,
            server_path=server_path,
            model_id=spec.model_id.strip(),
            host=spec.bind_host.strip(),
            client_host=spec.connection_host.strip(),
            roles=tuple(dict.fromkeys(spec.roles)),
            environment_overrides=environment,
            working_directory=workdir,
            backend=backend,
            gpu_layers=gpu_layers,
            fit_to_vram=fit_to_vram,
        )
        capabilities = self.binary_capabilities(server_path)
        if resolved.execution_backend == "cuda" and not capabilities["cuda_backend_available"]:
            raise ServerLifecycleError(
                f"CUDA backend was selected, but {server_path} reports no usable GPU backend or CUDA device; "
                "select a CUDA-enabled binary and verify NVIDIA visibility"
            )
        self._validate_command_compatibility(resolved)
        return resolved

    @staticmethod
    def find_available_port(preferred: int = 8080, *, attempts: int = 100) -> int:
        """Legacy discovery helper; launch never silently substitutes this value."""

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
        if spec.location_type != "local":
            raise ValueError("remote server specifications do not have launch commands")
        if spec.server_path is None or spec.model_path is None:
            raise ValueError("local server executable and model paths must be resolved")
        if not 1 <= spec.port <= 65535:
            raise ValueError("server port must be between 1 and 65535")
        if spec.context_size < 1:
            raise ValueError("server context size must be positive")
        generation_threads = max(1, min(8, os.cpu_count() or 1))
        command = [
            str(spec.server_path),
            "--model",
            str(spec.model_path),
            "--alias",
            spec.model_id,
            "--reasoning",
            "off",
            "--parallel",
            "1",
            "--threads",
            str(generation_threads),
            "--threads-batch",
            str(generation_threads),
            "--ctx-size",
            str(spec.context_size),
        ]
        backend = spec.execution_backend
        if backend == "cuda":
            if spec.gpu_layers is not None:
                command.extend(("--gpu-layers", str(spec.gpu_layers)))
            else:
                command.extend(("--gpu-layers", "auto" if spec.fit_to_vram else "all"))
            if spec.fit_to_vram:
                command.extend(("--fit", "on"))
        if spec.device and backend == "cuda":
            command.extend(("--device", spec.device))
        command.extend(("--host", spec.bind_host, "--port", str(spec.port)))
        command.extend(spec.additional_args)
        return command

    def start(self, spec: ServerSpec, *, readiness_timeout: float = 30.0) -> ServerStatus:
        """Start a local process or validate a remote endpoint.

        This call waits for bounded readiness, while concurrent GUI status
        reads see STARTING immediately after registration.
        """

        try:
            resolved = self.resolve_spec(spec)
        except (OSError, ValueError, ServerLifecycleError) as exc:
            self._record_prelaunch_failure(spec, str(exc))
            raise ServerLifecycleError(str(exc)) from exc

        with self._lock:
            current = self._servers.get(resolved.server_id)
            if current is not None and current.state in {"STARTING", "READY", "STOPPING"}:
                raise ServerLifecycleError(
                    f"server {resolved.server_id} is already {current.state.lower()}"
                )
            managed = _ManagedServer(
                spec=resolved,
                state="STARTING",
                started_monotonic=time.monotonic(),
                log_path=self._server_log_path(resolved.server_id),
            )
            if resolved.location_type == "local":
                managed.gpu_backend_available = self.detect_gpu_backend(
                    Path(str(resolved.server_path))
                )
            self._servers[resolved.server_id] = managed
            self._initialize_log(managed)

        if resolved.location_type == "remote":
            self._append_log(
                managed,
                "system",
                f"validating remote endpoint {resolved.endpoint} for roles "
                f"{','.join(resolved.roles) or 'none'}",
            )
            try:
                self._wait_for_readiness(managed, readiness_timeout)
            except ServerLifecycleError as exc:
                self._mark_failed(managed, str(exc))
                raise
            managed.state = "READY"
            self._append_log(managed, "system", "remote endpoint is ready")
            return self.status(resolved.server_id)

        try:
            self._validate_port_available(
                resolved.bind_host, resolved.port, resolved.server_id
            )
            command = self.build_command(resolved)
            environment = os.environ.copy()
            environment.update(resolved.env_overrides)
            self._append_log(
                managed, "system", "launch: " + shlex.join(command)
            )
            process = subprocess.Popen(
                command,
                cwd=resolved.workdir,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            managed.process = process
            self._append_log(managed, "system", f"created process PID {process.pid}")
            managed.readers = [
                threading.Thread(
                    target=self._capture_stream,
                    args=(managed, process.stdout, "stdout"),
                    name=f"eagle-server-{resolved.server_id}-stdout",
                    daemon=True,
                ),
                threading.Thread(
                    target=self._capture_stream,
                    args=(managed, process.stderr, "stderr"),
                    name=f"eagle-server-{resolved.server_id}-stderr",
                    daemon=True,
                ),
            ]
            for reader in managed.readers:
                reader.start()
            self._wait_for_readiness(managed, readiness_timeout)
        except (OSError, ValueError, ServerLifecycleError) as exc:
            self._mark_failed(managed, str(exc), terminate=True)
            raise ServerLifecycleError(str(exc)) from exc

        managed.state = "READY"
        managed.failure_reason = None
        self._append_log(managed, "system", f"server ready at {resolved.endpoint}")
        self._write_runtime_state(managed)
        return self.status(resolved.server_id)

    def stop(self, server_id: str) -> ServerStatus:
        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        if managed.state == "STOPPED":
            return self.status(server_id)
        managed.state = "STOPPING"
        self._append_log(managed, "system", "stopping server")
        self._terminate_managed(managed)
        managed.state = "STOPPED"
        managed.failure_reason = None
        self._clear_runtime_state(
            managed.process.pid if managed.process is not None else None
        )
        self._append_log(managed, "system", "server stopped and process reaped")
        return self.status(server_id)

    def stop_all(self) -> None:
        for server_id in tuple(self._servers):
            managed = self._servers[server_id]
            if managed.state not in {"STOPPED", "FAILED"} or (
                managed.process is not None and managed.process.poll() is None
            ):
                self.stop(server_id)

    def shutdown(self) -> None:
        self.stop_all()

    def discover_project_server_pids(
        self, *, proc_root: Path = Path("/proc")
    ) -> tuple[int, ...]:
        """Find llama-server processes whose executable and model belong to this repo."""

        if not proc_root.is_dir():
            return ()
        managed_pids = {
            managed.process.pid
            for managed in self._servers.values()
            if managed.process is not None and managed.process.poll() is None
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
        """Terminate orphaned repo-owned llama-server processes only."""

        pids = self.discover_project_server_pids()
        for pid in pids:
            self._terminate_project_pid(pid, timeout=timeout)
        if pids:
            self._clear_runtime_state()
        return pids

    def restart(
        self, spec: ServerSpec, *, readiness_timeout: float = 30.0
    ) -> ServerStatus:
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
        managed.spec = replace(managed.spec, roles=tuple(dict.fromkeys(roles)))
        return self.status(server_id)

    def status(self, server_id: str) -> ServerStatus:
        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        self._refresh_process_state(managed)
        process = managed.process
        live_pid = (
            process.pid
            if process is not None
            and process.poll() is None
            and managed.state in {"STARTING", "READY", "STOPPING"}
            else None
        )
        elapsed = (
            max(0.0, time.monotonic() - managed.started_monotonic)
            if managed.started_monotonic is not None
            and managed.state in {"STARTING", "READY"}
            else None
        )
        command: tuple[str, ...] = ()
        if managed.spec.location_type == "local":
            try:
                command = tuple(self.build_command(managed.spec))
            except ValueError:
                command = ()
        records = managed.logs.snapshot()
        executable = (
            str(managed.spec.server_path)
            if managed.spec.server_path is not None
            else None
        )
        model_path = (
            str(managed.spec.model_path)
            if managed.spec.model_path is not None
            else None
        )
        cuda_evidence = any(
            "cuda" in record.message.lower()
            or "ggml_cuda" in record.message.lower()
            or "offload" in record.message.lower()
            and "gpu" in record.message.lower()
            for record in records
        )
        offloaded_layers = _offloaded_layer_count(records)
        capabilities = (
            self.binary_capabilities(Path(str(managed.spec.server_path)))
            if managed.spec.server_path is not None
            else {"version": None, "devices": ()}
        )
        return ServerStatus(
            server_id=server_id,
            state=managed.state,
            endpoint=managed.spec.endpoint,
            model_id=managed.spec.model_id,
            roles=managed.spec.roles,
            command=command,
            pid=live_pid,
            output=tuple(record.display() for record in records),
            logs=records,
            error=managed.failure_reason,
            location_type=managed.spec.location_type,
            executable=executable,
            model_path=model_path,
            bind_host=managed.spec.bind_host,
            client_host=managed.spec.connection_host,
            port=managed.spec.port,
            base_url=managed.spec.base_url,
            api_endpoint=managed.spec.chat_completions_url,
            health_url=managed.spec.health_url,
            working_directory=str(managed.spec.workdir or ""),
            environment_overrides=_redacted_environment(managed.spec.env_overrides),
            elapsed_startup_seconds=elapsed,
            last_health_check=managed.last_health_check,
            exit_code=managed.exit_code,
            log_path=str(managed.log_path) if managed.log_path else None,
            gpu_expected=managed.spec.expects_gpu,
            gpu_backend_available=managed.gpu_backend_available,
            cuda_evidence=cuda_evidence,
            backend=managed.spec.execution_backend,
            detected_devices=tuple(capabilities.get("devices", ())),
            executable_version=capabilities.get("version"),
            offloaded_layers=offloaded_layers,
        )

    def statuses(self) -> list[ServerStatus]:
        return [self.status(server_id) for server_id in sorted(self._servers)]

    def server_spec(self, server_id: str) -> ServerSpec:
        """Return the exact resolved specification owned by this manager."""

        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        return managed.spec

    def clear_logs(self, server_id: str) -> None:
        managed = self._servers.get(server_id)
        if managed is None:
            raise ServerLifecycleError(f"unknown managed server: {server_id}")
        managed.logs.clear()

    def detect_gpu_backend(self, executable: Path) -> bool:
        return bool(self.binary_capabilities(executable)["cuda_backend_available"])

    def binary_capabilities(self, executable: Path) -> dict[str, Any]:
        """Inspect version and device capabilities without assuming GPU CLI flags work."""
        executable = executable.resolve()
        cached = self._capabilities.get(executable)
        if cached is not None:
            return cached
        version = None
        devices: tuple[str, ...] = ()
        try:
            version_result = subprocess.run(
                [str(executable), "--version"],
                cwd=self.repository_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            version_text = version_result.stdout + "\n" + version_result.stderr
            version = next((line.strip() for line in version_text.splitlines() if line.strip()), None)
            result = subprocess.run(
                [str(executable), "--list-devices"],
                cwd=self.repository_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            devices = tuple(_parse_device_lines(result.stdout + "\n" + result.stderr))
        except (OSError, subprocess.SubprocessError):
            pass
        capabilities = {
            "version": version,
            "devices": devices,
            "cuda_backend_available": bool(devices),
        }
        self._capabilities[executable] = capabilities
        return capabilities

    def diagnose_spec(self, spec: ServerSpec, *, timeout: float = 2.0) -> dict[str, Any]:
        """Return a credential-free, non-mutating diagnostic report."""

        report: dict[str, Any] = {
            "server_id": spec.server_id,
            "location_type": spec.location_type,
            "roles": list(spec.roles),
            "configuration_valid": False,
            "executable_valid": None,
            "model_valid": None,
            "process_state": None,
            "port_state": "unknown",
            "endpoint_state": "unknown",
            "gpu_expected": spec.expects_gpu,
            "gpu_backend_available": None,
            "backend": spec.execution_backend,
            "detected_devices": [],
            "executable_version": None,
            "cuda_startup_evidence": False,
            "error": None,
        }
        try:
            resolved = self.resolve_spec(spec)
            report.update(
                {
                    "configuration_valid": True,
                    "base_url": resolved.base_url,
                    "health_url": resolved.health_url,
                    "client_host": resolved.connection_host,
                    "bind_host": resolved.bind_host,
                    "port": resolved.port,
                    "working_directory": str(resolved.workdir or ""),
                    "environment_overrides": _redacted_environment(
                        resolved.env_overrides
                    ),
                }
            )
            if resolved.location_type == "local":
                report["executable_valid"] = True
                report["model_valid"] = True
                report["executable"] = str(resolved.server_path)
                report["model_path"] = str(resolved.model_path)
                report["command"] = self.build_command(resolved)
                capabilities = self.binary_capabilities(Path(str(resolved.server_path)))
                report["gpu_backend_available"] = capabilities["cuda_backend_available"]
                report["detected_devices"] = list(capabilities["devices"])
                report["executable_version"] = capabilities["version"]
                report["backend"] = resolved.execution_backend
            listening, detail = _port_listening(
                resolved.connection_host, resolved.port, timeout=timeout
            )
            report["port_state"] = "listening" if listening else detail
            endpoint_ok, endpoint_detail = self._probe_endpoint(resolved, timeout)
            report["endpoint_state"] = "ready" if endpoint_ok else endpoint_detail
            managed = self._servers.get(resolved.server_id)
            if managed is not None:
                status = self.status(resolved.server_id)
                report["process_state"] = status.state
                report["pid"] = status.pid
                report["exit_code"] = status.exit_code
                report["log_path"] = status.log_path
                report["cuda_startup_evidence"] = status.cuda_evidence
            else:
                runtime = self._read_runtime_state(resolved.server_id)
                if runtime is not None:
                    pid = runtime.get("pid")
                    alive = _pid_exists(pid)
                    report["process_state"] = "running" if alive else "stale"
                    report["pid"] = pid if alive else None
                    report["log_path"] = runtime.get("log_path")
                    log_path = runtime.get("log_path")
                    if isinstance(log_path, str) and Path(log_path).is_file():
                        recent = Path(log_path).read_text(
                            encoding="utf-8", errors="replace"
                        )[-100_000:]
                        report["cuda_startup_evidence"] = (
                            "cuda" in recent.lower()
                            or "ggml_cuda" in recent.lower()
                        )
        except (OSError, ValueError, ServerLifecycleError) as exc:
            report["error"] = str(exc)
        return report

    def _resolve_path(self, value: Path | str) -> Path:
        expanded = Path(os.path.expandvars(os.path.expanduser(str(value))))
        if not expanded.is_absolute():
            expanded = self.repository_root / expanded
        # Keep the user-facing symlink path. Model registries commonly point a
        # ``model.gguf`` symlink at a content-addressed blob with no extension;
        # resolving the link before validation incorrectly rejects that valid
        # model and obscures the selected registry entry.
        return Path(os.path.abspath(expanded))

    @staticmethod
    def _validate_executable(path: Path) -> Path:
        if not path.is_file():
            raise ServerLifecycleError(f"llama-server executable does not exist: {path}")
        if not os.access(path, os.X_OK):
            raise ServerLifecycleError(f"llama-server is not executable: {path}")
        return path

    def _validate_command_compatibility(self, spec: ServerSpec) -> None:
        executable = Path(str(spec.server_path)).resolve()
        options = self._supported_options.get(executable)
        if options is None:
            try:
                result = subprocess.run(
                    [str(executable), "--help"],
                    cwd=spec.workdir,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ServerLifecycleError(
                    f"could not inspect llama-server arguments for {executable}: {exc}"
                ) from exc
            help_text = result.stdout + "\n" + result.stderr
            options = frozenset(re.findall(r"(?<!\w)--[a-z0-9][a-z0-9-]*", help_text))
            self._supported_options[executable] = options
        required = {
            argument
            for argument in self.build_command(spec)
            if argument.startswith("--")
        }
        unsupported = sorted(required - options)
        if unsupported:
            raise ServerLifecycleError(
                f"llama-server {executable} does not support generated argument(s): "
                f"{', '.join(unsupported)}"
            )

    def _record_prelaunch_failure(self, spec: ServerSpec, reason: str) -> None:
        server_id = spec.server_id.strip() or "invalid-server"
        managed = _ManagedServer(
            spec=spec,
            state="FAILED",
            failure_reason=reason,
            log_path=self._server_log_path(server_id),
        )
        self._servers[server_id] = managed
        self._initialize_log(managed)
        self._append_log(managed, "system", f"pre-launch validation failed: {reason}", "error")

    def _server_log_path(self, server_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", server_id).strip("._") or "server"
        return self.repository_root / SERVER_LOG_ROOT / safe_id / "server.log"

    def _initialize_log(self, managed: _ManagedServer) -> None:
        if managed.log_path is None:
            return
        managed.log_path.parent.mkdir(parents=True, exist_ok=True)
        managed.log_path.touch(exist_ok=True)

    def _append_log(
        self,
        managed: _ManagedServer,
        stream: str,
        message: str,
        severity: str | None = None,
    ) -> None:
        clean_message = ANSI_ESCAPE.sub("", message).rstrip("\r\n")
        record = ProcessLogRecord.create(
            source="server",
            stream=stream,
            process=managed.spec.server_id,
            message=clean_message,
            severity=severity,
        )
        managed.logs.append(record)
        if managed.log_path is not None:
            with managed.log_lock:
                with managed.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        f"{record.timestamp} [{record.stream.upper()}] {record.message}\n"
                    )

    def _capture_stream(self, managed: _ManagedServer, stream, name: str) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                self._append_log(managed, name, line)
        except (OSError, ValueError) as exc:
            self._append_log(
                managed, "system", f"{name} log reader failed: {exc}", "error"
            )
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def _wait_for_readiness(
        self, managed: _ManagedServer, timeout: float
    ) -> None:
        deadline = time.monotonic() + max(0.01, timeout)
        last_error = "endpoint did not respond"
        while time.monotonic() < deadline:
            process = managed.process
            if process is not None and process.poll() is not None:
                managed.exit_code = process.returncode
                recent = _recent_relevant_lines(managed.logs.snapshot())
                suffix = f"; recent output: {recent}" if recent else ""
                raise ServerLifecycleError(
                    f"server process exited during startup with code "
                    f"{process.returncode}{suffix}"
                )
            listening, port_detail = _port_listening(
                managed.spec.connection_host, managed.spec.port, timeout=0.2
            )
            if not listening:
                last_error = port_detail
                managed.last_health_check = f"waiting for port: {port_detail}"
                time.sleep(0.1)
                continue
            ready, detail = self._probe_endpoint(managed.spec, timeout=1.0)
            managed.last_health_check = detail
            if ready:
                return
            last_error = detail
            time.sleep(0.2)
        raise ServerLifecycleError(
            f"readiness deadline reached for {managed.spec.endpoint}: {last_error}"
        )

    @staticmethod
    def _probe_endpoint(spec: ServerSpec, timeout: float) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(spec.health_url, timeout=timeout) as response:
                if not 200 <= response.status < 300:
                    return False, f"health returned HTTP {response.status}"
            with urllib.request.urlopen(spec.models_url, timeout=timeout) as response:
                if not 200 <= response.status < 300:
                    return False, f"models endpoint returned HTTP {response.status}"
                payload = json.loads(response.read().decode("utf-8"))
            model_ids = _available_model_ids(payload)
            if spec.model_id not in model_ids:
                return (
                    False,
                    f"API is reachable but model {spec.model_id!r} is not served; "
                    f"available={','.join(sorted(model_ids)) or 'none'}",
                )
            return True, f"health HTTP 2xx; model {spec.model_id!r} is served"
        except urllib.error.HTTPError as exc:
            return False, f"HTTP failure at {exc.url}: HTTP {exc.code}"
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ConnectionRefusedError):
                return False, f"connection refused at {spec.connection_host}:{spec.port}"
            if isinstance(reason, socket.gaierror):
                return False, f"unreachable host {spec.connection_host}: {reason}"
            return False, f"endpoint unavailable: {reason}"
        except (TimeoutError, socket.timeout):
            return False, f"endpoint timeout at {spec.connection_host}:{spec.port}"
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"incompatible API response: {exc}"

    def _mark_failed(
        self, managed: _ManagedServer, reason: str, *, terminate: bool = False
    ) -> None:
        if terminate:
            self._terminate_managed(managed)
        managed.state = "FAILED"
        managed.failure_reason = reason
        if managed.process is not None and managed.process.poll() is not None:
            managed.exit_code = managed.process.returncode
        self._append_log(managed, "system", f"startup failed: {reason}", "error")
        self._clear_runtime_state(
            managed.process.pid if managed.process is not None else None
        )

    def _terminate_managed(self, managed: _ManagedServer) -> None:
        process = managed.process
        if process is None or process.poll() is not None:
            if process is not None:
                managed.exit_code = process.returncode
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            process.wait(timeout=5)
        managed.exit_code = process.returncode
        for reader in managed.readers:
            reader.join(timeout=1)

    def _refresh_process_state(self, managed: _ManagedServer) -> None:
        process = managed.process
        if process is None:
            return
        returncode = process.poll()
        if returncode is None:
            return
        managed.exit_code = returncode
        if managed.state in {"STARTING", "READY"}:
            managed.state = "FAILED"
            managed.failure_reason = f"server process exited with code {returncode}"
        if not managed.exit_recorded:
            self._append_log(
                managed,
                "system",
                f"process exited with code {returncode}",
                "error" if returncode else "info",
            )
            managed.exit_recorded = True
        self._clear_runtime_state(process.pid)

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
        if managed.process is None:
            return
        payload = {
            "version": 2,
            "pid": managed.process.pid,
            "server_id": managed.spec.server_id,
            "state": managed.state,
            "base_url": managed.spec.base_url,
            "health_url": managed.spec.health_url,
            "model_id": managed.spec.model_id,
            "model_path": str(managed.spec.model_path),
            "server_path": str(managed.spec.server_path),
            "bind_host": managed.spec.bind_host,
            "client_host": managed.spec.connection_host,
            "port": managed.spec.port,
            "roles": list(managed.spec.roles),
            "log_path": str(managed.log_path) if managed.log_path else None,
        }
        path = self.runtime_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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

    def _read_runtime_state(self, server_id: str) -> dict[str, Any] | None:
        path = self.runtime_state_path
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("server_id") != server_id:
            return None
        return payload

    @staticmethod
    def _validate_port_available(
        bind_host: str, port: int, server_id: str
    ) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("server port must be between 1 and 65535")
        family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
        with socket.socket(family) as sock:
            try:
                sock.bind((bind_host, port))
            except OSError as exc:
                owner = _port_owner(port)
                detail = f"; {owner}" if owner else ""
                raise ServerLifecycleError(
                    f"port {port} for server {server_id} is already occupied{detail}"
                ) from exc

    @staticmethod
    def _wait_for_health(
        endpoint: str, process: subprocess.Popen[str], timeout: float
    ) -> None:
        """Compatibility wrapper retained for older focused callers."""

        parsed = urlparse(endpoint)
        model_id = ""
        health_url = f"{parsed.scheme}://{parsed.netloc}/health"
        deadline = time.monotonic() + timeout
        last_error = "health endpoint did not respond"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ServerLifecycleError(
                    f"server exited during startup with code {process.returncode}"
                )
            try:
                with urllib.request.urlopen(health_url, timeout=1) as response:
                    if 200 <= response.status < 300:
                        return
                    last_error = f"health endpoint returned HTTP {response.status}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = str(exc) or type(exc).__name__
            time.sleep(0.25)
        raise ServerLifecycleError(
            f"server readiness timed out at {health_url}: {last_error}; model={model_id}"
        )


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
    return (0 if path.name == "model.gguf" else 1, len(str(path)), str(path).lower())


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _redacted_environment(environment: dict[str, str]) -> dict[str, str]:
    return {
        key: (
            "<redacted>"
            if any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
            else value
        )
        for key, value in environment.items()
    }


def _available_model_ids(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    records: list[object] = []
    for key in ("data", "models"):
        value = payload.get(key)
        if isinstance(value, list):
            records.extend(value)
    values: set[str] = set()
    for item in records:
        if isinstance(item, str):
            values.add(item)
        elif isinstance(item, dict):
            for key in ("id", "name", "model"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    values.add(value)
            aliases = item.get("aliases")
            if isinstance(aliases, list):
                values.update(str(value) for value in aliases if value)
    return values


def _port_listening(host: str, port: int, *, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "listening"
    except ConnectionRefusedError:
        return False, f"connection refused at {host}:{port}"
    except socket.gaierror as exc:
        return False, f"unreachable host {host}: {exc}"
    except (TimeoutError, socket.timeout):
        return False, f"connection timeout at {host}:{port}"
    except OSError as exc:
        return False, f"port check failed at {host}:{port}: {exc}"


def _port_owner(port: int) -> str:
    lsof = shutil.which("lsof")
    if not lsof:
        return ""
    try:
        result = subprocess.run(
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpct"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    fields = [line for line in result.stdout.splitlines() if line]
    return "port owner " + " ".join(fields[:6]) if fields else ""


def _pid_exists(value: object) -> bool:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return False
    if pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _recent_relevant_lines(records: tuple[ProcessLogRecord, ...], limit: int = 8) -> str:
    lines = [
        ANSI_ESCAPE.sub("", record.message).strip()
        for record in records
        if record.message.strip()
    ]
    return " | ".join(lines[-limit:])


def _parse_device_lines(text: str) -> list[str]:
    """Parse llama.cpp's device listing, excluding its heading and CPU row."""
    devices: list[str] = []
    for raw in text.splitlines():
        line = ANSI_ESCAPE.sub("", raw).strip()
        if not line or line.lower().startswith("available devices"):
            continue
        if re.match(r"(?:CUDA|GPU)\d+\s*:", line, re.IGNORECASE):
            devices.append(line)
    return devices


def _offloaded_layer_count(records: tuple[ProcessLogRecord, ...]) -> int | None:
    patterns = (
        re.compile(r"offload(?:ed|ing)?\D+(\d+)\s+layers", re.IGNORECASE),
        re.compile(r"offloaded\s+(\d+)/(\d+)\s+layers", re.IGNORECASE),
    )
    for record in reversed(records):
        message = ANSI_ESCAPE.sub("", record.message)
        for pattern in patterns:
            match = pattern.search(message)
            if match:
                return int(match.group(1))
    return None


def _specs_from_topology(path: Path, repository_root: Path) -> list[ServerSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    servers = payload.get("servers")
    roles = payload.get("roles")
    if not isinstance(servers, dict) or not isinstance(roles, dict):
        raise ServerLifecycleError(
            "LLM role topology must contain object-valued 'servers' and 'roles'."
        )
    assigned: dict[str, list[str]] = {}
    for role, item in roles.items():
        if isinstance(item, dict) and item.get("server_id"):
            assigned.setdefault(str(item["server_id"]), []).append(str(role))
    specs: list[ServerSpec] = []
    for server_id, item in servers.items():
        if not isinstance(item, dict):
            continue
        parsed = urlparse(str(item.get("base_url", "")))
        location = str(item.get("location_type") or "remote")
        specs.append(
            ServerSpec(
                server_id=str(server_id),
                model_path=item.get("model_path"),
                server_path=item.get("executable"),
                model_id=str(item.get("model_id") or item.get("model") or ""),
                host=str(item.get("bind_host") or item.get("hostname") or parsed.hostname or ""),
                port=int(item.get("port") or parsed.port or 0),
                context_size=int(item.get("context_size") or 32768),
                roles=tuple(assigned.get(str(server_id), item.get("roles") or ())),
                location_type=location,
                client_host=str(item.get("client_host") or parsed.hostname or ""),
                gpu_layers=item.get("gpu_layers"),
                gpu_required=bool(item.get("gpu_required", False)),
                device=item.get("device"),
                backend=item.get("backend"),
                fit_to_vram=bool(item.get("fit_to_vram", False)),
                additional_args=tuple(item.get("additional_args") or ()),
                environment_overrides=tuple(
                    (str(key), str(value))
                    for key, value in (item.get("environment_overrides") or {}).items()
                ),
                working_directory=item.get("working_directory") or repository_root,
            )
        )
    return specs


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EAGLE LLM server diagnostics")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="report resolved configured-server status without opening the GUI",
    )
    parser.add_argument(
        "--topology",
        type=Path,
        default=Path("experiment_env/config/llm_topology.json"),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if not args.diagnose:
        parser.error("--diagnose is required")
    manager = LLMServerManager(args.repository_root)
    topology = args.topology
    if not topology.is_absolute():
        topology = manager.repository_root / topology
    try:
        specs = _specs_from_topology(topology, manager.repository_root)
        reports = [manager.diagnose_spec(spec) for spec in specs]
    except (OSError, ValueError, json.JSONDecodeError, ServerLifecycleError) as exc:
        print(json.dumps({"configuration_valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"topology": str(topology), "servers": reports}, indent=2))
    return 0 if reports and all(item["configuration_valid"] for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
