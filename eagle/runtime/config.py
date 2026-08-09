"""Canonical local Qwen3.5 runtime configuration."""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

RUNTIME_SCHEMA_VERSION = "runtime-v1"
LEGACY_RUNTIME_ERROR = (
    "Unsupported legacy multi-model runtime configuration.\n"
    "EAGLE now supports only the Qwen3.5-9B model configured in configs/runtime.yaml.\n"
    "Remove server lists, role mappings, and per-operation endpoints."
)


@dataclass(frozen=True)
class ServerArguments:
    context_size: int
    gpu_layers: int
    parallel: int
    threads: int
    batch_size: int


@dataclass(frozen=True)
class LLMConfig:
    model_name: str
    model_path: Path
    server_binary: Path
    host: str
    port: int
    context_size: int
    gpu_layers: int
    parallel: int
    threads: int
    batch_size: int
    startup_timeout_seconds: float
    health_timeout_seconds: float

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    @property
    def arguments(self) -> ServerArguments:
        return ServerArguments(
            self.context_size,
            self.gpu_layers,
            self.parallel,
            self.threads,
            self.batch_size,
        )


@dataclass(frozen=True)
class RuntimeConfig:
    source_path: Path
    project_root: Path
    conda_env: str
    llm: LLMConfig
    log_path: Path
    pid_path: Path

    @property
    def run_root(self) -> Path:
        return self.project_root / "runs"

    @property
    def log_root(self) -> Path:
        return self.log_path.parent

    @property
    def pid_root(self) -> Path:
        return self.pid_path.parent

    @property
    def runtime_root(self) -> Path:
        return self.log_root.parent

    @property
    def analysis_output_directory_name(self) -> str:
        return "analysis"


def load_runtime_config(
    path: str | Path,
    *,
    create_directories: bool = True,
    validate_files: bool = True,
) -> RuntimeConfig:
    source = Path(path).expanduser().resolve()
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid runtime YAML {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Runtime config must contain a YAML mapping.")
    if payload.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported runtime schema version {payload.get('schema_version')!r}; "
            f"expected {RUNTIME_SCHEMA_VERSION!r}."
        )
    if _contains_legacy_runtime_key(payload):
        raise ValueError(LEGACY_RUNTIME_ERROR)

    project_root = source.parent.parent
    conda_env = _required_text(payload, "conda_env")
    llm = _parse_llm(_mapping(payload, "llm"), project_root, validate_files=validate_files)
    runtime = _mapping(payload, "runtime")
    log_path = _runtime_path(runtime, "log_path", project_root)
    pid_path = _runtime_path(runtime, "pid_path", project_root)
    result = RuntimeConfig(source, project_root, conda_env, llm, log_path, pid_path)
    if create_directories:
        for directory in (result.log_root, result.pid_root):
            directory.mkdir(parents=True, exist_ok=True)
    return result


def read_conda_env(path: str | Path) -> str:
    return load_runtime_config(path, create_directories=False, validate_files=False).conda_env


def _parse_llm(value: dict[str, Any], project_root: Path, *, validate_files: bool) -> LLMConfig:
    model_name = _required_text(value, "model_name")
    if model_name != "qwen3.5-9b":
        raise ValueError("llm.model_name must be exactly 'qwen3.5-9b'.")
    model_path = _path(value, "model_path", project_root)
    server_binary = _path(value, "server_binary", project_root)
    if validate_files:
        if not model_path.is_file():
            raise ValueError(f"llm.model_path does not exist or is not a file: {model_path}")
        if not server_binary.is_file() or not os.access(server_binary, os.X_OK):
            raise ValueError(
                "llm.server_binary does not exist or is not executable: "
                f"{server_binary}"
            )
    host = _required_text(value, "host")
    _validate_host(host, "llm.host")
    port = _integer(value, "port")
    if not 1 <= port <= 65535:
        raise ValueError("llm.port must be between 1 and 65535.")
    context_size = _positive_int(value, "context_size")
    gpu_layers = _integer(value, "gpu_layers")
    parallel = _positive_int(value, "parallel")
    threads = _positive_int(value, "threads")
    batch_size = _positive_int(value, "batch_size")
    startup = _positive_number(value, "startup_timeout_seconds")
    health = _positive_number(value, "health_timeout_seconds")
    return LLMConfig(
        model_name, model_path, server_binary, host, port, context_size, gpu_layers,
        parallel, threads, batch_size, startup, health,
    )


def _contains_legacy_runtime_key(payload: dict[str, Any]) -> bool:
    keys = {
        "mode", "client_host", "remote", "servers", "endpoints", "roles", "role_mapping",
        "reflector", "rewriter", "generator", "coder", "general", "watchdog",
        "resolved_endpoint", "fallback", "models", "health_check", "environment",
    }
    return bool(keys.intersection(payload)) or any(
        key in payload.get("llm", {}) if isinstance(payload.get("llm"), dict) else False
        for key in keys
    )


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


def _path(payload: dict[str, Any], key: str, project_root: Path) -> Path:
    value = Path(_required_text(payload, key)).expanduser()
    return value if value.is_absolute() else (project_root / value).resolve()


def _runtime_path(payload: dict[str, Any], key: str, project_root: Path) -> Path:
    return _path(payload, key, project_root)


def _integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"Runtime config field {key!r} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Runtime config field {key!r} must be an integer.") from exc


def _positive_int(payload: dict[str, Any], key: str) -> int:
    result = _integer(payload, key)
    if result <= 0:
        raise ValueError(f"Runtime config field {key!r} must be positive.")
    return result


def _positive_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    try:
        result = float(value)
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
