"""Safe local llama-server and watchdog process management."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .config import RuntimeConfig, ServerConfig
from .endpoints import health_check, write_resolved_endpoints


@dataclass(frozen=True)
class ProcessStatus:
    server: ServerConfig
    state: str
    detail: str
    pid: int | None = None


def build_server_command(runtime: RuntimeConfig, server: ServerConfig) -> list[str]:
    if server.mode != "local" or server.model is None or server.host is None:
        raise ValueError(f"Cannot build a local command for {server.name}.")
    args = server.arguments
    command = [
        str(runtime.server_binary), "--host", server.host, "--port", str(server.port),
        "--model", str(server.model), "--ctx-size", str(args.context_size),
        "--n-gpu-layers", str(args.gpu_layers), "--parallel", str(args.parallel),
        "--threads", str(args.threads), "--batch-size", str(args.batch_size),
        "--cache-ram", str(args.prompt_cache_mib),
        "--cache-prompt" if args.reuse_prompt_cache else "--no-cache-prompt",
    ]
    if server.model_id:
        command.extend(["--alias", server.model_id])
    return command


class RuntimeManager:
    def __init__(self, runtime: RuntimeConfig):
        self.runtime = runtime

    def start(self, *, include_watchdog: bool = True) -> list[ProcessStatus]:
        statuses = []
        for server in self.runtime.enabled_servers():
            if server.mode == "remote":
                healthy, detail = health_check(server, self.runtime)
                if not healthy:
                    raise RuntimeError(f"Remote endpoint {server.name} is unavailable at {server.base_url}: {detail}")
                statuses.append(ProcessStatus(server, "healthy", detail))
            else:
                statuses.append(self.start_server(server))
        write_resolved_endpoints(self.runtime)
        if include_watchdog and self.runtime.watchdog.enabled:
            self.start_watchdog()
        return statuses

    def start_server(self, server: ServerConfig) -> ProcessStatus:
        command = build_server_command(self.runtime, server)
        pid = self.read_pid(server.name)
        if pid and process_alive(pid):
            if command_matches(pid, command):
                healthy, detail = health_check(server, self.runtime)
                if healthy:
                    return ProcessStatus(server, "healthy", detail, pid)
                raise RuntimeError(f"Managed server {server.name} (PID {pid}) is unhealthy: {detail}")
            raise RuntimeError(f"PID file for {server.name} points to an unrelated process: {pid}.")
        self.remove_pid(server.name)
        if port_occupied(server.client_host, server.port):
            raise RuntimeError(f"Port {server.client_host}:{server.port} for {server.name} is occupied by an unrelated process.")
        log_path = self.runtime.log_root / f"{server.name}.log"
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, cwd=self.runtime.project_root, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, text=True,
            )
        self.write_pid(server.name, process.pid)
        deadline = time.monotonic() + self.runtime.watchdog.startup_timeout_seconds
        detail = "startup timeout"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.remove_pid(server.name)
                raise RuntimeError(f"Server {server.name} exited with code {process.returncode}; see {log_path}.")
            healthy, detail = health_check(server, self.runtime, retries=1)
            if healthy:
                return ProcessStatus(server, "healthy", detail, process.pid)
            time.sleep(self.runtime.health_check.retry_delay_seconds)
        self.stop_server(server)
        raise RuntimeError(f"Server {server.name} failed startup health checks: {detail}")

    def stop(self) -> None:
        self.stop_watchdog()
        for server in self.runtime.local_servers():
            self.stop_server(server)
        try:
            self.runtime.resolved_endpoints_path.unlink()
        except FileNotFoundError:
            pass

    def stop_server(self, server: ServerConfig) -> None:
        pid = self.read_pid(server.name)
        if not pid or not process_alive(pid):
            self.remove_pid(server.name)
            return
        if not command_matches(pid, build_server_command(self.runtime, server)):
            raise RuntimeError(f"Refusing to stop unrelated process PID {pid} from {server.name}.pid.")
        terminate_pid(pid, timeout=5.0)
        self.remove_pid(server.name)

    def statuses(self) -> list[ProcessStatus]:
        result = []
        for server in self.runtime.enabled_servers():
            healthy, detail = health_check(server, self.runtime, retries=1)
            if server.mode == "remote":
                result.append(ProcessStatus(server, "healthy" if healthy else "unhealthy", detail))
                continue
            pid = self.read_pid(server.name)
            if not pid or not process_alive(pid):
                self.remove_pid(server.name)
                result.append(ProcessStatus(server, "stopped", "no live managed PID"))
            elif not command_matches(pid, build_server_command(self.runtime, server)):
                result.append(ProcessStatus(server, "unrelated", "PID command line does not match", pid))
            else:
                result.append(ProcessStatus(server, "healthy" if healthy else "unhealthy", detail, pid))
        return result

    def check(self) -> list[ProcessStatus]:
        return [
            ProcessStatus(server, "healthy" if healthy else "unhealthy", detail)
            for server in self.runtime.enabled_servers()
            for healthy, detail in [health_check(server, self.runtime)]
        ]

    def start_watchdog(self) -> int:
        pid = self.read_pid("watchdog")
        if pid and process_alive(pid):
            if "eagle.runtime.watchdog" in read_command(pid):
                return pid
            raise RuntimeError(f"watchdog.pid points to unrelated process PID {pid}.")
        self.remove_pid("watchdog")
        with (self.runtime.log_root / "watchdog.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "eagle.runtime.watchdog", "--config", str(self.runtime.source_path)],
                cwd=self.runtime.project_root, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, text=True,
            )
        self.write_pid("watchdog", process.pid)
        return process.pid

    def stop_watchdog(self) -> None:
        pid = self.read_pid("watchdog")
        if not pid or not process_alive(pid):
            self.remove_pid("watchdog")
            return
        if "eagle.runtime.watchdog" not in read_command(pid):
            raise RuntimeError(f"Refusing to stop unrelated watchdog PID {pid}.")
        terminate_pid(pid, timeout=5.0)
        self.remove_pid("watchdog")

    def pid_path(self, name: str) -> Path:
        return self.runtime.pid_root / f"{name}.pid"

    def read_pid(self, name: str) -> int | None:
        try:
            return int(self.pid_path(name).read_text(encoding="ascii").strip())
        except (FileNotFoundError, OSError, ValueError):
            return None

    def write_pid(self, name: str, pid: int) -> None:
        path = self.pid_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(f"{pid}\n", encoding="ascii")
        temporary.replace(path)

    def remove_pid(self, name: str) -> None:
        try:
            self.pid_path(name).unlink()
        except FileNotFoundError:
            pass


def read_command(pid: int) -> str:
    try:
        return "\0".join(part.decode("utf-8", errors="replace") for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part)
    except OSError:
        return ""


def command_matches(pid: int, expected: list[str]) -> bool:
    return read_command(pid).split("\0") == expected


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    except PermissionError:
        return True
    return pid > 0


def port_occupied(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except (ConnectionRefusedError, TimeoutError, socket.timeout, OSError):
        return False


def terminate_pid(pid: int, *, timeout: float) -> None:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return
        time.sleep(0.1)
    if process_alive(pid):
        os.kill(pid, signal.SIGKILL)
