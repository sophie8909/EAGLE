"""Top-level entry point for running the EAGLE search."""

from __future__ import annotations

from .config import EAConfig, load_config_from_json
from .project import DEFAULT_EVOLUTION_CONFIG_PATH, EAGLE_LOGS_DIR, PROMPTS_DIR
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


def _find_latest_log_dir() -> str | None:
    """Return the newest timestamped run directory under `logs/eagle/`, if any."""
    logs_dir = EAGLE_LOGS_DIR
    if not logs_dir.exists():
        return None

    candidates = [path for path in logs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return str(sorted(candidates)[-1])


def _resolve_component_pool_path() -> str:
    """Resolve the prompt component JSON relative to the repository root."""
    component_pool_path = PROMPTS_DIR / "components.json"
    return str(component_pool_path)


def _resolve_base_config(args, resume_log_dir: str | None) -> EAConfig:
    """Resolve the base config from resume logs, explicit config, or default config."""
    if resume_log_dir:
        return load_config_from_json(resume_log_dir)
    if args.config:
        return load_config_from_json(args.config)
    if DEFAULT_EVOLUTION_CONFIG_PATH.exists():
        return load_config_from_json(DEFAULT_EVOLUTION_CONFIG_PATH)
    return EAConfig()


def _build_runtime_config(args, resume_log_dir: str | None) -> EAConfig:
    """Build one runtime config with optional quick-run and CLI overrides."""
    config = _resolve_base_config(args, resume_log_dir)

    if args.algorithm:
        config.algorithm = args.algorithm

    if args.timeout_sec is not None:
        config.run_time_per_game_sec = max(1, int(args.timeout_sec))

    if args.quick_run:
        config.population_size = max(2, min(config.population_size, 2))
        config.num_generations = 2
        config.real_eval_rate = 0.0
        config.steady_state_surrogate_offspring_count = 2
        config.run_time_per_game_sec = 30
        config.final_test_max_front = 0

    config.validate()
    return config


def _resolve_opponent_list(args) -> list[str]:
    """Resolve the opponent list used by the current run."""
    if args.opponent:
        return [args.opponent]
    if args.quick_run:
        return [DEFAULT_EA_QUICK_RUN_OPPONENT]
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
        help=f"Load one base config JSON file. Defaults to {DEFAULT_EVOLUTION_CONFIG_PATH.as_posix()} when present.",
    )
    parser.add_argument(
        "--algorithm",
        choices=["ga", "nsga2", "steady_state_nsga2"],
        default=None,
        help="Override the algorithm for this run.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=None,
        help="Override the per-game MicroRTS timeout in seconds.",
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
        "--opponent",
        type=str,
        default=None,
        help="Use a single opponent class for this run.",
    )
    args = parser.parse_args()

    resume_log_dir = args.resume_log_dir
    if args.resume_latest and resume_log_dir is None:
        resume_log_dir = _find_latest_log_dir()

    config = _build_runtime_config(args, resume_log_dir)
    opponent_list = _resolve_opponent_list(args)
    should_run_final_test = _should_run_final_test(args, config)
    component_pool = ComponentPool.from_json(_resolve_component_pool_path())
    if config.algorithm == "ga":
        from .evolution.ga import GA

        ga = GA(config, component_pool, opponent_list=opponent_list)
        if resume_log_dir:
            ga.attach_log_dir(resume_log_dir)
        ga.save_config(ga.create_log_folder())
        ga.run()
    elif config.algorithm == "nsga2":
        from .evolution.nsga2 import NSGA2

        nsga2 = NSGA2(config, component_pool, opponent_list=opponent_list)
        if resume_log_dir:
            nsga2.attach_log_dir(resume_log_dir)
        nsga2.save_config(nsga2.create_log_folder())
        nsga2.run()
        if should_run_final_test:
            print("Running final test for NSGA2...")
            nsga2.run_final_test()
        else:
            print("Skipping final test.")
    elif config.algorithm == "steady_state_nsga2":
        from .evolution.steady_state_nsga2 import SteadyStateNSGA2

        steady_state_nsga2 = SteadyStateNSGA2(config, component_pool, opponent_list=opponent_list)
        if resume_log_dir:
            steady_state_nsga2.attach_log_dir(resume_log_dir)
        steady_state_nsga2.save_config(steady_state_nsga2.create_log_folder())
        steady_state_nsga2.run()
        if should_run_final_test:
            print("Running final test for Steady-State NSGA2...")
            steady_state_nsga2.run_final_test()
        else:
            print("Skipping final test.")
    else:
        raise ValueError(f"Unsupported algorithm: {config.algorithm}")


if __name__ == "__main__":
    main()
