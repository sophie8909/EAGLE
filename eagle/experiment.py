"""One experiment lifecycle from resolved config through runtime cleanup."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from .config import ExperimentConfig
from .final_test import FINAL_TEST_SCHEMA_VERSION, main as final_test_main
from .resume import load_resume_config, resume_search, validate_resume_config
from .run_artifacts import load_manifest
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


def _load_experiment_run_index(config_dir: Path) -> dict[str, Path]:
    """Load the canonical config-to-run index for a folder resume."""

    index_path = config_dir / "experiment.yaml"
    if not index_path.is_file() or not _is_experiment_run_index(index_path):
        raise ValueError(
            "Folder resume requires a generated experiment.yaml run index: "
            f"{index_path}"
        )
    payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    entries: dict[str, Path] = {}
    for config_name, raw_run_dir in payload.items():
        run_dir = Path(raw_run_dir).expanduser()
        if not run_dir.is_absolute():
            raise ValueError(
                f"Experiment run index entry must be absolute: {config_name}={raw_run_dir}"
            )
        entries[str(config_name)] = run_dir.resolve()
    return entries


def _search_run_is_complete(run_dir: Path) -> bool:
    """Return whether the evolutionary portion of an indexed run is complete."""

    return str(load_manifest(run_dir).get("status") or "") == "complete"


def _final_test_is_complete(run_dir: Path) -> bool:
    """Recognize only a fully written canonical final-test summary."""

    path = run_dir / "final_test" / "final_test_summary.json"
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == FINAL_TEST_SCHEMA_VERSION
    )


def _batch_entry_is_complete(
    run_dir: Path,
    *,
    mock: bool,
    skip_final_test: bool,
) -> bool:
    if not _search_run_is_complete(run_dir):
        return False
    return mock or skip_final_test or _final_test_is_complete(run_dir)


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
    print(f"Reflection model: {config.model.name}")
    print(f"Generation model: {config.resolved_generation_model.name}")
    print(f"Endpoint: {config.model.base_url}")
    print(f"Survivor selection: {config.survivor_selection} lexicase")
    kind = "initial" if config.reflection_operator_mode.adaptive else "fixed"
    print(f"Reflection operator mode: {config.reflection_operator_mode.value}")
    print(f"Strategy {kind} probability: {config.strategy_reflection_probability:.2f}")
    print(f"Prompt {kind} probability: {config.prompt_reflection_probability:.2f}")
    print(f"Code {kind} probability: {config.code_reflection_probability:.2f}")
    print(f"AOS minimum probability: {config.aos_minimum_probability:.2f}")
    print(f"run_dir={config_path}")
    print(f"completed_generation={completed_generation}")


def _ensure_runtime_phase(
    manager: RuntimeManager,
    config: ExperimentConfig,
    phase: str,
) -> None:
    runtime = runtime_config_from_experiment(config, phase=phase)
    if manager.current_spec is None:
        print(f"Runtime: starting {phase} model {runtime.llm.base_url}")
    elif manager.current_spec == runtime.spec:
        print(f"Runtime: reusing {phase} model server")
    else:
        print(f"Runtime: switching to {phase} model {runtime.llm.base_url}")
    status = manager.ensure(runtime)
    if status.state != "healthy":
        raise RuntimeError(
            f"Configured {phase} llama.cpp runtime is not healthy: {status.detail}"
        )


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
            resume_dir = resume_dir.expanduser().resolve()
            resume_index = resume_dir / "experiment.yaml"
            is_indexed_config_folder = (
                resume_dir.is_dir()
                and resume_index.is_file()
                and _is_experiment_run_index(resume_index)
            )
            is_unindexed_config_folder = (
                resume_dir.is_dir()
                and not (resume_dir / "manifest.json").is_file()
                and not (resume_dir / "config.yaml").is_file()
            )
            if is_indexed_config_folder or is_unindexed_config_folder:
                return self._run_directory_resume(
                    resume_dir,
                    mock=mock,
                    skip_final_test=skip_final_test,
                )
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
                    manager = self.runtime_factory()
                    _ensure_runtime_phase(manager, config, "reflection")

                resume_kwargs = {}
                if not mock and config.uses_distinct_generation_model:
                    assert manager is not None
                    resume_kwargs["activate_model_phase"] = (
                        lambda phase: _ensure_runtime_phase(manager, config, phase)
                    )
                result = self.resume_runner(
                    None,
                    run_dir=resume_dir,
                    mock=mock,
                    **resume_kwargs,
                )
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
                print(f"Reflection model: {config.model.name}")
                print(f"Generation model: {config.resolved_generation_model.name}")
                print(f"Survivor selection: {config.survivor_selection} lexicase")
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

                if manager is None:
                    manager = self.runtime_factory()
                _ensure_runtime_phase(manager, config, "reflection")
                search_kwargs = {}
                if config.uses_distinct_generation_model:
                    search_kwargs["activate_model_phase"] = (
                        lambda phase, selected=config: _ensure_runtime_phase(
                            manager, selected, phase
                        )
                    )
                result = self.search_runner(
                    config,
                    config_path=resolved_path,
                    mock=mock,
                    on_run_created=record_run,
                    **search_kwargs,
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

    def _run_directory_resume(
        self,
        config_dir: Path,
        *,
        mock: bool,
        skip_final_test: bool,
    ) -> SearchResult:
        """Resume an interrupted folder batch, then run remaining configs."""

        discovered_paths = resolve_experiment_configs(config_dir)
        run_index_path = config_dir / "experiment.yaml"
        indexed_runs = _load_experiment_run_index(config_dir)
        pending_resumes = [
            path
            for path in discovered_paths
            if path.name in indexed_runs
            and not _batch_entry_is_complete(
                indexed_runs[path.name],
                mock=mock,
                skip_final_test=skip_final_test,
            )
        ]
        config_paths = pending_resumes + [
            path for path in discovered_paths if path not in pending_resumes
        ]
        _print_batch_header(config_dir, len(config_paths))

        manager: RuntimeManager | None = None
        last_result: SearchResult | None = None
        last_known_run: Path | None = None

        def ensure_runtime(config: ExperimentConfig, phase: str = "reflection") -> None:
            nonlocal manager
            if mock:
                return
            if manager is None:
                manager = self.runtime_factory()
            _ensure_runtime_phase(manager, config, phase)

        def phase_kwargs(config: ExperimentConfig) -> dict[str, object]:
            if mock or not config.uses_distinct_generation_model:
                return {}
            return {
                "activate_model_phase": lambda phase, selected=config: ensure_runtime(
                    selected, phase
                )
            }

        try:
            for index, resolved_path in enumerate(config_paths, start=1):
                print(f"\n[{index}/{len(config_paths)}] {resolved_path.name}")
                requested = ExperimentConfig.from_file(resolved_path)
                requested.validate()
                indexed_run = indexed_runs.get(resolved_path.name)

                if indexed_run is not None:
                    persisted = load_resume_config(indexed_run)
                    validate_resume_config(requested, persisted, mock=mock)
                    persisted.validate()
                    last_known_run = indexed_run
                    if _batch_entry_is_complete(
                        indexed_run,
                        mock=mock,
                        skip_final_test=skip_final_test,
                    ):
                        print(f"Status: complete; skipping {indexed_run}")
                        continue

                    manifest = load_manifest(indexed_run)
                    search_complete = str(manifest.get("status") or "") == "complete"
                    if not search_complete and manifest.get("latest_generation") is None:
                        print(
                            "Status: interrupted before generation 0; "
                            "creating a replacement run"
                        )
                        ensure_runtime(requested)
                        record_run = lambda run_dir, name=resolved_path.name: _record_experiment_run(
                            run_index_path,
                            name,
                            run_dir,
                        )
                        result = self.search_runner(
                            requested,
                            config_path=resolved_path,
                            mock=mock,
                            on_run_created=record_run,
                            **phase_kwargs(requested),
                        )
                        record_run(result.run_dir)
                    else:
                        print(f"Status: resuming {indexed_run}")
                        if not search_complete:
                            ensure_runtime(persisted)
                        result = self.resume_runner(
                            None,
                            run_dir=indexed_run,
                            mock=mock,
                            **phase_kwargs(persisted),
                        )
                else:
                    print("Status: not started; creating a new run")
                    ensure_runtime(requested)
                    record_run = lambda run_dir, name=resolved_path.name: _record_experiment_run(
                        run_index_path,
                        name,
                        run_dir,
                    )
                    result = self.search_runner(
                        requested,
                        config_path=resolved_path,
                        mock=mock,
                        on_run_created=record_run,
                        **phase_kwargs(requested),
                    )
                    record_run(result.run_dir)

                last_result = result
                last_known_run = result.run_dir
                if not mock and not skip_final_test:
                    status = self.final_test_runner(["--run-dir", str(result.run_dir)])
                    if status:
                        raise RuntimeError(f"Final test failed with exit code {status}.")

            if last_result is None:
                if last_known_run is None:
                    raise RuntimeError("No configs were executed or indexed.")
                manifest = load_manifest(last_known_run)
                last_result = SearchResult(
                    last_known_run,
                    [],
                    None,
                    int(manifest.get("latest_generation") or 0),
                    manifest.get("stop_reason"),
                )
        finally:
            if manager is not None:
                manager.stop_owned()

        print("Batch complete")
        if not mock and manager is not None:
            print("Runtime: stopped")
        return last_result
