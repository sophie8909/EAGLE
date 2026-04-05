"""
Main entry point for running the evolutionary algorithm to optimize prompt components for MicroRTS. 
This script initializes the experiment configuration, loads the prompt components, and executes the selected evolutionary algorithm to evolve effective prompts for guiding agent behavior in MicroRTS.
"""

OPPONENT_LIST = [
    "ai.RandomBiasedAI",
    "ai.RandomAI",
    "ai.PassiveAI",
    "ai.abstraction.HeavyRush",
    "ai.abstraction.LightRush",
    # "ai.abstraction.LLM_Gemini", # game log diff, ignore it
    "ai.abstraction.ollama",
    "ai.abstraction.HybridLLMRush",
    "ai.abstraction.StrategicLLMAgent",
    "ai.abstraction.TurtleDefense", 
    "ai.abstraction.BoomEconomy"
]

def _find_latest_log_dir() -> str | None:
    """Return the newest timestamped run directory under `logs/`, if any."""
    from pathlib import Path

    logs_dir = Path("logs")
    if not logs_dir.exists():
        return None

    candidates = [path for path in logs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return str(sorted(candidates)[-1])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run or resume the EAGLE evolutionary search.")
    parser.add_argument("--resume-log-dir", type=str, default=None, help="Resume from an existing log directory.")
    parser.add_argument("--resume-latest", action="store_true", help="Resume from the most recent run in logs/.")
    args = parser.parse_args()

    resume_log_dir = args.resume_log_dir
    if args.resume_latest and resume_log_dir is None:
        resume_log_dir = _find_latest_log_dir()

    # load configuration
    from .config import EAConfig
    config = EAConfig()
    # load prompt components    
    from .component_pool import ComponentPool
    component_pool = ComponentPool.from_json("prompts/components.json")
    # run evolutionary algorithm    
    if config.algorithm == "ga":
        from .ga import GA
        ga = GA(config, component_pool, opponent_list=OPPONENT_LIST)
        if resume_log_dir:
            ga.attach_log_dir(resume_log_dir)
        ga.save_config(ga.create_log_folder())
        ga.run()
    elif config.algorithm == "nsga2":
        from .nsga2 import NSGA2
        nsga2 = NSGA2(config, component_pool, opponent_list=OPPONENT_LIST)
        if resume_log_dir:
            nsga2.attach_log_dir(resume_log_dir)
        nsga2.save_config(nsga2.create_log_folder())
        nsga2.run()
        print("Running final test for NSGA2...")
        nsga2.run_final_test()
    # elif config.algorithm == "moead":
    #     from .moead import MOEAD
    #     moead = MOEAD(config, component_pool)
    #     moead.run()
    else:
        raise ValueError(f"Unsupported algorithm: {config.algorithm}")
    

    
