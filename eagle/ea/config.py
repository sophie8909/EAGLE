"""Configuration objects for the EA pipeline.

The public API intentionally stays flat so existing call sites can continue to
use `config.population_size` or `config.surrogate_version` directly, while this
file groups related settings and exposes a few helper accessors for cleaner use
inside refactored modules.
"""

from dataclasses import dataclass, field


def _default_resource_advantage_weights() -> dict[str, float]:
    """Return the default material weights used by the resource-advantage objective."""
    return {
        "base": 10.0,
        "worker": 1.0,
        "light": 2.0,
        "heavy": 2.0,
        "ranged": 2.0,
        "resource": 1.0,
    }


@dataclass
class EAConfig:
    """Flat configuration surface for all EA, evaluation, and surrogate settings."""
    # Evolution / search settings
    algorithm: str = "nsga2"  # Options: "ga", "nsga2", "steady_state_nsga2", "moead"
    population_size: int = 20
    num_generations: int = 50
    mutation_rate: float = 0.1
    selection_method: str = "random"  # Options: "random", "tournament"
    tournament_size: int = 3
    crossover_method: str = "uniform"  # Options: "uniform", "one_point", "two_point"
    environment_selection_method: str = "elitism"

    # Evaluation runtime settings
    run_time_per_game_sec: int = 500
    real_eval_rate: float = 0.25

    # Fitness settings
    resource_advantage_alpha: float = 2.0
    resource_advantage_weights: dict[str, float] = field(
        default_factory=_default_resource_advantage_weights
    )

    # Surrogate settings
    surrogate_version: str = "llm"  # Options: "llm", "game_round"
    surrogate_recent_log_window: int = 10
    surrogate_game_round_samples: int = 10
    surrogate_log_dir: str = "logs"

    def evolution_settings(self) -> dict[str, object]:
        """Return the subset of fields that control population search behavior."""
        return {
            "algorithm": self.algorithm,
            "population_size": self.population_size,
            "num_generations": self.num_generations,
            "mutation_rate": self.mutation_rate,
            "selection_method": self.selection_method,
            "tournament_size": self.tournament_size,
            "crossover_method": self.crossover_method,
            "environment_selection_method": self.environment_selection_method,
        }

    def fitness_settings(self) -> dict[str, object]:
        """Return the subset of fields that affect fitness computation only."""
        return {
            "resource_advantage_alpha": self.resource_advantage_alpha,
            "resource_advantage_weights": dict(self.resource_advantage_weights),
        }

    def surrogate_settings(self) -> dict[str, object]:
        """Return the subset of fields used by surrogate evaluators."""
        return {
            "surrogate_version": self.surrogate_version,
            "surrogate_recent_log_window": self.surrogate_recent_log_window,
            "surrogate_game_round_samples": self.surrogate_game_round_samples,
            "surrogate_log_dir": self.surrogate_log_dir,
        }

    @property
    def normalized_surrogate_version(self) -> str:
        """Expose the surrogate mode in normalized lowercase form."""
        return str(self.surrogate_version).strip().lower()

    def real_eval_count(self, candidate_count: int | None = None) -> int:
        """Convert `real_eval_rate` into an integer evaluation budget."""
        total = candidate_count if candidate_count is not None else self.population_size
        budget = int(total * self.real_eval_rate)
        if self.real_eval_rate > 0 and budget == 0:
            return 1
        return max(0, budget)
    
