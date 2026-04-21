"""Configuration objects for the EA pipeline.

The public API intentionally stays flat so existing call sites can continue to
use `config.population_size` or `config.surrogate_version` directly, while this
file groups related settings and exposes a few helper accessors for cleaner use
inside refactored modules.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .project import DEFAULT_EVOLUTION_CONFIG_PATH, PROJECT_ROOT


@lru_cache(maxsize=1)
def _default_evolution_payload() -> dict[str, Any]:
    """Load the canonical default EA settings from configs/evolution/default.json."""
    if not DEFAULT_EVOLUTION_CONFIG_PATH.exists():
        raise FileNotFoundError(
            "Default evolution config not found. "
            f"Expected preset JSON at {DEFAULT_EVOLUTION_CONFIG_PATH}."
        )
    return json.loads(DEFAULT_EVOLUTION_CONFIG_PATH.read_text(encoding="utf-8"))


def _default_config_value(key: str) -> Any:
    """Return one deep-copied default value from the canonical evolution preset."""
    payload = _default_evolution_payload()
    if key not in payload:
        raise KeyError(
            f"Missing required default config key {key!r} in {DEFAULT_EVOLUTION_CONFIG_PATH}."
        )
    return deepcopy(payload[key])


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
    algorithm: str = field(default_factory=lambda: str(_default_config_value("algorithm")))
    population_size: int = field(default_factory=lambda: int(_default_config_value("population_size")))
    num_generations: int = field(default_factory=lambda: int(_default_config_value("num_generations")))
    convergence_generations: int = field(default_factory=lambda: int(_default_config_value("convergence_generations")))
    reproduction_operator_probs: dict[str, float] = field(
        default_factory=lambda: dict(_default_config_value("reproduction_operator_probs"))
    )
    enable_reflection_operator: bool = field(
        default_factory=lambda: bool(_default_config_value("enable_reflection_operator"))
    )
    reflection_max_components_to_rewrite: int = field(
        default_factory=lambda: int(_default_config_value("reflection_max_components_to_rewrite"))
    )
    strategy_mutation: dict[str, float] = field(
        default_factory=lambda: dict(_default_config_value("strategy_mutation"))
    )
    selection_method: str = field(default_factory=lambda: str(_default_config_value("selection_method")))
    tournament_size: int = field(default_factory=lambda: int(_default_config_value("tournament_size")))
    crossover: str = field(default_factory=lambda: str(_default_config_value("crossover")))
    crossover_repair_enabled: bool = field(
        default_factory=lambda: bool(_default_config_value("crossover_repair_enabled"))
    )
    environment_selection_method: str = field(
        default_factory=lambda: str(_default_config_value("environment_selection_method"))
    )
    steady_state_surrogate_offspring_count: int = field(
        default_factory=lambda: int(_default_config_value("steady_state_surrogate_offspring_count"))
    )
    final_test_max_front: int | None = field(default_factory=lambda: _default_config_value("final_test_max_front"))
    include_strategy_identity_in_prompt: bool = field(
        default_factory=lambda: bool(_default_config_value("include_strategy_identity_in_prompt"))
    )
    evolving_prompt_components: list[str] = field(
        default_factory=lambda: list(_default_config_value("evolving_prompt_components"))
    )
    component_pool_path: str = field(default_factory=lambda: str(_default_config_value("component_pool_path")))
    initial_population_seeds: list[dict[str, Any]] = field(
        default_factory=lambda: list(_default_config_value("initial_population_seeds"))
    )

    run_time_per_game_sec: int = field(default_factory=lambda: int(_default_config_value("run_time_per_game_sec")))
    real_eval_rate: float = field(default_factory=lambda: float(_default_config_value("real_eval_rate")))
    real_eval_opponents: list[str] = field(default_factory=lambda: list(_default_config_value("real_eval_opponents")))
    llm_interval: int = field(default_factory=lambda: int(_default_config_value("llm_interval")))

    resource_advantage_alpha: float = field(
        default_factory=lambda: float(_default_config_value("resource_advantage_alpha"))
    )
    resource_advantage_weights: dict[str, float] = field(
        default_factory=lambda: dict(_default_config_value("resource_advantage_weights"))
    )

    surrogate_version: str = field(default_factory=lambda: str(_default_config_value("surrogate_version")))
    surrogate_mode: str = field(default_factory=lambda: str(_default_config_value("surrogate_mode")))
    surrogate_recent_match_window: int = field(
        default_factory=lambda: int(_default_config_value("surrogate_recent_match_window"))
    )
    surrogate_round_samples_per_match: int = field(
        default_factory=lambda: int(_default_config_value("surrogate_round_samples_per_match"))
    )
    surrogate_log_dir: str = field(default_factory=lambda: str(_default_config_value("surrogate_log_dir")))


    def __post_init__(self) -> None:
        """Normalize aliases and validate the config surface eagerly."""
        self._legacy_missing_reproduction_operator_probs = False
        self._normalize_crossover()
        self.validate()

    def _normalize_crossover(self) -> None:
        """Normalize the single crossover selector used by the active code path."""
        self.crossover = str(self.crossover or "uniform").strip().lower()

    def validate(self) -> None:
        """Validate config values that affect offspring generation behavior."""
        self._normalize_crossover()

        if self.reflection_max_components_to_rewrite < 1:
            raise ValueError("reflection_max_components_to_rewrite must be >= 1.")

        if not isinstance(self.evolving_prompt_components, list):
            raise ValueError("evolving_prompt_components must be a list of component keys.")
        self.evolving_prompt_components = [str(key) for key in self.evolving_prompt_components]
        self.component_pool_path = str(self.component_pool_path or "").strip()
        if not self.component_pool_path:
            raise ValueError("component_pool_path must be a non-empty path.")
        if not isinstance(self.initial_population_seeds, list):
            raise ValueError("initial_population_seeds must be a list of seed objects.")
        normalized_seeds: list[dict[str, Any]] = []
        for seed in self.initial_population_seeds:
            if not isinstance(seed, dict):
                raise ValueError("Each initial_population_seeds entry must be a dict.")
            normalized_seeds.append(dict(seed))
        self.initial_population_seeds = normalized_seeds

        if self.crossover != "uniform":
            raise ValueError(
                f"Unsupported crossover: {self.crossover!r}. Only 'uniform' is supported."
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

        strategy_mutation = self._normalized_strategy_mutation_input(self.strategy_mutation)
        expected_mutation_keys = {
            "pool_replacement",
            "identity_preserving_rewrite",
            "identity_shift_rewrite",
        }
        actual_mutation_keys = set(strategy_mutation.keys())
        if actual_mutation_keys != expected_mutation_keys:
            raise ValueError(
                "strategy_mutation must define exactly "
                f"{sorted(expected_mutation_keys)}, got {sorted(actual_mutation_keys)}."
            )
        if all(value <= 0.0 for value in strategy_mutation.values()):
            raise ValueError("strategy_mutation must leave at least one mode enabled.")

        self.strategy_mutation = strategy_mutation

        normalized_surrogate_mode = str(self.surrogate_mode).strip().lower()
        if normalized_surrogate_mode not in {"random", "all_avg"}:
            raise ValueError(
                f"Unsupported surrogate_mode: {self.surrogate_mode!r}. "
                "Use 'random' or 'all_avg'."
            )
        self.surrogate_mode = normalized_surrogate_mode

    def evolution_settings(self) -> dict[str, object]:
        """Return the subset of fields that control population search behavior."""
        return {
            "algorithm": self.algorithm,
            "population_size": self.population_size,
            "num_generations": self.num_generations,
            "reproduction_operator_probs": dict(self.reproduction_operator_probs),
            "enable_reflection_operator": self.enable_reflection_operator,
            "reflection_max_components_to_rewrite": self.reflection_max_components_to_rewrite,
            "strategy_mutation": dict(self.strategy_mutation),
            "selection_method": self.selection_method,
            "tournament_size": self.tournament_size,
            "crossover": self.crossover,
            "crossover_repair_enabled": self.crossover_repair_enabled,
            "environment_selection_method": self.environment_selection_method,
            "steady_state_surrogate_offspring_count": self.steady_state_surrogate_offspring_count,
            "steady_state_surrogate_selection_metric": self.steady_state_surrogate_selection_metric,
            "final_test_max_front": self.final_test_max_front,
            "include_strategy_identity_in_prompt": self.include_strategy_identity_in_prompt,
            "evolving_prompt_components": list(self.evolving_prompt_components),
            "component_pool_path": self.component_pool_path,
            "initial_population_seeds": deepcopy(self.initial_population_seeds),
            "real_eval_opponents": list(self.real_eval_opponents),
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
            "surrogate_mode": self.surrogate_mode,
            "surrogate_recent_match_window": self.surrogate_recent_match_window,
            "surrogate_round_samples_per_match": self.surrogate_round_samples_per_match,
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
        weights = self._normalized_strategy_mutation_input(self.strategy_mutation)
        total = sum(max(0.0, value) for value in weights.values())
        if total <= 0:
            return {
                "pool_replacement": 1.0,
                "identity_preserving_rewrite": 0.0,
                "identity_shift_rewrite": 0.0,
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

    @staticmethod
    def _normalized_strategy_mutation_input(raw_strategy_mutation: dict[str, float] | None) -> dict[str, float]:
        """Convert strategy-mutation weights into a plain float dictionary."""
        strategy_mutation = dict(raw_strategy_mutation or {})
        return {str(key): float(value) for key, value in strategy_mutation.items()}


def load_config_payload(payload: dict[str, Any] | None) -> EAConfig:
    """Build one validated config from a JSON-like payload."""
    payload = dict(payload or {})
    config = EAConfig()
    valid_fields = set(config.__dataclass_fields__.keys())

    if "reproduction_operator_probs" not in payload:
        config.reproduction_operator_probs = _legacy_reproduction_operator_probs()
        config._legacy_missing_reproduction_operator_probs = True

    legacy_strategy_mutation = {
        "pool_replacement": payload.get("strategy_mutation_pool_replacement_prob"),
        "identity_preserving_rewrite": payload.get("strategy_mutation_identity_preserving_rewrite_prob"),
        "identity_shift_rewrite": payload.get("strategy_mutation_identity_shift_rewrite_prob"),
    }
    if "strategy_mutation" not in payload and any(value is not None for value in legacy_strategy_mutation.values()):
        config.strategy_mutation = {
            key: float(value)
            for key, value in legacy_strategy_mutation.items()
            if value is not None
        }

    legacy_crossover_repair_prob = payload.get("strategy_mutation_crossover_repair_rewrite_prob")
    if "crossover_repair_enabled" not in payload and legacy_crossover_repair_prob is not None:
        config.crossover_repair_enabled = float(legacy_crossover_repair_prob) > 0.0

    if "surrogate_recent_match_window" not in payload and "surrogate_recent_log_window" in payload:
        config.surrogate_recent_match_window = int(payload["surrogate_recent_log_window"])
    if "surrogate_round_samples_per_match" not in payload and "surrogate_game_round_samples" in payload:
        config.surrogate_round_samples_per_match = int(payload["surrogate_game_round_samples"])

    for key, value in payload.items():
        if key not in valid_fields:
            continue
        setattr(config, key, value)

    if "crossover" not in payload:
        if "crossover_mode" in payload:
            config.crossover = str(payload["crossover_mode"])
        elif "crossover_method" in payload:
            config.crossover = str(payload["crossover_method"])

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


def clone_config(config: EAConfig) -> EAConfig:
    """Return one validated copy of an existing config object."""
    payload = {
        field_name: deepcopy(getattr(config, field_name))
        for field_name in config.__dataclass_fields__
    }
    return load_config_payload(payload)


def resolve_component_pool_path(config: EAConfig, *, base_dir: str | Path | None = None) -> Path:
    """Resolve the configured component pool path against one base directory or the repo root."""
    configured_path = Path(str(config.component_pool_path))
    if configured_path.is_absolute():
        return configured_path
    if base_dir is not None:
        base_candidate = Path(base_dir).resolve() / configured_path
        if base_candidate.exists():
            return base_candidate
    return PROJECT_ROOT / configured_path


def load_config_from_optional_json(path_or_dir: str | Path | None) -> EAConfig:
    """Load one config file when provided, otherwise fall back to defaults."""
    if path_or_dir is None:
        return EAConfig()
    return load_config_from_json(path_or_dir)
