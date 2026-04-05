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

if __name__ == "__main__":
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
        ga.save_config(ga.create_log_folder())
        ga.run()
    elif config.algorithm == "nsga2":
        from .nsga2 import NSGA2
        nsga2 = NSGA2(config, component_pool, opponent_list=OPPONENT_LIST)
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
    

    
