"""One experiment lifecycle from resolved config through runtime cleanup."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from .config import ExperimentConfig
from .final_test import main as final_test_main
from .resume import load_resume_config, resume_search, validate_resume_config
from .runtime.config import runtime_config_from_experiment
from .runtime.processes import RuntimeManager
from .search import SearchResult, run_search


def resolve_experiment_configs(path: str | Path) -> list[Path]:
    """Resolve a config directory or YAML path into a deterministic list."""

    selected = Path(path).expanduser().resolve()
    if selected.is_dir():
        config_paths = sorted(
            candidate for candidate in selected.iterdir()
            if candidate.is_file() and candidate.suffix.lower() in {".yaml", ".yml"}
            and not _is_experiment_run_index(candidate)
        )
        if not config_paths:
            raise ValueError(f"no YAML configs found in directory: {selected}")
        return config_paths

    if not selected.is_file():
        raise ValueError(f"Experiment config is missing: {selected}.")

    if selected.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError(f"Experiment config must be YAML: {selected}")

    return [selected]


def _is_experiment_run_index(path: Path) -> bool:
    """Return whether ``experiment.yaml`` is a generated config-to-run index."""

    if path.name != "experiment.yaml":
        return False
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    return (
        isinstance(payload, dict)
        and "schema_version" not in payload
        and all(
            isinstance(name, str)
            and Path(name).suffix.lower() in {".yaml", ".yml"}
            and isinstance(run_dir, str)
            for name, run_dir in payload.items()
        )
    )


def _run_index_path(selected: Path) -> Path | None:
    """Choose the folder-owned run index without overwriting a legacy config."""

    if not selected.is_dir():
        return None
    path = selected / "experiment.yaml"
    if path.exists() and not _is_experiment_run_index(path):
        return None
    return path


def _initialize_experiment_run_index(index_path: Path) -> None:
    """Start a fresh index for the selected directory batch."""

    temporary = index_path.with_name(index_path.name + ".tmp")
    temporary.write_text("{}\n", encoding="utf-8")
    temporary.replace(index_path)


def _record_experiment_run(index_path: Path, config_name: str, run_dir: Path) -> None:
    """Atomically update one config-to-run mapping in a batch index."""

    entries: dict[str, str] = {}
    if index_path.exists():
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Experiment run index must contain a YAML mapping: {index_path}")
        entries = {str(name): str(folder) for name, folder in payload.items()}
    entries[config_name] = str(run_dir.resolve())
    temporary = index_path.with_name(index_path.name + ".tmp")
    temporary.write_text(
        yaml.safe_dump(dict(sorted(entries.items())), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(index_path)


def resolve_experiment_config(path: str | Path) -> Path:
    """Resolve the folder-first interface to a single YAML document."""

    return resolve_experiment_configs(path)[0]


def _print_non_batch_output(
    *,
    config: ExperimentConfig,
    config_path: Path,
    completed_generation: int,
) -> None:
    print("EAGLE experiment")
    print(f"Experiment: {config.experiment_name}")
    print(f"Model: {config.model.name}")
    print(f"Endpoint: {config.model.base_url}")
    kind = "initial" if config.reflection_operator_mode.adaptive else "fixed"
    print(f"Reflection operator mode: {config.reflection_operator_mode.value}")
    print(f"Strategy {kind} probability: {config.strategy_reflection_probability:.2f}")
    print(f"Code {kind} probability: {config.code_reflection_probability:.2f}")
    print(f"AOS minimum probability: {config.aos_minimum_probability:.2f}")
    print(f"run_dir={config_path}")
    print(f"completed_generation={completed_generation}")


def _print_batch_header(selected: Path, total: int) -> None:
    print(f"Experiment batch: {selected}")
    print(f"Configs: {total}")


@dataclass
class ExperimentOrchestrator:
    """Small owner of runtime/search/final-test ordering."""

    runtime_factory: Callable[[], RuntimeManager] = RuntimeManager
    search_runner: Callable[..., SearchResult] = run_search
    resume_runner: Callable[..., SearchResult] = resume_search
    final_test_runner: Callable[[list[str]], int] = final_test_main

    def run(
        self,
        *,
        config_path: Path | None,
        resume_dir: Path | None = None,
        mock: bool = False,
        skip_final_test: bool = False,
    ) -> SearchResult:
        if resume_dir is not None:
            persisted = load_resume_config(resume_dir)
            if config_path is not None:
                requested = ExperimentConfig.from_file(resolve_experiment_config(config_path))
                validate_resume_config(requested, persisted, mock=mock)
            config = persisted
            config.validate()
            print("EAGLE experiment")
            _print_non_batch_output(
                config=config,
                config_path=config_path or resume_dir / "config.yaml",
                completed_generation=0,
            )
            manager: RuntimeManager | None = None
            try:
                if not mock:
                    runtime = runtime_config_from_experiment(config)
                    manager = self.runtime_factory()
                    print(f"Runtime: starting {runtime.llm.base_url}")
                    status = manager.ensure(runtime)
                    if status.state != "healthy":
                        raise RuntimeError(
                            f"Configured llama.cpp runtime is not healthy: {status.detail}"
                        )

                result = self.resume_runner(None, run_dir=resume_dir, mock=mock)
                if not mock and not skip_final_test:
                    status = self.final_test_runner(["--run-dir", str(result.run_dir)])
                    if status:
                        raise RuntimeError(f"Final test failed with exit code {status}.")
                return result
            finally:
                if manager is not None:
                    manager.stop_owned()

        if config_path is None:
            raise ValueError("A config path is required unless --resume is supplied.")
        config_paths = resolve_experiment_configs(config_path)
        run_index_path = _run_index_path(config_path.resolve())
        if run_index_path is not None:
            _initialize_experiment_run_index(run_index_path)
        _print_batch_header(config_path.resolve(), len(config_paths))

        manager: RuntimeManager | None = None
        last_result: SearchResult | None = None
        try:
            for index, resolved_path in enumerate(config_paths, start=1):
                print(f"\n[{index}/{len(config_paths)}] {resolved_path.name}")
                config = ExperimentConfig.from_file(resolved_path)
                print(f"Model: {config.model.name}")
                print(f"Reflection operator mode: {config.reflection_operator_mode.value}")
                config.validate()
                record_run = (
                    None
                    if run_index_path is None
                    else lambda run_dir, name=resolved_path.name: _record_experiment_run(
                        run_index_path, name, run_dir
                    )
                )
                if mock:
                    result = self.search_runner(
                        config,
                        config_path=resolved_path,
                        mock=mock,
                        on_run_created=record_run,
                    )
                    if record_run is not None:
                        record_run(result.run_dir)
                    last_result = result
                    continue

                runtime = runtime_config_from_experiment(config)
                if manager is None:
                    manager = self.runtime_factory()
                if manager.current_spec is None:
                    print(f"Runtime: starting {runtime.llm.base_url}")
                elif manager.current_spec == runtime.spec:
                    print("Runtime: reusing existing model server")
                else:
                    print("Runtime: switching model server")
                    print(f"Runtime: starting {runtime.llm.base_url}")
                status = manager.ensure(runtime)
                if status.state != "healthy":
                    raise RuntimeError(
                        f"Configured llama.cpp runtime is not healthy: {status.detail}"
                    )
                result = self.search_runner(
                    config,
                    config_path=resolved_path,
                    mock=mock,
                    on_run_created=record_run,
                )
                if record_run is not None:
                    record_run(result.run_dir)
                last_result = result
                if not skip_final_test:
                    status = self.final_test_runner(["--run-dir", str(result.run_dir)])
                    if status:
                        raise RuntimeError(f"Final test failed with exit code {status}.")
            if last_result is None:
                raise RuntimeError("No configs were executed.")
        finally:
            if manager is not None:
                manager.stop_owned()
        print("Batch complete")
        if not mock:
            print("Runtime: stopped")
        return last_result
