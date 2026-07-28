"""Lifecycle management for exactly one local llama-server process."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass

from .config import RuntimeConfig
from .endpoints import health_check


@dataclass(frozen=True)
class ProcessStatus:
    state: str
    detail: str
    pid: int | None = None


def build_server_command(runtime: RuntimeConfig) -> list[str]:
    llm = runtime.llm
    return [
        str(llm.server_binary), "--model", str(llm.model_path), "--host", llm.host,
        "--port", str(llm.port), "--ctx-size", str(llm.context_size),
        "--n-gpu-layers", str(llm.gpu_layers), "--parallel", str(llm.parallel),
        "--threads", str(llm.threads), "--batch-size", str(llm.batch_size),
    ]


class RuntimeManager:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime

    def start(self) -> ProcessStatus:
        command = build_server_command(self.runtime)
        pid = self.read_pid()
        if pid is not None:
            if process_alive(pid):
                if not command_matches(pid, self.runtime):
                    raise RuntimeError(f"llama-server.pid points to an unrelated process: {pid}")
                ok, detail = health_check(self.runtime)
                if ok:
                    return ProcessStatus("healthy", detail, pid)
                raise RuntimeError(f"Managed llama-server (PID {pid}) is unhealthy: {detail}")
            self.remove_pid()

        if port_occupied(self.runtime.llm.host, self.runtime.llm.port):
            raise RuntimeError(
                f"Port {self.runtime.llm.host}:{self.runtime.llm.port} is occupied by an unrelated process."
            )
        self.runtime.log_root.mkdir(parents=True, exist_ok=True)
        log_path = self.runtime.log_path
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=self.runtime.project_root,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
        self.write_pid(process.pid)
        deadline = time.monotonic() + self.runtime.llm.startup_timeout_seconds
        detail = "startup timeout"
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                self.remove_pid()
                tail = _log_tail(log_path)
                raise RuntimeError(
                    f"llama-server exited with code {return_code}.\n"
                    f"Final server log lines:\n{tail}"
                )
            ok, detail = health_check(self.runtime)
            if ok:
                return ProcessStatus("healthy", detail, process.pid)
            time.sleep(0.25)
        self.stop()
        raise RuntimeError(f"llama-server failed startup health checks: {detail}")

    def stop(self) -> None:
        pid = self.read_pid()
        if pid is None:
            return
        if not process_alive(pid):
            self.remove_pid()
            return
        if not command_matches(pid, self.runtime):
            raise RuntimeError(f"Refusing to stop unrelated process PID {pid}.")
        terminate_pid(pid, 5.0)
        self.remove_pid()

    def status(self) -> ProcessStatus:
        pid = self.read_pid()
        if pid is None or not process_alive(pid):
            self.remove_pid()
            return ProcessStatus("stopped", "no live managed PID")
        if not command_matches(pid, self.runtime):
            return ProcessStatus("unrelated", "PID command line does not match", pid)
        ok, detail = health_check(self.runtime)
        return ProcessStatus("healthy" if ok else "unhealthy", detail, pid)

    def check(self) -> ProcessStatus:
        if self.runtime.llm.gpu_layers != 0:
            try:
                probe = subprocess.run(
                    [str(self.runtime.llm.server_binary), "--list-devices"],
                    cwd=self.runtime.project_root,
                    capture_output=True,
                    text=True,
                    timeout=self.runtime.llm.health_timeout_seconds,
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

    def read_pid(self) -> int | None:
        try:
            return int(self.runtime.pid_path.read_text(encoding="ascii").strip())
        except (FileNotFoundError, OSError, ValueError):
            return None

    def write_pid(self, pid: int) -> None:
        self.runtime.pid_root.mkdir(parents=True, exist_ok=True)
        temporary = self.runtime.pid_path.with_name(self.runtime.pid_path.name + ".tmp")
        temporary.write_text(f"{pid}\n", encoding="ascii")
        temporary.replace(self.runtime.pid_path)

    def remove_pid(self) -> None:
        try:
            self.runtime.pid_path.unlink()
        except FileNotFoundError:
            pass


def read_command(pid: int) -> str:
    try:
        return " ".join(
            part.decode("utf-8", errors="replace")
            for part in open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            if part
        )
    except OSError:
        return ""


def command_matches(pid: int, runtime: RuntimeConfig) -> bool:
    command = read_command(pid)
    return all(
        value in command
        for value in (
            str(runtime.llm.server_binary), str(runtime.llm.model_path), str(runtime.llm.port),
        )
    )


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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


def terminate_pid(pid: int, timeout: float) -> None:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return
        time.sleep(0.1)
    if process_alive(pid):
        os.kill(pid, signal.SIGKILL)


def _log_tail(path, lines: int = 80) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return f"Unable to read {path}"
    return "\n".join(content[-lines:]) or f"{path} is empty"


def _has_gpu_device(output: str) -> bool:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return any(line.startswith("CUDA") or "CUDA0" in line or "NVIDIA" in line for line in lines)
