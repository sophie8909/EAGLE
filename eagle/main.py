"""Top-level entry point for running the EAGLE search."""

from __future__ import annotations

from pathlib import Path

from .config import EAConfig, load_config_from_json, resolve_component_pool_path
from .experiment.config import ExperimentConfig, load_experiment_config
from .experiment.runner import build_algorithm
from .project import DEFAULT_EVOLUTION_CONFIG_PATH, EAGLE_LOGS_DIR, PROMPTS_DIR
from .utils.experiment_logs import resolve_resume_log_dir, resolve_resume_log_dir_from_config
from .utils.component_pool import ComponentPool

OPPONENT_LIST = [
    "ai.PassiveAI",
    "ai.RandomAI",
    "ai.RandomBiasedAI",
    "ai.abstraction.HeavyRush",
    "ai.abstraction.LightRush",
    # "ai.abstraction.WorkerRush",
]
DEFAULT_EA_QUICK_RUN_OPPONENT = "ai.PassiveAI"
SURROGATE_ALGORITHMS = {"ga_surrogate", "nsga2_surrogate"}


def _find_latest_log_dir() -> str | None:
    """Return the newest timestamped run directory under `logs/eagle/`, if any."""
    logs_dir = EAGLE_LOGS_DIR
    if not logs_dir.exists():
        return None

    candidates = [path for path in logs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return str(sorted(candidates)[-1])


def _resolve_requested_resume_log_dir(args) -> str | None:
    """Resolve explicit, latest, or checkpoint-config resume requests."""
    resume_log_dir = args.resume_log_dir
    if args.resume_latest and resume_log_dir is None:
        resume_log_dir = _find_latest_log_dir()
    if resume_log_dir:
        return str(resolve_resume_log_dir(resume_log_dir))
    config_resume_log_dir = resolve_resume_log_dir_from_config(args.config)
    return str(config_resume_log_dir) if config_resume_log_dir is not None else None


def _resolve_component_pool_path() -> str:
    """Resolve the prompt component JSON relative to the repository root."""
    component_pool_path = PROMPTS_DIR / "components.json"
    return str(component_pool_path)


def _resolve_component_pool_path_from_config(config: EAConfig, args, resume_log_dir: str | None) -> str:
    """Resolve the component-pool path from runtime config with sensible relative-path bases."""
    if args.config:
        return str(resolve_component_pool_path(config, base_dir=Path(args.config).resolve().parent))
    if resume_log_dir:
        return str(resolve_component_pool_path(config, base_dir=resume_log_dir))
    return str(resolve_component_pool_path(config))


def _resolve_base_config(args, resume_log_dir: str | None) -> EAConfig:
    """Resolve the base config from resume logs, explicit config, or default config."""
    if resume_log_dir:
        return load_config_from_json(resume_log_dir)
    if args.config:
        return load_experiment_config(args.config).ea
    if DEFAULT_EVOLUTION_CONFIG_PATH.exists():
        return load_config_from_json(DEFAULT_EVOLUTION_CONFIG_PATH, validate=False)
    return EAConfig()


def _build_runtime_config(args, resume_log_dir: str | None) -> EAConfig:
    """Build one runtime config with optional quick-run and CLI overrides."""
    config = _resolve_base_config(args, resume_log_dir)

    if args.algorithm:
        config.algorithm = args.algorithm

    if args.evaluator:
        config.evaluator = args.evaluator

    if args.surrogate and str(config.algorithm).strip().lower() in SURROGATE_ALGORITHMS:
        config.surrogate = args.surrogate

    if args.tick_limit is not None:
        config.tick_limit = max(1, int(args.tick_limit))

    if args.quick_run:
        config.population_size = max(2, min(config.population_size, 2))
        config.num_generations = 2
        config.gameplay_rate = 0.0
        config.tick_limit = 30
        config.final_test_max_front = 0

    config.validate()
    print(
        "[DEBUG] runtime_config "
        f"algorithm={config.algorithm} evaluator={config.evaluator} "
        f"surrogate={config.surrogate if config.algorithm in SURROGATE_ALGORITHMS else '(ignored)'} "
        f"objective_config={config.objective_config} "
        f"population={config.population_size} generations={config.num_generations} "
        f"gameplay_refresh_interval={config.gameplay_refresh_interval} "
        f"surrogate_top_ratio={config.surrogate_top_ratio} "
        f"archive_parent_ratio={config.archive_parent_ratio}",
        flush=True,
    )
    return config


def _resolve_opponent_list(args, config: EAConfig) -> list[str]:
    """Resolve the opponent list used by the current run."""
    if args.opponent:
        return [args.opponent]
    if args.quick_run:
        return [DEFAULT_EA_QUICK_RUN_OPPONENT]
    configured_opponents = list(getattr(config, "gameplay_opponents", []) or [])
    if configured_opponents:
        return configured_opponents
    return list(OPPONENT_LIST)


def _should_run_final_test(args, config: EAConfig) -> bool:
    """Return whether the configured run should enter the final-test stage."""
    if args.skip_final_test:
        return False
    if config.final_test_max_front is not None and int(config.final_test_max_front) < 1:
        return False
    return True


def main() -> None:
    """Run or resume the configured EAGLE evolutionary search."""
    import argparse

    parser = argparse.ArgumentParser(description="Run or resume the EAGLE evolutionary search.")
    parser.add_argument("--resume-log-dir", type=str, default=None, help="Resume from an existing log directory.")
    parser.add_argument("--resume-latest", action="store_true", help="Resume from the most recent run in logs/eagle/.")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Load one base config JSON/YAML file. Defaults to {DEFAULT_EVOLUTION_CONFIG_PATH.as_posix()} when present.",
    )
    parser.add_argument(
        "--algorithm",
        choices=["ga", "nsga2", "ga_surrogate", "nsga2_surrogate"],
        default=None,
        help="Override the algorithm for this run.",
    )
    parser.add_argument(
        "--evaluator",
        choices=["gameplay"],
        default=None,
        help="Override the evaluator selected by YAML experiment configs.",
    )
    parser.add_argument(
        "--surrogate",
        choices=["round", "policy_agent", "java_agent"],
        default=None,
        help="Select the gameplay agent surrogate mode.",
    )
    parser.add_argument(
        "--tick-limit",
        type=int,
        default=None,
        help="Override the per-game MicroRTS tick limit.",
    )
    parser.add_argument(
        "--quick-run",
        action="store_true",
        help="Run a minimal end-to-end EA smoke benchmark with a tiny population.",
    )
    parser.add_argument(
        "--skip-final-test",
        action="store_true",
        help="Skip the final evaluation stage for NSGA-II variants.",
    )
    parser.add_argument(
        "--final-test",
        action="store_true",
        help="Run the final evaluation stage when final_test_max_front allows it.",
    )
    parser.add_argument(
        "--opponent",
        type=str,
        default=None,
        help="Use a single opponent class for this run.",
    )
    parser.add_argument(
        "--precompile-python",
        action="store_true",
        help="Precompile EAGLE Python modules to bytecode before launching the run.",
    )
    args = parser.parse_args()

    if args.precompile_python:
        from .utils.precompile import precompile_python_sources

        metadata = precompile_python_sources()
        print(
            "[DEBUG] python precompile "
            f"targets={metadata['targets']} ok={bool(metadata['ok'])} "
            f"elapsed={float(metadata['elapsed_sec']):.2f}s",
            flush=True,
        )

    resume_log_dir = _resolve_requested_resume_log_dir(args)

    config = _build_runtime_config(args, resume_log_dir)
    opponent_list = _resolve_opponent_list(args, config)
    should_run_final_test = _should_run_final_test(args, config)
    component_pool = ComponentPool.from_json(
        _resolve_component_pool_path_from_config(config, args, resume_log_dir)
    )
    if args.config:
        experiment_config = load_experiment_config(args.config)
        experiment_config.ea = config
        experiment_config.opponents = opponent_list
        experiment_config.algorithm = config.algorithm
        experiment_config.evaluator = config.evaluator
    else:
        experiment_config = ExperimentConfig(
            algorithm=config.algorithm,
            evaluator=config.evaluator,
            ea=config,
            opponents=opponent_list,
        )
    if args.evaluator:
        experiment_config.evaluator = args.evaluator
        config.evaluator = args.evaluator
    if args.surrogate and config.algorithm in SURROGATE_ALGORITHMS:
        experiment_config.evaluator = config.evaluator

    print(
        "[DEBUG] launch "
        f"component_pool={_resolve_component_pool_path_from_config(config, args, resume_log_dir)} "
        f"opponents={opponent_list} final_test={should_run_final_test}",
        flush=True,
    )
    algorithm = build_algorithm(
        experiment_config,
        component_pool=component_pool,
        opponent_list=opponent_list,
    )
    if resume_log_dir:
        algorithm.attach_log_dir(resume_log_dir)
    algorithm.save_config(algorithm.create_log_folder())
    algorithm.run()
    if hasattr(algorithm, "run_final_test"):
        if should_run_final_test:
            print(f"Running final test for {experiment_config.algorithm}...")
            timing_recorder = getattr(algorithm, "timing_recorder", None)
            if timing_recorder is None:
                algorithm.run_final_test()
            else:
                with timing_recorder.phase("final_test"):
                    algorithm.run_final_test()
                timing_recorder.write_summary(status="complete")
        else:
            print("Skipping final test.")


if __name__ == "__main__":
    main()
