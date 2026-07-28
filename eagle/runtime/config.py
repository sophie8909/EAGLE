"""Typed loading and validation for the canonical runtime configuration."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

RUNTIME_SCHEMA_VERSION = "runtime-v1"


@dataclass(frozen=True)
class ServerArguments:
    context_size: int = 32768
    gpu_layers: int = -1
    parallel: int = 1
    threads: int = 8
    batch_size: int = 512


@dataclass(frozen=True)
class ServerConfig:
    name: str
    enabled: bool
    mode: str
    client_host: str
    port: int
    roles: tuple[str, ...]
    host: str | None = None
    model: Path | None = None
    arguments: ServerArguments = ServerArguments()
    model_id: str = ""

    @property
    def base_url(self) -> str:
        host = f"[{self.client_host}]" if ":" in self.client_host else self.client_host
        return f"http://{host}:{self.port}"


@dataclass(frozen=True)
class WatchdogConfig:
    enabled: bool
    interval_seconds: float
    startup_timeout_seconds: float
    health_timeout_seconds: float
    restart_delay_seconds: float
    max_consecutive_restarts: int
    restart_window_seconds: float


@dataclass(frozen=True)
class HealthCheckConfig:
    path: str
    fallback_path: str
    retries: int
    retry_delay_seconds: float


@dataclass(frozen=True)
class RuntimeConfig:
    source_path: Path
    conda_env: str
    project_root: Path
    run_root: Path
    log_root: Path
    pid_root: Path
    server_binary: Path
    servers: tuple[ServerConfig, ...]
    watchdog: WatchdogConfig
    health_check: HealthCheckConfig
    analysis_output_directory_name: str
    latest_run_strategy: str

    @property
    def runtime_root(self) -> Path:
        return self.log_root.parent

    @property
    def resolved_endpoints_path(self) -> Path:
        return self.runtime_root / "resolved_endpoints.json"

    def enabled_servers(self) -> tuple[ServerConfig, ...]:
        return tuple(server for server in self.servers if server.enabled)

    def local_servers(self) -> tuple[ServerConfig, ...]:
        return tuple(server for server in self.enabled_servers() if server.mode == "local")

    def roles(self) -> dict[str, ServerConfig]:
        return {role: server for server in self.enabled_servers() for role in server.roles}


def load_runtime_config(path: str | Path, *, create_directories: bool = True, validate_files: bool = True) -> RuntimeConfig:
    source = Path(path).expanduser().resolve()
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid runtime YAML {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Runtime config must contain a YAML mapping.")
    if payload.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported runtime schema version {payload.get('schema_version')!r}; "
            f"expected {RUNTIME_SCHEMA_VERSION!r}."
        )
    env = _mapping(payload, "environment")
    project_root = _absolute_path(env, "project_root")
    run_root = _absolute_path(env, "run_root")
    log_root = _absolute_path(env, "log_root")
    pid_root = _absolute_path(env, "pid_root")
    server_binary = _absolute_path(_mapping(payload, "llama_cpp"), "server_binary")
    if not project_root.is_dir():
        raise ValueError(f"Configured project root does not exist: {project_root}")
    if create_directories:
        for directory in (run_root, log_root, pid_root):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValueError(f"Runtime directory is not creatable: {directory}: {exc}") from exc
    servers = tuple(_parse_server(str(name), item) for name, item in _mapping(payload, "servers").items())
    ports: dict[int, str] = {}
    roles: dict[str, str] = {}
    for server in (item for item in servers if item.enabled):
        _validate_host(server.client_host, f"servers.{server.name}.client_host")
        if server.mode == "local":
            assert server.host is not None
            _validate_host(server.host, f"servers.{server.name}.host")
            if server.port in ports:
                raise ValueError(f"Duplicate local port {server.port}: {ports[server.port]} and {server.name}.")
            ports[server.port] = server.name
            if validate_files:
                if not server_binary.is_file():
                    raise ValueError(f"llama-server binary does not exist: {server_binary}")
                if server.model is None or not server.model.is_file():
                    raise ValueError(f"Model file for enabled local server {server.name!r} does not exist: {server.model}")
        for role in server.roles:
            if role in roles:
                raise ValueError(f"LLM role {role!r} is assigned to both {roles[role]!r} and {server.name!r}.")
            roles[role] = server.name
    analysis = _mapping(payload, "analysis")
    return RuntimeConfig(
        source, _required_text(env, "conda_env"), project_root, run_root, log_root,
        pid_root, server_binary, servers, _parse_watchdog(_mapping(payload, "watchdog")),
        _parse_health(_mapping(payload, "health_check")),
        _required_text(analysis, "output_directory_name"),
        _required_text(analysis, "latest_run_strategy"),
    )


def read_conda_env(path: str | Path) -> str:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise ValueError(f"Unsupported or missing runtime schema in {path}.")
    return _required_text(_mapping(payload, "environment"), "conda_env")


def _parse_server(name: str, value: object) -> ServerConfig:
    if not isinstance(value, dict):
        raise ValueError(f"servers.{name} must be a mapping.")
    mode = _required_text(value, "mode")
    if mode not in {"local", "remote"}:
        raise ValueError(f"servers.{name}.mode must be local or remote, not {mode!r}.")
    port = _positive_int(value, "port")
    if port > 65535:
        raise ValueError(f"servers.{name}.port must be between 1 and 65535.")
    raw_roles = value.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise ValueError(f"servers.{name}.roles must be a non-empty list.")
    roles = tuple(str(role).strip() for role in raw_roles)
    if any(not role for role in roles):
        raise ValueError(f"servers.{name}.roles contains an empty role.")
    args = ServerArguments()
    host = None
    model = None
    if mode == "local":
        host = _required_text(value, "host")
        model = _absolute_path(value, "model")
        raw = value.get("arguments", {})
        if not isinstance(raw, dict):
            raise ValueError(f"servers.{name}.arguments must be a mapping.")
        args = ServerArguments(
            _positive_int(raw, "context_size", 32768), int(raw.get("gpu_layers", -1)),
            _positive_int(raw, "parallel", 1), _positive_int(raw, "threads", 8),
            _positive_int(raw, "batch_size", 512),
        )
    return ServerConfig(
        name, bool(value.get("enabled", False)), mode, _required_text(value, "client_host"),
        port, roles, host, model, args, str(value.get("model_id", "")).strip(),
    )


def _parse_watchdog(value: dict[str, Any]) -> WatchdogConfig:
    return WatchdogConfig(
        bool(value.get("enabled", False)), _positive_number(value, "interval_seconds"),
        _positive_number(value, "startup_timeout_seconds"), _positive_number(value, "health_timeout_seconds"),
        _positive_number(value, "restart_delay_seconds"), _positive_int(value, "max_consecutive_restarts"),
        _positive_number(value, "restart_window_seconds"),
    )


def _parse_health(value: dict[str, Any]) -> HealthCheckConfig:
    path = _required_text(value, "path")
    fallback = _required_text(value, "fallback_path")
    if not path.startswith("/") or not fallback.startswith("/"):
        raise ValueError("Health-check paths must start with '/'.")
    return HealthCheckConfig(path, fallback, _positive_int(value, "retries"), _positive_number(value, "retry_delay_seconds"))


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Runtime config field {key!r} must be a mapping.")
    return value


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Runtime config field {key!r} is required.")
    return value


def _absolute_path(payload: dict[str, Any], key: str) -> Path:
    path = Path(_required_text(payload, key)).expanduser()
    if not path.is_absolute():
        raise ValueError(f"Runtime config field {key!r} must be an absolute path: {path}")
    return path


def _positive_int(payload: dict[str, Any], key: str, default: int | None = None) -> int:
    try:
        result = int(payload.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Runtime config field {key!r} must be an integer.") from exc
    if result <= 0:
        raise ValueError(f"Runtime config field {key!r} must be positive.")
    return result


def _positive_number(payload: dict[str, Any], key: str) -> float:
    try:
        result = float(payload.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Runtime config field {key!r} must be numeric.") from exc
    if result <= 0:
        raise ValueError(f"Runtime config field {key!r} must be positive.")
    return result


def _validate_host(host: str, field: str) -> None:
    if any(character.isspace() for character in host):
        raise ValueError(f"{field} is not a valid host: {host!r}")
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"{field} is not a valid host: {host!r}") from exc
