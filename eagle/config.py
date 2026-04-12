"""Configuration objects for the EA pipeline.

The public API intentionally stays flat so existing call sites can continue to
use `config.population_size` or `config.surrogate_version` directly, while this
file groups related settings and exposes a few helper accessors for cleaner use
inside refactored modules.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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


def _default_reproduction_operator_probs() -> dict[str, float]:
    """Return the default steady-state reproduction-operator distribution."""
    return {
        "crossover": 0.45,
        "mutation": 0.45,
        "reflection": 0.10,
    }


def _legacy_reproduction_operator_probs() -> dict[str, float]:
    """Return the pre-reflection fallback distribution for older saved runs."""
    return {
        "crossover": 0.50,
        "mutation": 0.50,
        "reflection": 0.0,
    }


@dataclass
class EAConfig:
    """Flat configuration surface for all EA, evaluation, and surrogate settings."""
    algorithm: str = "steady_state_nsga2"
    population_size: int = 3
    num_generations: int = 4
    mutation_rate: float = 0.1
    reproduction_operator_probs: dict[str, float] = field(
        default_factory=_default_reproduction_operator_probs
    )
    enable_reflection_operator: bool = True
    reflection_max_components_to_rewrite: int = 1
    strategy_mutation_pool_replacement_prob: float = 0.40
    strategy_mutation_identity_preserving_rewrite_prob: float = 0.35
    strategy_mutation_identity_shift_rewrite_prob: float = 0.15
    strategy_mutation_crossover_repair_rewrite_prob: float = 0.10
    selection_method: str = "random"
    tournament_size: int = 3
    crossover_mode: str = "uniform"
    crossover_method: str = "uniform"
    environment_selection_method: str = "elitism"
    steady_state_surrogate_offspring_count: int = 4
    steady_state_surrogate_selection_metric: str = "game_round_score"
    final_test_max_front: int | None = 1

    run_time_per_game_sec: int = 10
    real_eval_rate: float = 0.25
    llm_interval: int = 1

    resource_advantage_alpha: float = 2.0
    resource_advantage_weights: dict[str, float] = field(
        default_factory=_default_resource_advantage_weights
    )

    surrogate_version: str = "policy"
    surrogate_recent_log_window: int = 10
    surrogate_game_round_samples: int = 10
    surrogate_log_dir: str = "logs"

    def __post_init__(self) -> None:
        """Normalize aliases and validate the config surface eagerly."""
        self._legacy_missing_reproduction_operator_probs = False
        self._sync_crossover_aliases()
        self.validate()

    def _sync_crossover_aliases(self) -> None:
        """Keep the legacy `crossover_method` field aligned with `crossover_mode`."""
        normalized_mode = str(self.crossover_mode or self.crossover_method or "uniform").strip().lower()
        normalized_method = str(self.crossover_method or normalized_mode).strip().lower()
        if normalized_mode != normalized_method:
            normalized_method = normalized_mode
        self.crossover_mode = normalized_mode
        self.crossover_method = normalized_method

    def validate(self) -> None:
        """Validate config values that affect offspring generation behavior."""
        self._sync_crossover_aliases()

        if self.reflection_max_components_to_rewrite < 1:
            raise ValueError("reflection_max_components_to_rewrite must be >= 1.")

        if self.crossover_mode != "uniform":
            raise ValueError(
                f"Unsupported crossover_mode: {self.crossover_mode!r}. Only 'uniform' is supported."
            )

        probabilities = self._normalized_probability_input(self.reproduction_operator_probs)
        expected_keys = {"crossover", "mutation", "reflection"}
        actual_keys = set(probabilities.keys())
        if actual_keys != expected_keys:
            raise ValueError(
                "reproduction_operator_probs must define exactly "
                f"{sorted(expected_keys)}, got {sorted(actual_keys)}."
            )

        total = 0.0
        for operator_name, value in probabilities.items():
            if value < 0:
                raise ValueError(
                    f"reproduction_operator_probs[{operator_name!r}] must be >= 0, got {value}."
                )
            total += value

        if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError(
                "reproduction_operator_probs must sum to 1.0 within tolerance; "
                f"got {total:.8f} from {probabilities}."
            )

        effective = self.reproduction_operator_weights()
        if not effective:
            raise ValueError(
                "At least one reproduction operator must remain enabled after applying "
                "enable_reflection_operator and zero-probability filters."
            )

    def evolution_settings(self) -> dict[str, object]:
        """Return the subset of fields that control population search behavior."""
        return {
            "algorithm": self.algorithm,
            "population_size": self.population_size,
            "num_generations": self.num_generations,
            "mutation_rate": self.mutation_rate,
            "reproduction_operator_probs": dict(self.reproduction_operator_probs),
            "enable_reflection_operator": self.enable_reflection_operator,
            "reflection_max_components_to_rewrite": self.reflection_max_components_to_rewrite,
            "strategy_mutation_pool_replacement_prob": self.strategy_mutation_pool_replacement_prob,
            "strategy_mutation_identity_preserving_rewrite_prob": self.strategy_mutation_identity_preserving_rewrite_prob,
            "strategy_mutation_identity_shift_rewrite_prob": self.strategy_mutation_identity_shift_rewrite_prob,
            "strategy_mutation_crossover_repair_rewrite_prob": self.strategy_mutation_crossover_repair_rewrite_prob,
            "selection_method": self.selection_method,
            "tournament_size": self.tournament_size,
            "crossover_mode": self.crossover_mode,
            "crossover_method": self.crossover_method,
            "environment_selection_method": self.environment_selection_method,
            "steady_state_surrogate_offspring_count": self.steady_state_surrogate_offspring_count,
            "steady_state_surrogate_selection_metric": self.steady_state_surrogate_selection_metric,
            "final_test_max_front": self.final_test_max_front,
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

    def strategy_mutation_mode_weights(self) -> dict[str, float]:
        """Return normalized sampling weights for strategy-mutation dispatch."""
        weights = {
            "pool_replacement": float(self.strategy_mutation_pool_replacement_prob),
            "identity_preserving_rewrite": float(self.strategy_mutation_identity_preserving_rewrite_prob),
            "identity_shift_rewrite": float(self.strategy_mutation_identity_shift_rewrite_prob),
            "crossover_repair_rewrite": float(self.strategy_mutation_crossover_repair_rewrite_prob),
        }
        total = sum(max(0.0, value) for value in weights.values())
        if total <= 0:
            return {
                "pool_replacement": 1.0,
                "identity_preserving_rewrite": 0.0,
                "identity_shift_rewrite": 0.0,
                "crossover_repair_rewrite": 0.0,
            }
        return {
            key: max(0.0, value) / total
            for key, value in weights.items()
        }

    def reproduction_operator_weights(self) -> dict[str, float]:
        """Return the effective operator distribution after reflection gating."""
        probabilities = self._normalized_probability_input(self.reproduction_operator_probs)
        if not self.enable_reflection_operator:
            probabilities["reflection"] = 0.0

        filtered = {key: value for key, value in probabilities.items() if value > 0.0}
        total = sum(filtered.values())
        if total <= 0.0:
            return {}
        return {key: value / total for key, value in filtered.items()}

    @staticmethod
    def _normalized_probability_input(raw_probabilities: dict[str, float] | None) -> dict[str, float]:
        """Convert operator probabilities into a plain float dictionary."""
        probabilities = dict(raw_probabilities or {})
        return {str(key): float(value) for key, value in probabilities.items()}


def load_config_payload(payload: dict[str, Any] | None) -> EAConfig:
    """Build one validated config from a JSON-like payload."""
    payload = dict(payload or {})
    config = EAConfig()
    valid_fields = set(config.__dataclass_fields__.keys())

    if "reproduction_operator_probs" not in payload:
        config.reproduction_operator_probs = _legacy_reproduction_operator_probs()
        config._legacy_missing_reproduction_operator_probs = True

    for key, value in payload.items():
        if key not in valid_fields:
            continue
        setattr(config, key, value)

    if "crossover_mode" not in payload and "crossover_method" in payload:
        config.crossover_mode = str(payload["crossover_method"])
    if "crossover_method" not in payload and "crossover_mode" in payload:
        config.crossover_method = str(payload["crossover_mode"])

    config.validate()
    return config


def load_config_from_json(path_or_dir: str | Path) -> EAConfig:
    """Load a saved config file or run directory into a validated `EAConfig`."""
    candidate_path = Path(path_or_dir)
    config_path = candidate_path / "config.json" if candidate_path.is_dir() else candidate_path
    if not config_path.exists():
        return EAConfig()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return load_config_payload(payload)
