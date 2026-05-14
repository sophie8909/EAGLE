"""Configuration objects for the current EA pipeline."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from dataclasses import MISSING, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .project import DEFAULT_EVOLUTION_CONFIG_PATH, PROJECT_ROOT


def normalize_algorithm_name(
    algorithm: Any,
    *,
    evaluator: Any = None,
    surrogate: Any = None,
    warn: bool = False,
) -> str:
    """Normalize current algorithm names and explicitly handled legacy aliases."""
    normalized = str(algorithm or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "round_nsga2":
        if warn:
            print("WARNING: round_nsga2 is deprecated; use nsga2. NSGA-II surrogate is removed.", flush=True)
        return "nsga2"
    if normalized == "round_ga":
        evaluator_name = str(evaluator or "").strip().lower().replace("-", "_").replace(" ", "_")
        surrogate_name = str(surrogate or "").strip().lower().replace("-", "_").replace(" ", "_")
        if evaluator_name == "round" or surrogate_name in {"round", "policy_agent", "java_agent"}:
            if warn:
                print("WARNING: round_ga is deprecated; mapped to ga_surrogate.", flush=True)
            return "ga_surrogate"
        if warn:
            print("WARNING: round_ga is deprecated; mapped to ga.", flush=True)
        return "ga"
    return normalized or "nsga2"


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


@dataclass
class EAConfig:
    """Flat configuration surface for all EA, evaluation, and surrogate settings."""
    application: str = "microrts"
    algorithm: str = field(default_factory=lambda: str(_default_config_value("algorithm")))
    evaluator: str = field(default_factory=lambda: str(_default_config_value("evaluator")))
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
    mutation_operator: str = "mix"
    selection_method: str = field(default_factory=lambda: str(_default_config_value("selection_method")))
    parent_selection_operator: str = ""
    tournament_size: int = field(default_factory=lambda: int(_default_config_value("tournament_size")))
    crossover: str = field(default_factory=lambda: str(_default_config_value("crossover")))
    crossover_operator: str = field(default_factory=lambda: str(_default_config_value("crossover_operator")))
    crossover_repair_enabled: bool = field(
        default_factory=lambda: bool(_default_config_value("crossover_repair_enabled"))
    )
    environment_selection_method: str = field(
        default_factory=lambda: str(_default_config_value("environment_selection_method"))
    )
    env_selection_operator: str = ""
    final_test_max_front: int | None = field(default_factory=lambda: _default_config_value("final_test_max_front"))
    include_strategy_identity_in_prompt: bool = field(
        default_factory=lambda: bool(_default_config_value("include_strategy_identity_in_prompt"))
    )
    evolving_prompt_components: list[str] = field(
        default_factory=lambda: list(_default_config_value("evolving_prompt_components"))
    )
    non_evolving_prompt_components: list[str] = field(
        default_factory=lambda: list(_default_config_value("non_evolving_prompt_components"))
    )
    component_pool_path: str = field(default_factory=lambda: str(_default_config_value("component_pool_path")))
    initial_population_seeds: list[dict[str, Any]] = field(
        default_factory=lambda: list(_default_config_value("initial_population_seeds"))
    )

    tick_limit: int = field(default_factory=lambda: int(_default_config_value("tick_limit")))
    llm_call_limit: int = field(default_factory=lambda: int(_default_config_value("llm_call_limit")))
    gameplay_rate: float = field(default_factory=lambda: float(_default_config_value("gameplay_rate")))
    gameplay_refresh_interval: int = field(default_factory=lambda: int(_default_config_value("gameplay_refresh_interval")))
    surrogate_top_ratio: float = field(default_factory=lambda: float(_default_config_value("surrogate_top_ratio")))
    archive_parent_ratio: float = field(default_factory=lambda: float(_default_config_value("archive_parent_ratio")))
    objective_config: dict[str, Any] = field(default_factory=lambda: dict(_default_config_value("objective_config")))
    gameplay_opponents: list[str] = field(default_factory=lambda: list(_default_config_value("gameplay_opponents")))
    gameplay_map_dir: str = field(default_factory=lambda: str(_default_config_value("gameplay_map_dir")))
    llm_interval: list[int] = field(default_factory=lambda: list(_default_config_value("llm_interval")))
    save_trace_on_test: bool = field(default_factory=lambda: bool(_default_config_value("save_trace_on_test")))

    resource_advantage_alpha: float = field(
        default_factory=lambda: float(_default_config_value("resource_advantage_alpha"))
    )
    win_bonus: float = field(
        default_factory=lambda: float(_default_config_value("win_bonus"))
    )
    resource_advantage_weights: dict[str, float] = field(
        default_factory=lambda: dict(_default_config_value("resource_advantage_weights"))
    )

    surrogate_version: str = field(default_factory=lambda: str(_default_config_value("surrogate_version")))
    surrogate: str = field(default_factory=lambda: str(_default_config_value("surrogate")))
    surrogate_recent_match_window: int = field(
        default_factory=lambda: int(_default_config_value("surrogate_recent_match_window"))
    )
    surrogate_round_samples_per_match: int = field(
        default_factory=lambda: int(_default_config_value("surrogate_round_samples_per_match"))
    )
    surrogate_log_dir: str = field(default_factory=lambda: str(_default_config_value("surrogate_log_dir")))
    one_eval_rounds: int = field(default_factory=lambda: int(_default_config_value("one_eval_rounds")))
    round_eval_parallel_workers: int = field(
        default_factory=lambda: int(_default_config_value("round_eval_parallel_workers"))
    )
    agent_eval_parallel_workers: int = field(
        default_factory=lambda: int(_default_config_value("agent_eval_parallel_workers"))
    )
    individual_eval_parallel_workers: int = field(
        default_factory=lambda: int(_default_config_value("individual_eval_parallel_workers"))
    )
    llm_parallel_workers: int = field(default_factory=lambda: int(_default_config_value("llm_parallel_workers")))
    prompt_history_path: str = field(default_factory=lambda: str(_default_config_value("prompt_history_path")))


    def __post_init__(self) -> None:
        """Normalize aliases and validate the config surface eagerly."""
        self._normalize_crossover()
        self.validate()

    def _normalize_crossover(self) -> None:
        """Normalize the single crossover selector used by the active code path."""
        self.crossover = str(self.crossover or "uniform").strip().lower()

    def validate(self) -> None:
        """Validate config values that affect offspring generation behavior."""
        self._normalize_crossover()
        self.application = str(self.application or "microrts").strip().lower()
        self.algorithm = normalize_algorithm_name(
            self.algorithm,
            evaluator=getattr(self, "evaluator", None),
            surrogate=getattr(self, "surrogate", None),
            warn=True,
        )
        self.evaluator = str(self.evaluator or "gameplay").strip().lower()
        if self.evaluator != "gameplay":
            raise ValueError("evaluator must be 'gameplay'.")
        normalized_surrogate = str(self.surrogate).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized_surrogate not in {"round", "policy_agent", "java_agent"}:
            raise ValueError(
                f"Unsupported surrogate backend: {self.surrogate!r}. "
                "Use 'round', 'policy_agent', or 'java_agent'."
            )
        self.surrogate = normalized_surrogate
        algorithm_name = str(self.algorithm or "").strip().lower()
        if algorithm_name not in {"ga", "nsga2", "ga_surrogate"}:
            raise ValueError("algorithm must be one of: ga, nsga2, ga_surrogate.")
        single_objective_algorithm = algorithm_name in {"ga", "ga_surrogate"}
        self.parent_selection_operator = self._normalized_parent_selection_operator(
            self.parent_selection_operator,
            single_objective_algorithm,
        )
        self.env_selection_operator = self._normalized_env_selection_operator(
            self.env_selection_operator,
            single_objective_algorithm,
        )
        if self.objective_config == _default_config_value("objective_config"):
            from eagle.objectives.registry import default_objective_config

            self.objective_config = default_objective_config(self)
        from eagle.objectives.registry import validate_objective_config

        self.objective_config = validate_objective_config(self)
        objective_mode = str(self.objective_config.get("mode", "")).strip().lower()
        if single_objective_algorithm and objective_mode not in {"single", "weighted_mix"}:
            from eagle.objectives.registry import default_objective_config

            self.objective_config = default_objective_config(self)
            objective_mode = str(self.objective_config.get("mode", "")).strip().lower()
        if single_objective_algorithm and objective_mode not in {"single", "weighted_mix"}:
            raise ValueError("Single-objective algorithms require objective_config.mode single or weighted_mix.")
        if not single_objective_algorithm and objective_mode != "multi":
            raise ValueError("Multi-objective algorithms require objective_config.mode multi.")

        if self.reflection_max_components_to_rewrite < 1:
            raise ValueError("reflection_max_components_to_rewrite must be >= 1.")
        self.gameplay_refresh_interval = max(1, int(self.gameplay_refresh_interval))
        self.one_eval_rounds = max(1, int(self.one_eval_rounds))
        self.round_eval_parallel_workers = max(1, int(self.round_eval_parallel_workers))
        self.agent_eval_parallel_workers = max(1, int(self.agent_eval_parallel_workers))
        self.individual_eval_parallel_workers = max(1, int(self.individual_eval_parallel_workers))
        self.llm_parallel_workers = max(1, int(self.llm_parallel_workers))
        self.surrogate_top_ratio = min(1.0, max(0.0, float(self.surrogate_top_ratio)))
        self.archive_parent_ratio = min(1.0, max(0.0, float(self.archive_parent_ratio)))

        if not isinstance(self.evolving_prompt_components, list):
            raise ValueError("evolving_prompt_components must be a list of component keys.")
        self.evolving_prompt_components = [str(key) for key in self.evolving_prompt_components]
        if not isinstance(self.non_evolving_prompt_components, list):
            raise ValueError("non_evolving_prompt_components must be a list of component keys.")
        self.non_evolving_prompt_components = [str(key) for key in self.non_evolving_prompt_components]
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
        if all(value <= 0.0 for value in strategy_mutation.values()):
            raise ValueError("strategy_mutation must leave at least one mode enabled.")

        self.strategy_mutation = strategy_mutation

        self.gameplay_map_dir = str(self.gameplay_map_dir or "8x8").strip().strip("/\\")
        if not self.gameplay_map_dir:
            raise ValueError("gameplay_map_dir must be a non-empty maps/ subfolder name.")
        self.tick_limit = max(1, int(self.tick_limit))
        self.llm_call_limit = max(1, int(self.llm_call_limit))
        self.llm_interval = self._normalized_llm_interval_input(self.llm_interval)

    def evolution_settings(self) -> dict[str, object]:
        """Return the subset of fields that control population search behavior."""
        return {
            "algorithm": self.algorithm,
            "evaluator": self.evaluator,
            "population_size": self.population_size,
            "num_generations": self.num_generations,
            "reproduction_operator_probs": dict(self.reproduction_operator_probs),
            "enable_reflection_operator": self.enable_reflection_operator,
            "reflection_max_components_to_rewrite": self.reflection_max_components_to_rewrite,
            "strategy_mutation": dict(self.strategy_mutation),
            "mutation_operator": self.mutation_operator,
            "selection_method": self.selection_method,
            "parent_selection_operator": self.parent_selection_operator,
            "tournament_size": self.tournament_size,
            "crossover": self.crossover,
            "crossover_operator": self.crossover_operator,
            "crossover_repair_enabled": self.crossover_repair_enabled,
            "environment_selection_method": self.environment_selection_method,
            "env_selection_operator": self.env_selection_operator,
            "final_test_max_front": self.final_test_max_front,
            "include_strategy_identity_in_prompt": self.include_strategy_identity_in_prompt,
            "evolving_prompt_components": list(self.evolving_prompt_components),
            "non_evolving_prompt_components": list(self.non_evolving_prompt_components),
            "component_pool_path": self.component_pool_path,
            "initial_population_seeds": deepcopy(self.initial_population_seeds),
            "objective_config": deepcopy(self.objective_config),
            "gameplay_opponents": list(self.gameplay_opponents),
            "gameplay_map_dir": self.gameplay_map_dir,
            "gameplay_refresh_interval": self.gameplay_refresh_interval,
            "surrogate_top_ratio": self.surrogate_top_ratio,
            "archive_parent_ratio": self.archive_parent_ratio,
        }

    def fitness_settings(self) -> dict[str, object]:
        """Return the subset of fields that affect fitness computation only."""
        return {
            "resource_advantage_alpha": self.resource_advantage_alpha,
            "win_bonus": self.win_bonus,
            "resource_advantage_weights": dict(self.resource_advantage_weights),
        }

    def surrogate_settings(self) -> dict[str, object]:
        """Return the subset of fields used by surrogate evaluators."""
        return {
            "surrogate": self.surrogate,
            "gameplay_refresh_interval": self.gameplay_refresh_interval,
            "surrogate_top_ratio": self.surrogate_top_ratio,
            "archive_parent_ratio": self.archive_parent_ratio,
            "surrogate_recent_match_window": self.surrogate_recent_match_window,
            "surrogate_round_samples_per_match": self.surrogate_round_samples_per_match,
            "one_eval_rounds": self.one_eval_rounds,
            "round_eval_parallel_workers": self.round_eval_parallel_workers,
            "agent_eval_parallel_workers": self.agent_eval_parallel_workers,
            "individual_eval_parallel_workers": self.individual_eval_parallel_workers,
            "llm_parallel_workers": self.llm_parallel_workers,
            "surrogate_log_dir": self.surrogate_log_dir,
        }

    def gameplay_count(self, candidate_count: int | None = None) -> int:
        """Convert `gameplay_rate` into an integer evaluation budget."""
        total = candidate_count if candidate_count is not None else self.population_size
        budget = int(total * self.gameplay_rate)
        if self.gameplay_rate > 0 and budget == 0:
            return 1
        return max(0, budget)

    def llm_interval_for_generation(self, generation: int | None) -> int:
        """Return the scheduled LLM interval for one zero-based generation."""
        schedule = self._normalized_llm_interval_input(self.llm_interval)
        if generation is None or generation < 0:
            return schedule[0]
        if self.num_generations <= 0:
            return schedule[-1]
        schedule_index = min(
            len(schedule) - 1,
            max(0, int(generation) * len(schedule) // int(self.num_generations)),
        )
        return schedule[schedule_index]

    def set_active_llm_interval_for_generation(self, generation: int | None) -> int:
        """Select and store the runtime LLM interval for the active generation."""
        interval = self.llm_interval_for_generation(generation)
        self._active_llm_interval = interval
        return interval

    def set_active_llm_interval(self, interval: int | None) -> None:
        """Set or clear an explicit runtime LLM interval override."""
        self._active_llm_interval = None if interval is None else int(interval)

    def active_llm_interval(self) -> int:
        """Return the runtime LLM interval currently used by MicroRTS launches."""
        active_interval = getattr(self, "_active_llm_interval", None)
        if active_interval is not None:
            return int(active_interval)
        return self.llm_interval_for_generation(None)

    def strategy_mutation_mode_weights(self) -> dict[str, float]:
        """Return normalized sampling weights for strategy-mutation dispatch."""
        weights = self._normalized_strategy_mutation_input(self.strategy_mutation)
        total = sum(max(0.0, value) for value in weights.values())
        if total <= 0:
            return {
                "pool_replacement": 1.0,
                "identity_preserving_rewrite": 0.0,
                "identity_shift_rewrite": 0.0,
                "bitmask_flip": 0.0,
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

    @staticmethod
    def _normalized_llm_interval_input(raw_interval: int | list[int] | tuple[int, ...]) -> list[int]:
        """Normalize the LLM interval schedule into a non-empty integer list."""
        if isinstance(raw_interval, (list, tuple)):
            values = [int(value) for value in raw_interval]
        else:
            values = [int(raw_interval)]
        if not values:
            raise ValueError("llm_interval must contain at least one interval value.")
        if any(value < 1 for value in values):
            raise ValueError("All llm_interval values must be >= 1.")
        return values

    @staticmethod
    def _normalized_parent_selection_operator(raw_operator: str | None, single_objective: bool) -> str:
        """Return a parent-selection operator compatible with the algorithm family."""
        operator = str(raw_operator or "").strip()
        if single_objective and operator in {"", "nsga2_tournament"}:
            return "ga_fitness_tournament"
        if not single_objective and operator in {"", "ga_fitness_tournament", "tournament"}:
            return "nsga2_tournament"
        return operator

    @staticmethod
    def _normalized_env_selection_operator(raw_operator: str | None, single_objective: bool) -> str:
        """Return an environment-selection operator compatible with the algorithm family."""
        operator = str(raw_operator or "").strip()
        if single_objective and operator in {"", "nsga2_environmental"}:
            return "ga_fitness_elitism"
        if not single_objective and operator in {"", "ga_fitness_elitism", "elitism"}:
            return "nsga2_environmental"
        return operator


def _config_with_defaults_unvalidated() -> EAConfig:
    """Build an `EAConfig` with default field values without eager validation."""
    config = object.__new__(EAConfig)
    for field_name, field_info in EAConfig.__dataclass_fields__.items():
        if field_info.default is not MISSING:
            value = deepcopy(field_info.default)
        elif field_info.default_factory is not MISSING:
            value = field_info.default_factory()
        else:
            value = None
        setattr(config, field_name, value)
    return config


def load_config_payload(payload: dict[str, Any] | None, *, validate: bool = True) -> EAConfig:
    """Build one validated config from a JSON-like payload."""
    payload = dict(payload or {})
    if "objective_config" not in payload and "objective_operator" in payload:
        payload["objective_config"] = {
            "mode": "single",
            "objective": str(payload["objective_operator"]),
        }
    if "objective_config" not in payload and "objective" in payload:
        payload["objective_config"] = {
            "mode": "single",
            "objective": str(payload["objective"]),
        }
    config = _config_with_defaults_unvalidated()
    valid_fields = set(config.__dataclass_fields__.keys())

    for key, value in payload.items():
        if key not in valid_fields:
            continue
        setattr(config, key, value)

    if validate:
        config.validate()
    return config


def load_config_from_json(path_or_dir: str | Path, *, validate: bool = True) -> EAConfig:
    """Load a saved config file or run directory into a validated `EAConfig`."""
    candidate_path = Path(path_or_dir)
    config_path = candidate_path / "config.json" if candidate_path.is_dir() else candidate_path
    if not config_path.exists():
        return EAConfig()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return load_config_payload(payload, validate=validate)


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
