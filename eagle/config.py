"""Configuration objects for the current EA pipeline."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from dataclasses import MISSING, asdict, dataclass, field, fields
from functools import lru_cache
from pathlib import Path
from typing import Any

from eagle.core.config import algorithm_default_config, algorithm_objective_mode, is_surrogate_algorithm, plugin_names

from .project import DEFAULT_EVOLUTION_CONFIG_PATH, EAGLE_LOGS_DIR, MICRORTS_ROOT, PROJECT_ROOT

LEGACY_CONFIG_FILENAME = "config.json"
RESOLVED_CONFIG_FILENAME = "config.resolved.json"

AGENT_CLASS_CHOICES = {
    "ai.eagle.EAGLE",
    "ai.eagle.EAGLERepair",
}
DEFAULT_AGENT_CLASS = "ai.eagle.EAGLE"


@dataclass(frozen=True)
class ExperimentSection:
    """User-facing experiment settings derived from the canonical config."""

    run_name: str | None
    seed: int | None
    mode: str
    generations: int
    population_size: int
    resume_run: str | None


@dataclass(frozen=True)
class AlgorithmSection:
    """Algorithm, objective, and operator settings."""

    algorithm_name: str
    objective_mode: str
    objectives: dict[str, Any]
    selection: dict[str, Any]
    mutation: dict[str, Any]
    crossover: dict[str, Any]
    reflection: dict[str, Any]
    surrogate: dict[str, Any]
    adaptive_operator_selection: dict[str, Any]


@dataclass(frozen=True)
class LLMSection:
    """LLM runtime settings currently used by EAGLE."""

    provider: str
    model: str
    base_url: str
    api_key_env_var: str | None
    temperature: float | None
    max_tokens: int | None
    call_limit: int
    trace_enabled: bool
    round_eval_model: str


@dataclass(frozen=True)
class EvaluationSection:
    """Evaluation backend and final-test settings."""

    backend: str
    evaluator: str
    eval_mode: str
    gameplay_rate: float
    real_eval_opponents: list[str]
    surrogate_eval_games: int
    final_test: dict[str, Any]
    early_end: dict[str, Any]


@dataclass(frozen=True)
class MicroRTSSection:
    """MicroRTS backend settings, present only when the backend is active."""

    enabled: bool
    root: str
    java_classpath: str | None
    compile_root: str
    map_selection: str
    opponent_selection: list[str]
    max_cycles: int
    server_port: int | None
    llm_interval: list[int]
    agent_class: str
    skip_same_behavior_state: bool
    save_trace_on_test: bool


@dataclass(frozen=True)
class ComponentsSection:
    """Prompt component and few-shot example settings."""

    prompt_components_path: str
    examples_path: str
    enabled_components: list[str]
    evolving_components: list[str]
    few_shot: dict[str, Any]


@dataclass(frozen=True)
class LoggingSection:
    """Resolved run artifact paths."""

    log_root: str
    run_dir: str | None
    checkpoint_dir: str | None
    llm_trace_dir: str | None
    analysis_dir: str | None
    microrts_log_dir: str


@dataclass(frozen=True)
class ConfigSections:
    """Sectioned view of the canonical flat EAGLE config."""

    experiment: ExperimentSection
    algorithm: AlgorithmSection
    llm: LLMSection
    evaluation: EvaluationSection
    microrts: MicroRTSSection
    components: ComponentsSection
    logging: LoggingSection


def normalize_algorithm_name(
    algorithm: Any,
    *,
    evaluator: Any = None,
    surrogate: Any = None,
    warn: bool = False,
) -> str:
    """Normalize one current algorithm key from config or CLI input.

    Args:
        algorithm: Raw algorithm name from JSON/YAML config or command-line arguments.
        evaluator: Unused; retained only because existing call sites pass the active evaluator.
        surrogate: Unused; retained only because existing call sites pass the active surrogate.
        warn: Unused; old-name warning support was removed with legacy aliases.

    Returns:
        The normalized current algorithm key. Only spelling/case separators are normalized;
        old algorithm names are intentionally not mapped to current names.
    """
    del evaluator, surrogate, warn
    normalized = str(algorithm or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or "nsga2"


def normalize_agent_class(agent_class: Any) -> str:
    """Normalize the selectable MicroRTS LLM Java agent class."""
    selected = str(agent_class or "").strip()
    return selected if selected in AGENT_CLASS_CHOICES else DEFAULT_AGENT_CLASS


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """Normalize JSON, form, and environment-style boolean values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


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
    eval_mode: str = "full_game"
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
    mutation_selection_mode: str = field(default_factory=lambda: str(_default_config_value("mutation_selection_mode")))
    example_reproduction_operator_probs: dict[str, float] = field(
        default_factory=lambda: dict(_default_config_value("example_reproduction_operator_probs"))
    )
    example_mutation_source_probs: dict[str, float] = field(
        default_factory=lambda: dict(_default_config_value("example_mutation_source_probs"))
    )
    mutation_operator: str = "mix"
    reflection_operator: str = "round_reflection"
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
    fitness_metric: str = field(default_factory=lambda: str(_default_config_value("fitness_metric")))
    agent_class: str = field(default_factory=lambda: str(_default_config_value("agent_class")))
    skip_same_behavior_state: bool = field(
        default_factory=lambda: bool(_default_config_value("skip_same_behavior_state"))
    )
    llm_model: str = field(default_factory=lambda: str(_default_config_value("llm_model")))
    llm_base_url: str = field(default_factory=lambda: str(_default_config_value("llm_base_url")))
    gameplay_rate: float = field(default_factory=lambda: float(_default_config_value("gameplay_rate")))
    gameplay_refresh_interval: int = field(default_factory=lambda: int(_default_config_value("gameplay_refresh_interval")))
    surrogate_llm_call_limit: int = field(default_factory=lambda: int(_default_config_value("surrogate_llm_call_limit")))
    surrogate_top_ratio: float = field(default_factory=lambda: float(_default_config_value("surrogate_top_ratio")))
    archive_parent_ratio: float = field(default_factory=lambda: float(_default_config_value("archive_parent_ratio")))
    min_token_length: int = field(default_factory=lambda: int(_default_config_value("min_token_length")))
    objective_config: dict[str, Any] = field(default_factory=lambda: dict(_default_config_value("objective_config")))
    aggressiveness_objective_enabled: bool = field(
        default_factory=lambda: bool(_default_config_value("aggressiveness_objective_enabled"))
    )
    aggressiveness_mode: str = field(default_factory=lambda: str(_default_config_value("aggressiveness_mode")))
    aggressiveness_llm_weight: float = field(
        default_factory=lambda: float(_default_config_value("aggressiveness_llm_weight"))
    )
    aggressiveness_component_weight: float = field(
        default_factory=lambda: float(_default_config_value("aggressiveness_component_weight"))
    )
    aggressiveness_judge_model: str = field(
        default_factory=lambda: str(_default_config_value("aggressiveness_judge_model"))
    )
    aggressiveness_judge_temperature: float = field(
        default_factory=lambda: float(_default_config_value("aggressiveness_judge_temperature"))
    )
    training_example_sample_count: str | int = field(
        default_factory=lambda: _default_config_value("training_example_sample_count")
    )
    training_example_fixed_count: bool = field(
        default_factory=lambda: bool(_default_config_value("training_example_fixed_count"))
    )
    use_few_shot_examples: bool = field(default_factory=lambda: bool(_default_config_value("use_few_shot_examples")))
    min_examples: int = field(default_factory=lambda: int(_default_config_value("min_examples")))
    max_examples: int = field(default_factory=lambda: int(_default_config_value("max_examples")))
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
    round_eval_model: str = field(default_factory=lambda: str(_default_config_value("round_eval_model")))
    round_state_seed: int | None = field(default_factory=lambda: _default_config_value("round_state_seed"))
    surrogate_log_dir: str = field(default_factory=lambda: str(_default_config_value("surrogate_log_dir")))
    one_eval_rounds: int = field(default_factory=lambda: int(_default_config_value("one_eval_rounds")))
    prompt_history_path: str = field(default_factory=lambda: str(_default_config_value("prompt_history_path")))


    def __post_init__(self) -> None:
        """Normalize current selectors and validate the config surface eagerly."""
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
        self.eval_mode = str(self.eval_mode or "full_game").strip().lower()
        if self.eval_mode == "gameplay":
            self.eval_mode = "full_game"
        if self.eval_mode not in {"full_game", "early_end", "java_surrogate", "round"}:
            raise ValueError("eval_mode must be 'full_game', 'early_end', 'java_surrogate', or 'round'.")
        normalized_surrogate = str(self.surrogate).strip().lower().replace("-", "_").replace(" ", "_")
        surrogate_names = set(plugin_names("surrogate", application=self.application))
        if normalized_surrogate not in surrogate_names:
            raise ValueError(f"surrogate must be one of: {', '.join(sorted(surrogate_names))}.")
        self.surrogate = normalized_surrogate
        algorithm_name = str(self.algorithm or "").strip().lower()
        algorithm_names = set(plugin_names("algorithm", application=self.application))
        if algorithm_name not in algorithm_names:
            raise ValueError(f"algorithm must be one of: {', '.join(sorted(algorithm_names))}.")
        if self.surrogate == "none" and is_surrogate_algorithm(algorithm_name, application=self.application):
            defaults = algorithm_default_config(algorithm_name, application=self.application)
            self.surrogate = str(defaults.get("surrogate", "early_end"))
        objective_mode_support = algorithm_objective_mode(algorithm_name, application=self.application)
        single_objective_algorithm = objective_mode_support == "SO"
        multi_objective_algorithm = objective_mode_support == "MO"
        self.parent_selection_operator = self._normalized_parent_selection_operator(
            self.parent_selection_operator,
            single_objective_algorithm,
        )
        self.env_selection_operator = self._normalized_env_selection_operator(
            self.env_selection_operator,
            single_objective_algorithm,
        )
        self.parent_selection_operator = self._normalized_registered_operator(
            self.parent_selection_operator,
            "parent_selection",
            "ga_fitness_tournament" if single_objective_algorithm else "nsga2_tournament",
        )
        self.env_selection_operator = self._normalized_registered_operator(
            self.env_selection_operator,
            "env_selection",
            "ga_fitness_elitism" if single_objective_algorithm else "nsga2_environmental",
        )
        self.crossover_operator = self._normalized_registered_operator(
            self.crossover_operator,
            "crossover",
            "uniform",
        )
        self.mutation_operator = self._normalized_registered_operator(
            self.mutation_operator,
            "mutation",
            "mix",
        )
        self.reflection_operator = self._normalized_registered_operator(
            self.reflection_operator,
            "reflection",
            "round_reflection",
        )
        from eagle.objectives.registry import validate_objective_config

        self.objective_config = validate_objective_config(self)
        objective_mode = str(self.objective_config.get("mode", "")).strip().lower()
        if single_objective_algorithm and objective_mode != "single":
            selected_objectives = (
                list(self.objective_config.get("objectives", []))
                if objective_mode == "multi"
                else list(dict(self.objective_config.get("weights", {})).keys())
            )
            if selected_objectives:
                self.objective_config = {"mode": "single", "objective": selected_objectives[0]}
            else:
                from eagle.objectives.registry import default_objective_config

                self.objective_config = default_objective_config(self)
            objective_mode = str(self.objective_config.get("mode", "")).strip().lower()
        if single_objective_algorithm and objective_mode != "single":
            raise ValueError("Single-objective algorithms require objective_config.mode single.")
        if multi_objective_algorithm and objective_mode != "multi":
            raise ValueError("Multi-objective algorithms require objective_config.mode multi.")
        self.aggressiveness_objective_enabled = bool(self.aggressiveness_objective_enabled)
        self.aggressiveness_mode = str(self.aggressiveness_mode or "hybrid").strip().lower()
        if self.aggressiveness_mode not in {"component_only", "llm_only", "hybrid"}:
            raise ValueError("aggressiveness_mode must be component_only, llm_only, or hybrid.")
        self.aggressiveness_component_weight = min(1.0, max(0.0, float(self.aggressiveness_component_weight)))
        self.aggressiveness_llm_weight = min(1.0, max(0.0, float(self.aggressiveness_llm_weight)))
        self.aggressiveness_judge_model = str(self.aggressiveness_judge_model or self.llm_model or "local").strip()
        if not self.aggressiveness_judge_model:
            raise ValueError("aggressiveness_judge_model must be a non-empty model name.")
        self.aggressiveness_judge_temperature = min(
            1.0,
            max(0.0, float(self.aggressiveness_judge_temperature)),
        )
        if self.aggressiveness_objective_enabled and not single_objective_algorithm:
            objectives = list(self.objective_config.get("objectives", []))
            if "strategic_aggressiveness" not in objectives:
                objectives.append("strategic_aggressiveness")
            self.objective_config = {"mode": "multi", "objectives": objectives}

        if self.reflection_max_components_to_rewrite < 1:
            raise ValueError("reflection_max_components_to_rewrite must be >= 1.")
        self.gameplay_refresh_interval = max(1, int(self.gameplay_refresh_interval))
        self.one_eval_rounds = max(1, int(self.one_eval_rounds))
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
        self.mutation_selection_mode = str(self.mutation_selection_mode or "fixed").strip().lower()
        if self.mutation_selection_mode not in {"fixed", "aos"}:
            raise ValueError("mutation_selection_mode must be 'fixed' or 'aos'.")
        example_probabilities = self._normalized_probability_input(self.example_reproduction_operator_probs)
        expected_example_keys = {"crossover", "mutation"}
        actual_example_keys = set(example_probabilities.keys())
        if actual_example_keys != expected_example_keys:
            raise ValueError(
                "example_reproduction_operator_probs must define exactly "
                f"{sorted(expected_example_keys)}, got {sorted(actual_example_keys)}."
            )
        example_total = sum(example_probabilities.values())
        if example_total <= 0:
            raise ValueError("example_reproduction_operator_probs must have a positive total weight.")
        if any(value < 0 for value in example_probabilities.values()):
            raise ValueError("example_reproduction_operator_probs values must be >= 0.")
        self.example_reproduction_operator_probs = {
            key: value / example_total
            for key, value in example_probabilities.items()
        }
        self.example_mutation_source_probs = self._normalized_exact_probability_map(
            self.example_mutation_source_probs,
            expected_keys={"fresh", "pool"},
            field_name="example_mutation_source_probs",
        )

        self.surrogate_round_samples_per_match = max(1, int(self.surrogate_round_samples_per_match))
        self.round_eval_model = str(self.round_eval_model or "").strip()
        if not self.round_eval_model:
            raise ValueError("round_eval_model must be a non-empty model name.")
        self.round_state_seed = None if self.round_state_seed is None else int(self.round_state_seed)
        self.gameplay_map_dir = str(self.gameplay_map_dir or "8x8").strip().strip("/\\")
        if not self.gameplay_map_dir:
            raise ValueError("gameplay_map_dir must be a non-empty maps/ subfolder name.")
        self.tick_limit = max(1, int(self.tick_limit))
        self.llm_call_limit = max(1, int(self.llm_call_limit))
        self.fitness_metric = str(self.fitness_metric or "default").strip()
        self.agent_class = normalize_agent_class(self.agent_class)
        self.skip_same_behavior_state = normalize_bool(self.skip_same_behavior_state, default=True)
        self.llm_model = str(self.llm_model or "").strip()
        if not self.llm_model:
            raise ValueError("llm_model must be a non-empty model name.")
        self.llm_base_url = self._normalize_llm_base_url(self.llm_base_url)
        self.surrogate_llm_call_limit = max(1, int(self.surrogate_llm_call_limit))
        self.min_token_length = max(1, int(self.min_token_length))
        self.llm_interval = self._normalized_llm_interval_input(self.llm_interval)
        self.use_few_shot_examples = bool(self.use_few_shot_examples)
        self.min_examples = max(0, int(self.min_examples))
        self.max_examples = int(self.max_examples)
        if self.max_examples < self.min_examples:
            raise ValueError("max_examples must be >= min_examples.")

    def evolution_settings(self) -> dict[str, object]:
        """Return the subset of fields that control population search behavior."""
        return {
            "algorithm": self.algorithm,
            "evaluator": self.evaluator,
            "eval_mode": self.eval_mode,
            "population_size": self.population_size,
            "num_generations": self.num_generations,
            "reproduction_operator_probs": dict(self.reproduction_operator_probs),
            "example_reproduction_operator_probs": dict(self.example_reproduction_operator_probs),
            "example_mutation_source_probs": dict(self.example_mutation_source_probs),
            "enable_reflection_operator": self.enable_reflection_operator,
            "reflection_max_components_to_rewrite": self.reflection_max_components_to_rewrite,
            "strategy_mutation": dict(self.strategy_mutation),
            "mutation_selection_mode": self.mutation_selection_mode,
            "mutation_operator": self.mutation_operator,
            "reflection_operator": self.reflection_operator,
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
            "fitness_metric": self.fitness_metric,
            "agent_class": self.agent_class,
            "skip_same_behavior_state": self.skip_same_behavior_state,
            "aggressiveness_objective_enabled": self.aggressiveness_objective_enabled,
            "aggressiveness_mode": self.aggressiveness_mode,
            "aggressiveness_llm_weight": self.aggressiveness_llm_weight,
            "aggressiveness_component_weight": self.aggressiveness_component_weight,
            "aggressiveness_judge_model": self.aggressiveness_judge_model,
            "aggressiveness_judge_temperature": self.aggressiveness_judge_temperature,
            "use_few_shot_examples": self.use_few_shot_examples,
            "min_examples": self.min_examples,
            "max_examples": self.max_examples,
            "gameplay_opponents": list(self.gameplay_opponents),
            "gameplay_map_dir": self.gameplay_map_dir,
            "gameplay_refresh_interval": self.gameplay_refresh_interval,
            "surrogate_llm_call_limit": self.surrogate_llm_call_limit,
            "surrogate_top_ratio": self.surrogate_top_ratio,
            "archive_parent_ratio": self.archive_parent_ratio,
        }

    def fitness_settings(self) -> dict[str, object]:
        """Return the subset of fields that affect fitness computation only."""
        return {
            "resource_advantage_alpha": self.resource_advantage_alpha,
            "win_bonus": self.win_bonus,
            "resource_advantage_weights": dict(self.resource_advantage_weights),
            "min_token_length": self.min_token_length,
            "aggressiveness_objective_enabled": self.aggressiveness_objective_enabled,
            "aggressiveness_mode": self.aggressiveness_mode,
            "aggressiveness_llm_weight": self.aggressiveness_llm_weight,
            "aggressiveness_component_weight": self.aggressiveness_component_weight,
            "aggressiveness_judge_model": self.aggressiveness_judge_model,
            "aggressiveness_judge_temperature": self.aggressiveness_judge_temperature,
        }

    def surrogate_settings(self) -> dict[str, object]:
        """Return the subset of fields used by surrogate evaluators."""
        return {
            "surrogate": self.surrogate,
            "gameplay_refresh_interval": self.gameplay_refresh_interval,
            "surrogate_llm_call_limit": self.surrogate_llm_call_limit,
            "surrogate_top_ratio": self.surrogate_top_ratio,
            "archive_parent_ratio": self.archive_parent_ratio,
            "surrogate_recent_match_window": self.surrogate_recent_match_window,
            "surrogate_round_samples_per_match": self.surrogate_round_samples_per_match,
            "round_eval_model": self.round_eval_model,
            "round_state_seed": self.round_state_seed,
            "one_eval_rounds": self.one_eval_rounds,
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

    @staticmethod
    def _normalize_llm_base_url(raw_url: Any) -> str:
        """Normalize the OpenAI-compatible LLM API base URL."""
        base_url = str(raw_url or "http://127.0.0.1:8080/v1").strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        return base_url

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

    @classmethod
    def _normalized_exact_probability_map(
        cls,
        raw_probabilities: dict[str, float] | None,
        *,
        expected_keys: set[str],
        field_name: str,
    ) -> dict[str, float]:
        """Validate and normalize a named probability map."""
        probabilities = cls._normalized_probability_input(raw_probabilities)
        actual_keys = set(probabilities.keys())
        if actual_keys != expected_keys:
            raise ValueError(
                f"{field_name} must define exactly {sorted(expected_keys)}, got {sorted(actual_keys)}."
            )
        if any(value < 0 for value in probabilities.values()):
            raise ValueError(f"{field_name} values must be >= 0.")
        total = sum(probabilities.values())
        if total <= 0:
            raise ValueError(f"{field_name} must have a positive total weight.")
        return {key: value / total for key, value in probabilities.items()}

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

    @staticmethod
    def _normalized_registered_operator(raw_operator: str | None, operator_type: str, default: str) -> str:
        """Return a selected operator after validating it against the operator registry."""
        from eagle.operators.registry import list_operator_names

        operator = str(raw_operator or default).strip().lower().replace("-", "_").replace(" ", "_")
        choices = set(list_operator_names(operator_type))
        if operator not in choices:
            raise ValueError(
                f"{operator_type}_operator must be one of: {', '.join(sorted(choices))}."
            )
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
    """Build one config from a current-schema JSON-like payload.

    Args:
        payload: Mapping loaded from a current EAGLE config file.
        validate: When true, normalize and validate the resulting config before returning.

    Returns:
        An `EAConfig` populated from current-schema fields.

    Raises:
        ValueError: If the payload contains fields that are not part of `EAConfig`.
    """
    payload = _ea_payload_from_config_mapping(payload)
    config = _config_with_defaults_unvalidated()
    valid_fields = set(config.__dataclass_fields__.keys())
    unknown_fields = sorted(key for key in payload if key not in valid_fields)
    if unknown_fields:
        raise ValueError(
            "Unknown config fields are not accepted: "
            f"{', '.join(unknown_fields)}."
        )

    for key, value in payload.items():
        setattr(config, key, value)

    if validate:
        config.validate()
    return config


def config_to_payload(config: EAConfig) -> dict[str, Any]:
    """Serialize one `EAConfig` to the canonical flat config payload."""
    return {
        field_info.name: deepcopy(getattr(config, field_info.name))
        for field_info in fields(EAConfig)
    }


def config_to_sections(
    config: EAConfig,
    *,
    run_dir: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> ConfigSections:
    """Return typed section views over the canonical flat config.

    `EAConfig` remains the source of truth for persistence and runtime behavior.
    These sections give GUI, analysis, and plugin-facing code stable boundaries
    without introducing another writable config schema.
    """
    objective_mode = _objective_mode_from_config(config)
    run_path = Path(run_dir).expanduser().resolve() if run_dir is not None else None
    component_path = serialize_config_path(resolve_component_pool_path(config, base_dir=base_dir))
    examples_path = serialize_config_path(Path(component_path).with_name("examples_pool.jsonl"))
    microrts_root = serialize_config_path(MICRORTS_ROOT)
    return ConfigSections(
        experiment=ExperimentSection(
            run_name=run_path.name if run_path is not None else None,
            seed=None,
            mode=objective_mode,
            generations=int(config.num_generations),
            population_size=int(config.population_size),
            resume_run=str(run_path) if run_path is not None else None,
        ),
        algorithm=AlgorithmSection(
            algorithm_name=str(config.algorithm),
            objective_mode=objective_mode,
            objectives=deepcopy(config.objective_config),
            selection={
                "method": config.selection_method,
                "parent_selection_operator": config.parent_selection_operator,
                "environment_selection_method": config.environment_selection_method,
                "env_selection_operator": config.env_selection_operator,
                "tournament_size": config.tournament_size,
            },
            mutation={
                "operator": config.mutation_operator,
                "selection_mode": config.mutation_selection_mode,
                "strategy_mutation": dict(config.strategy_mutation),
            },
            crossover={
                "name": config.crossover,
                "operator": config.crossover_operator,
                "repair_enabled": bool(config.crossover_repair_enabled),
            },
            reflection={
                "operator": config.reflection_operator,
                "enabled": bool(config.enable_reflection_operator),
                "max_components_to_rewrite": int(config.reflection_max_components_to_rewrite),
            },
            surrogate={
                "mode": config.surrogate,
                "top_ratio": float(config.surrogate_top_ratio),
                "archive_parent_ratio": float(config.archive_parent_ratio),
                "recent_match_window": int(config.surrogate_recent_match_window),
            },
            adaptive_operator_selection={
                "enabled": config.mutation_selection_mode == "aos",
                "mutation_selection_mode": config.mutation_selection_mode,
            },
        ),
        llm=LLMSection(
            provider="openai_compatible",
            model=config.llm_model,
            base_url=config.llm_base_url,
            api_key_env_var=None,
            temperature=None,
            max_tokens=None,
            call_limit=int(config.llm_call_limit),
            trace_enabled=bool(config.save_trace_on_test),
            round_eval_model=config.round_eval_model,
        ),
        evaluation=EvaluationSection(
            backend=config.application,
            evaluator=config.evaluator,
            eval_mode=config.eval_mode,
            gameplay_rate=float(config.gameplay_rate),
            real_eval_opponents=list(config.gameplay_opponents),
            surrogate_eval_games=int(config.surrogate_round_samples_per_match),
            final_test={"max_front": config.final_test_max_front},
            early_end={
                "one_eval_rounds": int(config.one_eval_rounds),
                "gameplay_refresh_interval": int(config.gameplay_refresh_interval),
            },
        ),
        microrts=MicroRTSSection(
            enabled=config.application == "microrts",
            root=microrts_root,
            java_classpath=None,
            compile_root=microrts_root,
            map_selection=config.gameplay_map_dir,
            opponent_selection=list(config.gameplay_opponents),
            max_cycles=int(config.tick_limit),
            server_port=None,
            llm_interval=list(config.llm_interval),
            agent_class=config.agent_class,
            skip_same_behavior_state=bool(config.skip_same_behavior_state),
            save_trace_on_test=bool(config.save_trace_on_test),
        ),
        components=ComponentsSection(
            prompt_components_path=component_path,
            examples_path=examples_path,
            enabled_components=list(config.evolving_prompt_components) + list(config.non_evolving_prompt_components),
            evolving_components=list(config.evolving_prompt_components),
            few_shot={
                "enabled": bool(config.use_few_shot_examples),
                "min_examples": int(config.min_examples),
                "max_examples": int(config.max_examples),
                "training_example_sample_count": deepcopy(config.training_example_sample_count),
                "training_example_fixed_count": bool(config.training_example_fixed_count),
            },
        ),
        logging=LoggingSection(
            log_root=serialize_config_path(EAGLE_LOGS_DIR),
            run_dir=str(run_path) if run_path is not None else None,
            checkpoint_dir=str(run_path) if run_path is not None else None,
            llm_trace_dir=str(run_path / "llm_calls") if run_path is not None else None,
            analysis_dir=str(run_path / "analysis") if run_path is not None else None,
            microrts_log_dir=config.surrogate_log_dir,
        ),
    )


def config_to_section_payload(
    config: EAConfig,
    *,
    run_dir: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Serialize the sectioned config view to a JSON-like mapping."""
    return asdict(config_to_sections(config, run_dir=run_dir, base_dir=base_dir))


def _objective_mode_from_config(config: EAConfig) -> str:
    """Return `single` or `multi` from objective config, falling back to algorithm metadata."""
    raw_mode = str(dict(config.objective_config or {}).get("mode") or "").strip().lower()
    if raw_mode == "single":
        return "single"
    if raw_mode in {"multi", "weighted_mix"}:
        return "multi"
    plugin_mode = algorithm_objective_mode(config.algorithm, application=config.application)
    return "single" if plugin_mode == "SO" else "multi"


def resolve_config_path(path_text: str | Path, *, base_dir: str | Path | None = None) -> Path:
    """Resolve a config-owned path against its config directory or the repo root."""
    raw_path = Path(path_text)
    if raw_path.is_absolute():
        return raw_path.resolve()
    if base_dir is not None:
        base_candidate = Path(base_dir).resolve() / raw_path
        if base_candidate.exists():
            return base_candidate.resolve()
    return (PROJECT_ROOT / raw_path).resolve()


def serialize_config_path(path: str | Path) -> str:
    """Return a stable repo-relative path when possible, otherwise an absolute path."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_config(config: EAConfig, *, base_dir: str | Path | None = None) -> EAConfig:
    """Return a validated config with config-owned paths normalized."""
    resolved = clone_config(config)
    resolved.component_pool_path = serialize_config_path(
        resolve_component_pool_path(resolved, base_dir=base_dir)
    )
    for field_name in ("surrogate_log_dir", "prompt_history_path"):
        raw_value = str(getattr(resolved, field_name, "") or "").strip()
        if raw_value:
            setattr(
                resolved,
                field_name,
                serialize_config_path(resolve_config_path(raw_value, base_dir=base_dir)),
            )
    resolved.validate()
    return resolved


def load_config_from_json(path_or_dir: str | Path, *, validate: bool = True) -> EAConfig:
    """Load a saved config file or run directory into a validated `EAConfig`."""
    config_path = select_config_path(path_or_dir)
    if not config_path.exists():
        return EAConfig()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return load_config_payload(payload, validate=validate)


def load_resume_config(run_dir: str | Path, *, validate: bool = True) -> EAConfig:
    """Load the resolved config from an existing run directory without mutating it."""
    run_path = Path(run_dir)
    if not run_path.exists() or not run_path.is_dir():
        raise FileNotFoundError(f"Resume run directory not found: {run_path}")
    config_path = select_config_path(run_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Resume run is missing a config file: {run_path}")
    return load_config_from_json(run_path, validate=validate)


def select_config_path(path_or_dir: str | Path, *, prefer_resolved: bool = True) -> Path:
    """Return the config file to read, preferring resolved run configs."""
    candidate_path = Path(path_or_dir)
    if candidate_path.is_dir():
        if prefer_resolved:
            resolved_path = candidate_path / RESOLVED_CONFIG_FILENAME
            if resolved_path.exists():
                return resolved_path
        return candidate_path / LEGACY_CONFIG_FILENAME
    if prefer_resolved and candidate_path.name == LEGACY_CONFIG_FILENAME:
        resolved_path = candidate_path.with_name(RESOLVED_CONFIG_FILENAME)
        if resolved_path.exists():
            return resolved_path
    return candidate_path


def save_resolved_config(
    config: EAConfig,
    run_dir: str | Path,
    *,
    base_dir: str | Path | None = None,
    write_legacy: bool = True,
) -> Path:
    """Save the resolved run config and optionally refresh the legacy filename."""
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    resolved_config = resolve_config(config, base_dir=base_dir)
    payload = config_to_payload(resolved_config)
    resolved_path = run_path / RESOLVED_CONFIG_FILENAME
    resolved_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    if write_legacy:
        (run_path / LEGACY_CONFIG_FILENAME).write_text(json.dumps(payload, indent=4), encoding="utf-8")
    return resolved_path


def clone_config(config: EAConfig) -> EAConfig:
    """Return one validated copy of an existing config object."""
    return load_config_payload(config_to_payload(config))


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


def _ea_payload_from_config_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Convert the most recent old experiment envelope into the flat EA payload."""
    data = dict(payload or {})
    if "llm_intervals" in data and "llm_interval" not in data:
        data["llm_interval"] = data.pop("llm_intervals")
    ea_payload = data.get("ea")
    if not isinstance(ea_payload, dict):
        return data
    flat = dict(ea_payload)
    if "llm_intervals" in flat and "llm_interval" not in flat:
        flat["llm_interval"] = flat.pop("llm_intervals")
    for key in ("algorithm", "evaluator", "eval_mode", "surrogate", "application", "llm_interval"):
        if key in data and key not in flat:
            flat[key] = data[key]
    if "opponents" in data and "gameplay_opponents" not in flat:
        flat["gameplay_opponents"] = data["opponents"]
    return flat
