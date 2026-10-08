"""Resume the canonical EA from the latest surviving-population snapshot."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from eagle.artifacts import write_summary
from eagle.config import ExperimentConfig
from eagle.evaluation.opponents import preflight_evaluation_opponents
from eagle.run_artifacts import (
    finalize_run,
    RESUME_ARCHIVE_PATHS,
    load_error_memory,
    load_aos_state,
    load_resume_population,
    mark_run_started,
    mark_run_failed,
    mark_run_interrupted,
)
from eagle.evolution.generation import run_generation_step
from eagle.evolution.search import SearchResult
from eagle.strategy_diversity import (
    ensure_strategy_archive,
    update_strategy_archive,
)
from eagle.operators.selection import best_candidate, population_signature
from eagle.evolution.runtime import build_search_runtime, preflight_llm_endpoint
from eagle.self_play import (
    load_self_play_snapshot,
)


def resume_search(
    config: ExperimentConfig | None = None,
    *,
    config_path: Path | None = None,
    run_dir: Path,
    mock: bool = False,
    activate_model_phase=None,
) -> SearchResult:
    """Continue from the last atomically recorded generation."""

    persisted = load_resume_config(run_dir)
    if config is not None:
        validate_resume_config(config, persisted, mock=mock)
    config = persisted
    try:
        mark_run_started(run_dir)
        return _resume_search_impl(
            config,
            config_path=config_path,
            run_dir=run_dir,
            mock=mock,
            activate_model_phase=activate_model_phase,
        )
    except KeyboardInterrupt:
        mark_run_interrupted(run_dir)
        raise
    except Exception as exc:
        mark_run_failed(run_dir, exc)
        raise


def load_resume_config(run_dir: Path) -> ExperimentConfig:
    """Load the immutable experiment definition owned by a run."""

    run_config_path = run_dir / "config.yaml"
    if not run_config_path.is_file():
        raise ValueError(f"Resume run has no canonical config.yaml: {run_dir}")
    return ExperimentConfig.from_file(run_config_path)


def _resume_search_impl(
    config: ExperimentConfig,
    *,
    config_path: Path | None,
    run_dir: Path,
    mock: bool = False,
    activate_model_phase=None,
) -> SearchResult:
    config.validate()
    if config.evaluation_mode == "fixed_roster":
        preflight_evaluation_opponents(config, mock=mock)
    completed_generation, population = load_resume_population(run_dir)
    _restore_completed_generation(run_dir, completed_generation)
    ensure_strategy_archive(run_dir)
    # Backfill the archive from the surviving snapshot when resuming a run
    # created before strategy_archive.json existed.  Older candidates retain
    # the explicit ``unknown`` fallback and are not inferred from prompt text.
    update_strategy_archive(run_dir, population)
    if completed_generation >= config.generations:
        best = best_candidate(population)
        return SearchResult(run_dir, population, best, completed_generation)

    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    for directory in (candidates_dir, generated_agents_dir, classes_dir):
        directory.mkdir(parents=True, exist_ok=True)
    runtime = build_search_runtime(
        config,
        mock=mock,
        run_dir=run_dir,
        candidates_dir=candidates_dir,
        controller_state=load_aos_state(run_dir),
    )
    generation_backend = runtime.generation_backend
    shared_client = runtime.client
    generation_client = runtime.generation_client
    mutations = runtime.mutations
    rng = random.Random(config.random_seed)
    operator_controller = runtime.operator_controller
    population_state_signature = population_signature(
        population,
        selection_mode=config.algorithm,
    )
    snapshot_path = run_dir / "generations" / f"generation_{completed_generation:04d}.json"
    checkpoint = json.loads(snapshot_path.read_text(encoding="utf-8"))
    stagnation = int(checkpoint.get("stagnation_count", 0))
    error_memory = load_error_memory(run_dir)
    stop_reason = (
        f"stagnation_{config.stagnation_generations}_generations"
        if config.stagnation_generations > 0 and stagnation >= config.stagnation_generations
        else None
    )
    active_model_phase = "reflection"
    self_play_opponent_snapshot = (
        load_self_play_snapshot(
            run_dir,
            completed_generation=completed_generation,
            refresh_interval=config.self_play_refresh_interval,
        )
        if config.evaluation_mode == "self_play"
        else None
    )

    def activate_phase(phase: str) -> None:
        nonlocal active_model_phase
        if not config.uses_distinct_generation_model or phase == active_model_phase:
            return
        if mock:
            active_model_phase = phase
            return
        if activate_model_phase is None:
            raise RuntimeError(
                "A distinct generation_model requires the experiment orchestrator's "
                "model-phase activation callback."
            )
        activate_model_phase(phase)
        preflight_llm_endpoint(
            generation_client if phase == "generation" else shared_client
        )
        active_model_phase = phase

    for generation in range(completed_generation + 1, config.generations + 1):
        if stop_reason is not None:
            break
        step = run_generation_step(
            generation=generation,
            config=config,
            run_dir=run_dir,
            candidates_dir=candidates_dir,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            mock=mock,
            run_id=run_dir.name,
            rng=rng,
            population=population,
            population_state_signature=population_state_signature,
            stagnation_count=stagnation,
            error_memory=error_memory,
            self_play_opponent_snapshot=self_play_opponent_snapshot,
            generation_backend=generation_backend,
            shared_client=shared_client,
            generation_client=generation_client,
            mutations=mutations,
            operator_controller=operator_controller,
            activate_phase=activate_phase,
        )
        population = step.population
        self_play_opponent_snapshot = step.self_play_opponent_snapshot
        population_state_signature = step.population_state_signature
        stagnation = step.stagnation_count
        error_memory = step.error_memory
        completed_generation = generation
        if step.stop_reason is not None:
            stop_reason = step.stop_reason
            break
    best = best_candidate(population)
    write_summary(
        run_dir, config=config, final_population=population, best_candidate=best,
        mock=mock, completed_generation=completed_generation,
        stop_reason=stop_reason,
    )
    finalize_run(run_dir, population, stop_reason=stop_reason)
    return SearchResult(run_dir, population, best, completed_generation, stop_reason)


def validate_resume_config(
    config: ExperimentConfig,
    persisted: ExperimentConfig,
    *,
    mock: bool = False,
    allow_experiment_name_alias: bool = False,
) -> None:
    run_mapping = persisted.to_mapping(mock=False)
    requested_mapping = config.to_mapping(mock=mock)
    if allow_experiment_name_alias:
        # A folder resume is already bound by the exact config-filename-to-run
        # entry in experiment.yaml.  The human-readable experiment name is
        # metadata and may be corrected without changing the immutable run
        # definition used for continued execution.
        run_mapping.pop("experiment_name", None)
        requested_mapping.pop("experiment_name", None)
    mismatches = _mapping_differences(run_mapping, requested_mapping)
    if mismatches:
        raise ValueError("Resume config does not match the run: " + "; ".join(mismatches))


def _mapping_differences(run_value, requested_value, prefix: str = "") -> list[str]:
    if isinstance(run_value, dict) and isinstance(requested_value, dict):
        differences: list[str] = []
        for key in sorted(set(run_value) | set(requested_value)):
            path = f"{prefix}.{key}" if prefix else str(key)
            differences.extend(
                _mapping_differences(run_value.get(key), requested_value.get(key), path)
            )
        return differences
    if run_value == requested_value:
        return []
    return [f"{prefix}: run={run_value!r}, config={requested_value!r}"]


def _restore_completed_generation(run_dir: Path, generation: int) -> None:
    """Preserve unfinished work before replaying its stable task identities."""
    run_root = run_dir.resolve()
    snapshot = json.loads((run_root / "generations" / f"generation_{generation:04d}.json").read_text(encoding="utf-8"))
    pending: list[Path] = []
    for root_name in ("candidates", "generated_agents", "classes", "classes/.generation_attempts"):
        root = run_root / root_name
        for path in sorted(root.glob("gen_*")):
            match = re.match(r"gen_(\d+)_", path.name)
            if match and int(match.group(1)) > generation:
                pending.append(path)
    for path in sorted((run_root / "generations").glob("generation_*")):
        match = re.match(r"generation_(\d+)", path.name)
        if match and int(match.group(1)) > generation:
            pending.append(path)
    archived_logs: dict[Path, dict] = {}
    for path in sorted((run_root / "llm_logs").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidate_match = re.match(r"gen_(\d+)_", str(payload.get("candidate_id") or ""))
        log_generation = payload.get("generation")
        if (candidate_match and int(candidate_match.group(1)) > generation) or (
            log_generation is not None and int(log_generation) > generation
        ):
            pending.append(path)
            archived_logs[path] = payload
    archives = snapshot.get("resume_archives")
    if isinstance(archives, dict):
        for name in RESUME_ARCHIVE_PATHS:
            path = run_root / name
            if name in archives and path.is_file() and path.read_text(encoding="utf-8") != archives[name]:
                pending.append(path)
    if pending:
        archive_root = run_root / "archives" / "interrupted_work"
        attempt = 1
        while (archive_root / f"attempt_{attempt:04d}").exists():
            attempt += 1
        archive_root = archive_root / f"attempt_{attempt:04d}"
        moved_roots = [source.relative_to(run_root).as_posix() for source in pending]
        for source in pending:
            resolved = source.resolve()
            destination = archive_root / source.relative_to(run_root)
            if not resolved.is_relative_to(run_root) or not destination.resolve().is_relative_to(run_root):
                raise ValueError(f"Interrupted artifact escapes the run directory: {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            if source in archived_logs:
                payload = archived_logs[source]
                refs = payload.get("artifact_refs")
                if isinstance(refs, dict):
                    prefix = archive_root.relative_to(run_root).as_posix()
                    payload["artifact_refs"] = {
                        key: f"{prefix}/{value}" if isinstance(value, str) and any(
                            value == root or value.startswith(root + "/") for root in moved_roots
                        ) else value
                        for key, value in refs.items()
                    }
                    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if isinstance(archives, dict):
        for name in RESUME_ARCHIVE_PATHS:
            value = archives.get(name)
            if value is not None:
                path = run_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")
