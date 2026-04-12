"""Top-level entry point for running the EAGLE search."""

from __future__ import annotations

from pathlib import Path

from .config import EAConfig, load_config_from_json
from .tools.component_pool import ComponentPool

OPPONENT_LIST = [
    "ai.PassiveAI",
    "ai.RandomAI",
    "ai.RandomBiasedAI",
    "ai.abstraction.HeavyRush",
    "ai.abstraction.LightRush",
    "ai.abstraction.WorkerRush",
]


def _find_latest_log_dir() -> str | None:
    """Return the newest timestamped run directory under `eagle/logs/`, if any."""
    repo_root = Path(__file__).resolve().parents[1]
    logs_dir = repo_root / "eagle" / "logs"
    if not logs_dir.exists():
        return None

    candidates = [path for path in logs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return str(sorted(candidates)[-1])


def _resolve_component_pool_path() -> str:
    """Resolve the prompt component JSON relative to the repository root."""
    repo_root = Path(__file__).resolve().parents[1]
    component_pool_path = repo_root / "eagle" / "prompts" / "components.json"
    return str(component_pool_path)


def main() -> None:
    """Run or resume the configured EAGLE evolutionary search."""
    import argparse

    parser = argparse.ArgumentParser(description="Run or resume the EAGLE evolutionary search.")
    parser.add_argument("--resume-log-dir", type=str, default=None, help="Resume from an existing log directory.")
    parser.add_argument("--resume-latest", action="store_true", help="Resume from the most recent run in eagle/logs/.")
    args = parser.parse_args()

    resume_log_dir = args.resume_log_dir
    if args.resume_latest and resume_log_dir is None:
        resume_log_dir = _find_latest_log_dir()

    config = load_config_from_json(resume_log_dir) if resume_log_dir else EAConfig()
    config.validate()
    component_pool = ComponentPool.from_json(_resolve_component_pool_path())
    if config.algorithm == "ga":
        from .algorithm.ga import GA

        ga = GA(config, component_pool, opponent_list=OPPONENT_LIST)
        if resume_log_dir:
            ga.attach_log_dir(resume_log_dir)
        ga.save_config(ga.create_log_folder())
        ga.run()
    elif config.algorithm == "nsga2":
        from .algorithm.nsga2 import NSGA2

        nsga2 = NSGA2(config, component_pool, opponent_list=OPPONENT_LIST)
        if resume_log_dir:
            nsga2.attach_log_dir(resume_log_dir)
        nsga2.save_config(nsga2.create_log_folder())
        nsga2.run()
        print("Running final test for NSGA2...")
        nsga2.run_final_test()
    elif config.algorithm == "steady_state_nsga2":
        from .algorithm.steady_state_nsga2 import SteadyStateNSGA2

        steady_state_nsga2 = SteadyStateNSGA2(config, component_pool, opponent_list=OPPONENT_LIST)
        if resume_log_dir:
            steady_state_nsga2.attach_log_dir(resume_log_dir)
        steady_state_nsga2.save_config(steady_state_nsga2.create_log_folder())
        steady_state_nsga2.run()
        print("Running final test for Steady-State NSGA2...")
        steady_state_nsga2.run_final_test()
    else:
        raise ValueError(f"Unsupported algorithm: {config.algorithm}")


if __name__ == "__main__":
    main()
