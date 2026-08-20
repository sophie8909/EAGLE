"""Owned lifecycle management for one batch-local llama.cpp process."""
from __future__ import annotations

import json
import os
import shlex
import signal
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import RuntimeConfig, RuntimeSpec
from .endpoints import health_check


OWNERSHIP_SCHEMA_VERSION = "eagle-runtime-ownership-v1"


@dataclass(frozen=True)
class ProcessStatus:
    state: str
    detail: str
    pid: int | None = None
    action: str | None = None


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_time: int
    executable: str
    command: tuple[str, ...]


def build_server_command(runtime: RuntimeConfig) -> list[str]:
    llm = runtime.llm
    return [
        str(llm.server_binary), "--model", str(llm.model_path), "--host", llm.host,
        "--port", str(llm.port), "--ctx-size", str(llm.context_size),
        "--n-gpu-layers", str(llm.gpu_layers), "--parallel", str(llm.parallel),
        "--threads", str(llm.threads), "--batch-size", str(llm.batch_size),
        # The bundled llama.cpp build can abort while reusing a prompt-cache
        # sequence. EAGLE already owns request-level context, so server-side
        # prompt caching is unnecessary and unsafe for this runtime.
        "--no-cache-prompt",
    ]


class RuntimeManager:
    """Ensure at most one runtime owned by this Python batch."""

    def __init__(self, runtime: RuntimeConfig | None = None) -> None:
        self.runtime = runtime
        self._owner_token = uuid.uuid4().hex
        self._owned_identity: ProcessIdentity | None = None
        self._launcher_identity = process_identity(os.getpid())

    @property
    def current_spec(self) -> RuntimeSpec | None:
        return None if self.runtime is None or self._owned_identity is None else self.runtime.spec

    def ensure(self, runtime: RuntimeConfig) -> ProcessStatus:
        """Start, reuse, or switch to the requested launch-critical runtime."""

        if self._owned_identity is not None and self.runtime is not None:
            if self.runtime.spec == runtime.spec:
                self._verify_owned_process()
                ok, detail = health_check(runtime)
                if not ok:
                    raise RuntimeError(
                        f"Owned llama-server (PID {self._owned_identity.pid}) is unhealthy: {detail}"
                    )
                return ProcessStatus(
                    "healthy", detail, self._owned_identity.pid, action="reused"
                )
            self.stop_owned()
        self.runtime = runtime
        return self.start()

    def start(self) -> ProcessStatus:
        runtime = self._require_runtime()
        if self._owned_identity is not None:
            return self.ensure(runtime)

        self._reconcile_ownership_state()
        self._reconcile_legacy_pid_state()

        existing_pid = discover_listening_server_pid(runtime.llm.host, runtime.llm.port)
        if existing_pid is not None and process_alive(existing_pid):
            raise RuntimeError(_foreign_server_message(runtime.llm.host, runtime.llm.port, existing_pid))
        if port_occupied(runtime.llm.host, runtime.llm.port):
            raise RuntimeError(_foreign_server_message(runtime.llm.host, runtime.llm.port, None))

        command = build_server_command(runtime)
        runtime.log_root.mkdir(parents=True, exist_ok=True)
        log_path = runtime.log_path
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=runtime.project_root,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
        identity = _wait_for_process_identity(process.pid)
        if identity is None:
            return_code = process.poll()
            if return_code is None:
                terminate_pid(process.pid, 5.0)
            raise RuntimeError(
                "llama-server exited before ownership could be recorded"
                + ("." if return_code is None else f" with code {return_code}.")
            )
        self._owned_identity = identity
        try:
            self._write_ownership_state(identity)
        except Exception:
            try:
                terminate_pid(identity.pid, 5.0)
            finally:
                self._owned_identity = None
            raise

        deadline = time.monotonic() + runtime.llm.startup_timeout_seconds
        detail = "startup timeout"
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                self._remove_ownership_state(only_if_owned=True)
                self._owned_identity = None
                tail = _log_tail(log_path)
                raise RuntimeError(
                    f"llama-server exited with code {return_code}.\n"
                    f"Final server log lines:\n{tail}"
                )
            ok, detail = health_check(runtime)
            if ok:
                return ProcessStatus("healthy", detail, process.pid, action="started")
            time.sleep(0.25)
        self.stop_owned()
        raise RuntimeError(f"llama-server failed startup health checks: {detail}")

    def stop(self) -> None:
        """Stop a process verified by canonical or legacy EAGLE ownership state."""

        runtime = self._require_runtime()
        record = self._read_ownership_state()
        if record is not None:
            identity = _identity_from_record(record)
            if identity is None or not identity_matches_process(identity):
                self._remove_ownership_state()
            else:
                terminate_pid(identity.pid, 5.0)
                self._remove_ownership_state()
                if self._owned_identity == identity:
                    self._owned_identity = None
                return
        self._stop_verified_legacy_processes(runtime, allow_active=True)

    def stop_owned(self) -> None:
        """Stop only the process created and recorded by this manager instance."""

        identity = self._owned_identity
        if identity is None:
            return
        record = self._read_ownership_state()
        if (
            record is None
            or record.get("owner_token") != self._owner_token
            or _identity_from_record(record) != identity
        ):
            self._owned_identity = None
            raise RuntimeError(
                f"Refusing to stop PID {identity.pid}: EAGLE ownership identity no longer matches."
            )
        if not identity_matches_process(identity):
            self._remove_ownership_state(only_if_owned=True)
            self._owned_identity = None
            return
        terminate_pid(identity.pid, 5.0)
        self._remove_ownership_state(only_if_owned=True)
        self._owned_identity = None

    def status(self) -> ProcessStatus:
        runtime = self._require_runtime()
        record = self._read_ownership_state()
        if record is None:
            return ProcessStatus("stopped", "no EAGLE ownership state")
        identity = _identity_from_record(record)
        if identity is None or not identity_matches_process(identity):
            self._remove_ownership_state()
            return ProcessStatus("stopped", "removed stale EAGLE ownership state")
        ok, detail = health_check(runtime)
        return ProcessStatus("healthy" if ok else "unhealthy", detail, identity.pid)

    def check(self) -> ProcessStatus:
        runtime = self._require_runtime()
        if runtime.llm.gpu_layers != 0:
            try:
                probe = subprocess.run(
                    [str(runtime.llm.server_binary), "--list-devices"],
                    cwd=runtime.project_root,
                    capture_output=True,
                    text=True,
                    timeout=runtime.llm.health_timeout_seconds,
                    check=False,
                )
            except OSError as exc:
                raise RuntimeError(f"Unable to inspect llama.cpp devices: {exc}") from exc
            devices = (probe.stdout + probe.stderr).strip()
            if probe.returncode != 0 or not _has_gpu_device(devices):
                raise RuntimeError(
                    "CUDA support is unavailable for the configured GPU execution.\n"
                    f"{devices or 'llama-server --list-devices returned no devices.'}"
                )
        return ProcessStatus("healthy", "runtime configuration is valid")

    def _require_runtime(self) -> RuntimeConfig:
        if self.runtime is None:
            raise RuntimeError("RuntimeManager has no requested runtime.")
        return self.runtime

    def _verify_owned_process(self) -> None:
        identity = self._owned_identity
        record = self._read_ownership_state()
        if (
            identity is None
            or record is None
            or record.get("owner_token") != self._owner_token
            or _identity_from_record(record) != identity
            or not identity_matches_process(identity)
        ):
            self._owned_identity = None
            raise RuntimeError("The batch's owned llama-server identity is no longer valid.")

    def _read_ownership_state(self) -> dict[str, Any] | None:
        runtime = self._require_runtime()
        try:
            payload = json.loads(runtime.ownership_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            self._remove_ownership_state()
            return None
        if not isinstance(payload, dict) or payload.get("schema_version") != OWNERSHIP_SCHEMA_VERSION:
            self._remove_ownership_state()
            return None
        return payload

    def _write_ownership_state(self, identity: ProcessIdentity) -> None:
        runtime = self._require_runtime()
        launcher = self._launcher_identity or process_identity(os.getpid())
        runtime.ownership_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": OWNERSHIP_SCHEMA_VERSION,
            "owner_token": self._owner_token,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project_root": str(runtime.project_root),
            "pid": identity.pid,
            "process_start_time": identity.start_time,
            "executable": identity.executable,
            "command": list(identity.command),
            "launcher_pid": None if launcher is None else launcher.pid,
            "launcher_start_time": None if launcher is None else launcher.start_time,
            "runtime_spec": runtime.spec.to_mapping(),
        }
        temporary = runtime.ownership_path.with_name(runtime.ownership_path.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(runtime.ownership_path)

    def _remove_ownership_state(self, *, only_if_owned: bool = False) -> None:
        runtime = self._require_runtime()
        if only_if_owned:
            try:
                payload = json.loads(runtime.ownership_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                return
            if not isinstance(payload, dict) or payload.get("owner_token") != self._owner_token:
                return
        try:
            runtime.ownership_path.unlink()
        except FileNotFoundError:
            pass

    def _reconcile_ownership_state(self) -> None:
        runtime = self._require_runtime()
        record = self._read_ownership_state()
        if record is None:
            return
        identity = _identity_from_record(record)
        if identity is None or not _record_is_trusted(record, runtime) or not identity_matches_process(identity):
            self._remove_ownership_state()
            return
        if _launcher_is_alive(record):
            raise RuntimeError(_active_eagle_server_message(runtime, identity))
        terminate_pid(identity.pid, 5.0)
        self._remove_ownership_state()

    def _reconcile_legacy_pid_state(self) -> None:
        runtime = self._require_runtime()
        self._stop_verified_legacy_processes(runtime, allow_active=False)

    def _stop_verified_legacy_processes(
        self,
        runtime: RuntimeConfig,
        *,
        allow_active: bool,
    ) -> None:
        legacy_root = runtime.runtime_root / "pids"
        if not legacy_root.is_dir():
            return
        for pid_path in sorted(legacy_root.glob("*.pid")):
            try:
                pid = int(pid_path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                _remove_legacy_files(pid_path)
                continue
            if not process_alive(pid):
                _remove_legacy_files(pid_path)
                continue
            identity = process_identity(pid)
            if identity is None or not _legacy_identity_is_trusted(identity, runtime):
                _remove_legacy_files(pid_path)
                continue
            active = _legacy_launcher_is_alive(pid)
            if active and not allow_active:
                raise RuntimeError(_active_eagle_server_message(runtime, identity))
            terminate_pid(pid, 5.0)
            _remove_legacy_files(pid_path)


def read_command_args(pid: int) -> tuple[str, ...]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            parts = handle.read().split(b"\0")
        return tuple(
            part.decode("utf-8", errors="replace") for part in parts if part
        )
    except OSError:
        return ()


def read_command(pid: int) -> str:
    command = read_command_args(pid)
    return shlex.join(command) if command else ""


def read_executable(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return "unavailable"


def read_process_start_time(pid: int) -> int | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        remainder = value.rsplit(")", 1)[1].strip().split()
        return int(remainder[19])
    except (OSError, ValueError, IndexError):
        return None


def read_parent_pid(pid: int) -> int | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        remainder = value.rsplit(")", 1)[1].strip().split()
        return int(remainder[1])
    except (OSError, ValueError, IndexError):
        return None


def process_identity(pid: int) -> ProcessIdentity | None:
    start_time = read_process_start_time(pid)
    command = read_command_args(pid)
    executable = read_executable(pid)
    if start_time is None or not command or executable == "unavailable":
        return None
    return ProcessIdentity(pid, start_time, executable, command)


def identity_matches_process(identity: ProcessIdentity) -> bool:
    return process_alive(identity.pid) and process_identity(identity.pid) == identity


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        state = stat.rsplit(")", 1)[1].strip().split()[0]
        return state != "Z"
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, IndexError):
        return False


def port_occupied(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
    except OSError:
        return True
    finally:
        probe.close()
    return False


def discover_listening_server_pid(host: str, port: int) -> int | None:
    commands = (
        ["ss", "-ltnp", f"sport = :{port}"],
        ["lsof", "-nP", f"-iTCP@{host}:{port}", "-sTCP:LISTEN", "-t"],
    )
    for command in commands:
        try:
            probe = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError:
            continue
        if probe.returncode != 0:
            continue
        if command[0] == "lsof":
            for line in probe.stdout.splitlines():
                if line.strip().isdigit():
                    return int(line.strip())
            continue
        for line in probe.stdout.splitlines():
            if f":{port}" not in line or "pid=" not in line:
                continue
            suffix = line.split("pid=", 1)[1]
            digits = []
            for character in suffix:
                if character.isdigit():
                    digits.append(character)
                else:
                    break
            if digits:
                return int("".join(digits))
    return None


def terminate_pid(pid: int, timeout: float) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return
        time.sleep(0.1)
    if process_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _command_matches_runtime(identity: ProcessIdentity, runtime: RuntimeConfig) -> bool:
    return (
        identity.command == tuple(build_server_command(runtime))
        and _same_executable(identity.executable, runtime.llm.server_binary)
    )


def _legacy_identity_is_trusted(identity: ProcessIdentity, runtime: RuntimeConfig) -> bool:
    command = identity.command
    if not command or Path(identity.executable).name != "llama-server":
        return False
    try:
        Path(identity.executable).resolve().relative_to(runtime.project_root.resolve())
    except ValueError:
        return False
    values = _command_options(command)
    return values.get("--host") == runtime.llm.host and values.get("--port") == str(runtime.llm.port)


def _command_options(command: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for index, value in enumerate(command[:-1]):
        if value.startswith("--"):
            values[value] = command[index + 1]
    return values


def _same_executable(actual: str, expected: Path) -> bool:
    try:
        return Path(actual).resolve() == expected.resolve()
    except OSError:
        return False


def _identity_from_record(record: dict[str, Any]) -> ProcessIdentity | None:
    try:
        command = record["command"]
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            return None
        return ProcessIdentity(
            int(record["pid"]),
            int(record["process_start_time"]),
            str(record["executable"]),
            tuple(command),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _record_is_trusted(record: dict[str, Any], runtime: RuntimeConfig) -> bool:
    identity = _identity_from_record(record)
    return bool(
        identity is not None
        and record.get("project_root") == str(runtime.project_root)
        and Path(identity.executable).name == "llama-server"
    )


def _launcher_is_alive(record: dict[str, Any]) -> bool:
    try:
        pid = int(record["launcher_pid"])
        start_time = int(record["launcher_start_time"])
    except (KeyError, TypeError, ValueError):
        return False
    return process_alive(pid) and read_process_start_time(pid) == start_time


def _legacy_launcher_is_alive(server_pid: int) -> bool:
    """Recognize an actual EAGLE CLI ancestor, not an adopting init process."""

    ancestor = read_parent_pid(server_pid)
    visited: set[int] = set()
    for _ in range(8):
        if ancestor in {None, 0, 1} or ancestor in visited:
            return False
        visited.add(ancestor)
        identity = process_identity(ancestor)
        if identity is None:
            return False
        command = identity.command
        if any(
            command[index:index + 3] == ("-m", "eagle", operation)
            for operation in ("experiment", "runtime")
            for index in range(max(0, len(command) - 2))
        ):
            return True
        ancestor = read_parent_pid(ancestor)
    return False


def _wait_for_process_identity(pid: int) -> ProcessIdentity | None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        identity = process_identity(pid)
        if identity is not None:
            return identity
        if not process_alive(pid):
            return None
        time.sleep(0.01)
    return process_identity(pid)


def _remove_legacy_files(pid_path: Path) -> None:
    for path in (pid_path, pid_path.with_suffix(".model")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _active_eagle_server_message(runtime: RuntimeConfig, identity: ProcessIdentity) -> str:
    return (
        f"Port {runtime.llm.host}:{runtime.llm.port} is occupied by an active "
        f"EAGLE-owned llama-server (PID {identity.pid}).\n\n"
        f"Executable: {identity.executable}\n"
        f"Command: {shlex.join(identity.command)}\n\n"
        "Wait for the owning EAGLE command to finish or stop it through the EAGLE runtime command."
    )


def _foreign_server_message(host: str, port: int, pid: int | None) -> str:
    executable = "unavailable" if pid is None else read_executable(pid)
    command = "unavailable" if pid is None else read_command(pid) or "unavailable"
    return (
        f"Port {host}:{port} is occupied by a process that is not EAGLE-owned.\n\n"
        f"Process:\n  PID: {pid if pid is not None else 'unavailable'}\n"
        f"  Executable: {executable}\n  Command: {command}\n\n"
        "EAGLE will not stop this process. Stop it manually or choose another port."
    )


def _log_tail(path: Path, lines: int = 80) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return f"Unable to read {path}"
    return "\n".join(content[-lines:]) or f"{path} is empty"


def _has_gpu_device(output: str) -> bool:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return any(line.startswith("CUDA") or "CUDA0" in line or "NVIDIA" in line for line in lines)
