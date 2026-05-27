"""Config-driven runner for the prompt-search framework."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import resolve_component_pool_path
from ..core.registry import ALGORITHMS, normalize_registry_name
from ..project import PROMPTS_DIR
from ..utils.component_pool import ComponentPool
from ..utils.experiment_logs import resolve_resume_log_dir, resolve_resume_log_dir_from_config
from .config import ExperimentConfig, load_experiment_config


def build_algorithm(
    experiment: ExperimentConfig,
    *,
    component_pool: ComponentPool | None = None,
    opponent_list: list[str] | None = None,
) -> Any:
    """Instantiate the configured algorithm through the algorithm registry."""
    _ensure_default_registrations()
    algorithm_name = normalize_registry_name(experiment.algorithm)
    algorithm_cls = ALGORITHMS.get(algorithm_name)
    pool = component_pool or ComponentPool.from_json(resolve_component_pool_path(experiment.ea))
    opponents = list(opponent_list if opponent_list is not None else experiment.opponents)
    if not opponents:
        opponents = list(experiment.ea.gameplay_opponents)
    algorithm = algorithm_cls(experiment.ea, pool, opponent_list=opponents)
    algorithm.evaluator_name = experiment.evaluator
    algorithm.evaluator_params = dict(experiment.evaluator_params)
    print(
        "[DEBUG] build_algorithm "
        f"algorithm={experiment.algorithm} evaluator={experiment.evaluator} "
        f"surrogate={getattr(experiment.ea, 'surrogate', 'unknown')} "
        f"objective_config={getattr(experiment.ea, 'objective_config', {})} "
        f"opponents={opponents}",
        flush=True,
    )
    return algorithm


def run_experiment(
    config_path: str | Path | None = None,
    *,
    resume_log_dir: str | Path | None = None,
    component_pool: ComponentPool | None = None,
    opponent_list: list[str] | None = None,
    run_final_test: bool = True,
) -> Any:
    """Run an experiment selected by config instead of hard-coded branching."""
    experiment = load_experiment_config(config_path)
    algorithm = build_algorithm(
        experiment,
        component_pool=component_pool,
        opponent_list=opponent_list,
    )
    if resume_log_dir is None:
        resume_log_dir = resolve_resume_log_dir_from_config(config_path)
    if resume_log_dir:
        algorithm.attach_log_dir(resolve_resume_log_dir(resume_log_dir))
    log_dir = algorithm.create_log_folder()
    algorithm.save_config(log_dir)
    result = algorithm.run()
    if run_final_test and hasattr(algorithm, "run_final_test"):
        max_front = getattr(experiment.ea, "final_test_max_front", None)
        if max_front is None or int(max_front) >= 1:
            timing_recorder = getattr(algorithm, "timing_recorder", None)
            if timing_recorder is None:
                algorithm.run_final_test()
            else:
                with timing_recorder.phase("final_test"):
                    algorithm.run_final_test()
                timing_recorder.write_summary(status="complete")
    return result


def _ensure_default_registrations() -> None:
    """Import default component modules so decorators populate registries."""
    from .. import operators  # noqa: F401
    from ..evolution.component import algorithms as component_algorithms  # noqa: F401
    from ..eval.microrts import algorithms as microrts_algorithms  # noqa: F401


def default_component_pool() -> ComponentPool:
    """Return the bundled MicroRTS component pool."""
    return ComponentPool.from_json(PROMPTS_DIR / "components.json")
