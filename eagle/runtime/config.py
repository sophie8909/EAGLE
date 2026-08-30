"""Runtime values derived exclusively from a resolved experiment config."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServerArguments:
    context_size: int
    gpu_layers: int
    parallel: int
    threads: int
    batch_size: int


@dataclass(frozen=True)
class LLMConfig:
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
            self.context_size, self.gpu_layers, self.parallel, self.threads,
            self.batch_size,
        )


@dataclass(frozen=True)
class RuntimeSpec:
    """Canonical compatibility identity for one llama.cpp runtime."""

    model_path: Path
    server_binary: Path
    host: str
    port: int
    context_size: int
    gpu_layers: int
    parallel: int
    threads: int
    batch_size: int

    def to_mapping(self) -> dict[str, object]:
        return {
            "model_path": str(self.model_path),
            "server_binary": str(self.server_binary),
            "host": self.host,
            "port": self.port,
            "context_size": self.context_size,
            "gpu_layers": self.gpu_layers,
            "parallel": self.parallel,
            "threads": self.threads,
            "batch_size": self.batch_size,
        }

    @property
    def command_fragments(self) -> tuple[str, ...]:
        return (
            str(self.server_binary),
            "--model",
            str(self.model_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.context_size),
            "--n-gpu-layers",
            str(self.gpu_layers),
            "--parallel",
            str(self.parallel),
            "--threads",
            str(self.threads),
            "--batch-size",
            str(self.batch_size),
        )


@dataclass(frozen=True)
class RuntimeConfig:
    source_path: Path
    project_root: Path
    conda_env: str
    llm: LLMConfig
    log_path: Path
    ownership_path: Path

    @property
    def run_root(self) -> Path:
        return self.project_root / "runs"

    @property
    def log_root(self) -> Path:
        return self.log_path.parent

    @property
    def ownership_root(self) -> Path:
        return self.ownership_path.parent

    @property
    def runtime_root(self) -> Path:
        return self.log_root.parent

    @property
    def analysis_output_directory_name(self) -> str:
        return "analysis"

    @property
    def spec(self) -> RuntimeSpec:
        return RuntimeSpec(
            model_path=self.llm.model_path,
            server_binary=self.llm.server_binary,
            host=self.llm.host,
            port=self.llm.port,
            context_size=self.llm.context_size,
            gpu_layers=self.llm.gpu_layers,
            parallel=self.llm.parallel,
            threads=self.llm.threads,
            batch_size=self.llm.batch_size,
        )


def runtime_config_from_experiment(config: Any) -> RuntimeConfig:
    """Adapt the one resolved experiment model to process-layer settings."""

    project_root = Path(__file__).resolve().parents[2]
    model = config.model
    config.validate_runtime_files()
    assert model.path is not None and model.llama_server is not None
    slug = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in model.name
    )
    endpoint_slug = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in f"{model.host}-{model.port}"
    )
    runtime_root = project_root / "runtime"
    return RuntimeConfig(
        source_path=Path("<resolved-experiment-config>"),
        project_root=project_root,
        conda_env="eagle",
        llm=LLMConfig(
            model.path, model.llama_server, model.host, model.port,
            model.context_size, model.gpu_layers, model.parallel, model.threads,
            model.batch_size, model.startup_timeout_seconds,
            model.health_timeout_seconds,
        ),
        log_path=runtime_root / "logs" / f"{slug}-{model.port}.log",
        ownership_path=runtime_root / "ownership" / f"{endpoint_slug}.json",
    )
