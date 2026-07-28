"""Typed loading and validation for the single-endpoint runtime contract."""
from __future__ import annotations

import ipaddress
import os
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
class LLMConfig:
    mode: str
    host: str | None
    client_host: str
    port: int
    model: Path | None
    server_binary: Path | None
    arguments: ServerArguments

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
    llm: LLMConfig
    watchdog: WatchdogConfig
    health_check: HealthCheckConfig
    analysis_output_directory_name: str
    latest_run_strategy: str

    @property
    def runtime_root(self) -> Path:
        return self.log_root.parent

    @property
    def resolved_endpoint_path(self) -> Path:
        return self.runtime_root / "resolved_endpoint.json"


def load_runtime_config(path: str | Path, *, create_directories: bool = True, validate_files: bool = True) -> RuntimeConfig:
    source = Path(path).expanduser().resolve()
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid runtime YAML {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Runtime config must contain a YAML mapping.")
    if payload.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise ValueError(f"Unsupported runtime schema version {payload.get('schema_version')!r}; expected {RUNTIME_SCHEMA_VERSION!r}.")
    obsolete = {"servers", "roles", "role_mapping", "endpoints", "reflector", "rewriter", "generator", "coder", "general"}
    found = sorted(obsolete.intersection(payload))
    if found:
        raise ValueError("Legacy multi-endpoint runtime fields are not supported: " + ", ".join(found) + ". Move one endpoint into llm.")
    env = _mapping(payload, "environment")
    project_root = _absolute_path(env, "project_root")
    run_root = _absolute_path(env, "run_root")
    log_root = _absolute_path(env, "log_root")
    pid_root = _absolute_path(env, "pid_root")
    if not project_root.is_dir():
        raise ValueError(f"Configured project root does not exist: {project_root}")
    if create_directories:
        for directory in (run_root, log_root, pid_root):
            directory.mkdir(parents=True, exist_ok=True)
    llm = _parse_llm(_mapping(payload, "llm"), validate_files=validate_files)
    analysis = _mapping(payload, "analysis")
    return RuntimeConfig(
        source, _required_text(env, "conda_env"), project_root, run_root, log_root, pid_root, llm,
        _parse_watchdog(_mapping(payload, "watchdog")), _parse_health(_mapping(payload, "health_check")),
        _required_text(analysis, "output_directory_name"), _required_text(analysis, "latest_run_strategy"),
    )


def read_conda_env(path: str | Path) -> str:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise ValueError(f"Unsupported or missing runtime schema in {path}.")
    return _required_text(_mapping(payload, "environment"), "conda_env")


def _parse_llm(value: dict[str, Any], *, validate_files: bool) -> LLMConfig:
    mode = _required_text(value, "mode")
    if mode not in {"local", "remote"}:
        raise ValueError("llm.mode must be local or remote.")
    client_host = _required_text(value, "client_host")
    _validate_host(client_host, "llm.client_host")
    port = _positive_int(value, "port")
    if port > 65535:
        raise ValueError("llm.port must be between 1 and 65535.")
    host = model = binary = None
    if mode == "local":
        host = _required_text(value, "host")
        _validate_host(host, "llm.host")
        model = _absolute_path(value, "model")
        binary = _absolute_path(value, "server_binary")
        if validate_files:
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise ValueError(f"llm.server_binary does not exist or is not executable: {binary}")
            if not model.is_file():
                raise ValueError(f"llm.model does not exist or is not a file: {model}")
    raw = value.get("arguments", {})
    if not isinstance(raw, dict):
        raise ValueError("llm.arguments must be a mapping.")
    args = ServerArguments(
        _positive_int(raw, "context_size", 32768), int(raw.get("gpu_layers", -1)),
        _positive_int(raw, "parallel", 1), _positive_int(raw, "threads", 8), _positive_int(raw, "batch_size", 512),
    )
    return LLMConfig(mode, host, client_host, port, model, binary, args)


def _parse_watchdog(value: dict[str, Any]) -> WatchdogConfig:
    return WatchdogConfig(bool(value.get("enabled", False)), _positive_number(value, "interval_seconds"), _positive_number(value, "startup_timeout_seconds"), _positive_number(value, "health_timeout_seconds"), _positive_number(value, "restart_delay_seconds"), _positive_int(value, "max_consecutive_restarts"), _positive_number(value, "restart_window_seconds"))


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

