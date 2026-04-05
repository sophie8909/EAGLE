"""
Configuration for the Evolutionary Algorithm.
This module defines the EAConfig class, which encapsulates the configuration parameters for the genetic algorithm used to evolve prompt components for guiding agent behavior in MicroRTS. The EAConfig class includes parameters such as population size, number of generations, mutation rate, selection method, and other relevant settings that control the behavior of the evolutionary algorithm. This configuration is used by the GA class to initialize and run the genetic algorithm effectively.
"""


from dataclasses import dataclass
from dataclasses import field

@dataclass
class EAConfig:
    algorithm: str = "nsga2"  # Options: "ga", "nsga2", "moead"
    population_size: int = 20  
    num_generations: int = 50
    mutation_rate: float = 0.1
    run_time_per_game_sec: int = 500
    real_eval_rate: float = 0.25
    tournament_size: int = 3
    selection_method: str = "random"  # Options: "random", "tournament"
    crossover_method: str = "uniform"  # Options: "uniform", "one_point", "two_point"
    environment_selection_method: str = "elitism"
    resource_advantage_alpha: float = 2.0
    resource_advantage_weights: dict[str, float] = field(
        default_factory=lambda: {
            "base": 10.0,
            "worker": 1.0,
            "light": 2.0,
            "heavy": 2.0,
            "ranged": 2.0,
            "resource": 1.0,
        }
    )
    surrogate_version: str = "llm"  # Options: "llm", "game_round"
    surrogate_recent_log_window: int = 10
    surrogate_game_round_samples: int = 10
    surrogate_log_dir: str = "logs"
    
