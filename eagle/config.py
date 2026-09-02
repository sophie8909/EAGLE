"""Experiment configuration for the generated-agent EAGLE pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from generation.agent_template import (
    DEFAULT_AGENT_TEMPLATE_PATH,
    DEFAULT_INITIAL_JAVA_SEED_PATH,
)

from .candidate import DEFAULT_GENERATION_PROMPT
from .aos import ReflectionOperatorMode, ReflectionOperatorSettings
from .opponent_cases import LEXICASE_CASES, OPPONENT_WEIGHTS, OPPONENT_WEIGHT_SUM
from .prompts import DEFAULT_PROMPT_DIR


DEFAULT_EVALUATION_MAPS = (
    "maps/8x8/basesWorkers8x8.xml",
    "maps/16x16/basesWorkers16x16.xml",
    "maps/24x24/basesWorkers24x24.xml",
)
DEFAULT_SEED_POLICY_PATH = Path(__file__).resolve().parents[1] / "seeds" / "blank_policy.txt"
DEFAULT_SEARCH_OPPONENTS = tuple((case, OPPONENT_WEIGHTS[case]) for case in LEXICASE_CASES)
FIXED_OPPONENT_WEIGHT_SUM = OPPONENT_WEIGHT_SUM
MU_PLUS_LAMBDA_SELECTION = "mu_plus_lambda"
CANDIDATE_JAVA_MODES = ("generated_phenotype", "inherited_genotype")

DEFAULT_UNIT_MATERIAL_VALUES = (
    ("Resource", 0.0),
    ("Base", 10.0),
    ("Barracks", 5.0),
    ("Worker", 1.0),
    ("Light", 2.0),
    ("Heavy", 4.0),
    ("Ranged", 2.0),
)


@dataclass(frozen=True)
class ModelConfig:
    """The one llama.cpp model/runtime selected by an experiment."""

    name: str = "unconfigured"
    path: Path | None = None
    llama_server: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8080
    context_size: int = 32768
    gpu_layers: int = -1
    threads: int = 8
    batch_size: int = 512
    parallel: int = 1
    startup_timeout_seconds: float = 180.0
    health_timeout_seconds: float = 5.0

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    def validate(self, *, require_files: bool = False) -> None:
        if not self.name.strip():
            raise ValueError("model.name is required.")
        if not self.host or any(character.isspace() for character in self.host):
            raise ValueError(f"model.host is invalid: {self.host!r}")
        if not 1 <= self.port <= 65535:
            raise ValueError("model.port must be between 1 and 65535.")
        for field_name in ("context_size", "threads", "batch_size", "parallel"):
            if int(getattr(self, field_name)) <= 0:
                raise ValueError(f"model.{field_name} must be positive.")
        if self.startup_timeout_seconds <= 0 or self.health_timeout_seconds <= 0:
            raise ValueError("model startup and health timeouts must be positive.")
        if require_files:
            if self.path is None or not self.path.is_file():
                raise ValueError(f"model.path does not exist or is not a file: {self.path}")
            if self.llama_server is None or not self.llama_server.is_file():
                raise ValueError(
                    "model.llama_server does not exist or is not a file: "
                    f"{self.llama_server}"
                )
            import os
            if not os.access(self.llama_server, os.X_OK):
                raise ValueError(f"model.llama_server is not executable: {self.llama_server}")

@dataclass(frozen=True)
class ExperimentConfig:
    seed_prompts: tuple[str, ...]
    seed_prompt_files: tuple[Path, ...] = ()
    experiment_name: str = "eagle_experiment"
    model: ModelConfig = field(default_factory=ModelConfig)
    generations: int = 1
    population_size: int = 4
    mutation_max_attempts: int = 3
    generation_max_attempts: int = 1
    crossover_rate: float = 0.75
    mutation_rate: float = 0.85
    random_seed: int = 7
    survivor_selection: str = MU_PLUS_LAMBDA_SELECTION
    execution_mode: str = "openai"
    llm_temperature: float = 0.2
    llm_max_tokens: int | None = None
    match_commentator_enabled: bool = True
    match_commentator_temperature: float = 0.2
    match_commentator_sample_count: int = 10
    microrts_dir: Path = Path("third_party/microrts")
    runs_dir: Path = Path("runs")
    agent_template_path: Path = DEFAULT_AGENT_TEMPLATE_PATH
    initial_java_seed_path: Path = DEFAULT_INITIAL_JAVA_SEED_PATH
    candidate_java_mode: str = "generated_phenotype"
    tick_limit: int = 100
    match_timeout_seconds: float = 120.0
    match_artifact_mode: str = "compact"
    evaluation_maps: tuple[str, ...] = DEFAULT_EVALUATION_MAPS
    evaluation_map_tick_limits: tuple[int, ...] = ()
    rounds_per_map: int = 3
    swap_player_sides: bool = True
    evaluation_opponents: tuple[tuple[str, float], ...] = DEFAULT_SEARCH_OPPONENTS
    max_prompt_chars: int = 4000
    max_prompt_lines: int = 80
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
    generation_prompt_file: Path = DEFAULT_PROMPT_DIR / "initial_generation.txt"
    mock_score_base: float = 10.0
    mock_score_step: float = 1.0
    result_win_score: float = 100.0
    result_draw_score: float = 0.0
    result_loss_score: float = -100.0
    material_scale: float = 10.0
    resource_scale: float = 10.0
    unit_material_values: tuple[tuple[str, float], ...] = DEFAULT_UNIT_MATERIAL_VALUES
    stagnation_generations: int = 10
    reflection_operator_mode: ReflectionOperatorMode = ReflectionOperatorMode.AOS_HEAD2HEAD
    strategy_reflection_probability: float = 0.20
    code_reflection_probability: float = 0.80
    balance_reflection_probability: float = 0.0
    aos_minimum_probability: float = 0.10

    @classmethod
    def from_file(cls, path: str | Path) -> "ExperimentConfig":
        config_path = Path(path)
        raw_config = config_path.read_text(encoding="utf-8")
        payload = json.loads(raw_config) if config_path.suffix.lower() == ".json" else yaml.safe_load(raw_config)
        if not isinstance(payload, dict):
            raise ValueError("Experiment config must contain a YAML mapping.")
        return cls.from_mapping(payload, base_dir=Path(__file__).resolve().parents[1])

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        *,
        base_dir: Path | None = None,
    ) -> "ExperimentConfig":
        schema_version = payload.get("schema_version")
        if schema_version not in {None, "experiment-v1", "experiment-v2"}:
            raise ValueError(f"Unsupported experiment schema version: {schema_version!r}")
        if payload.get("algorithm", "lexicase") != "lexicase":
            raise ValueError("The canonical EAGLE parent-selection algorithm is lexicase.")
        survivor_selection = str(
            payload.get("survivor_selection", MU_PLUS_LAMBDA_SELECTION)
        )
        if survivor_selection != MU_PLUS_LAMBDA_SELECTION:
            raise ValueError(
                "The canonical EAGLE survivor selection is mu_plus_lambda lexicase."
            )
        if payload.get("application", "microrts") != "microrts":
            raise ValueError("The configured application is not supported.")
        if payload.get("objectives", {"opponent_cases": "maximize"}) != {"opponent_cases": "maximize"}:
            raise ValueError("The evolutionary objective contract is the ten fixed opponent cases.")
        if schema_version == "experiment-v2" and not isinstance(payload.get("model"), dict):
            raise ValueError("experiment-v2 requires a model mapping.")
        forbidden = {
            "llm_base_url", "llm_model", "llm_model_path", "model_path",
            "llm_role_topology_path", "servers", "role_mapping", "endpoints",
        }
        found = sorted(forbidden.intersection(payload))
        if found:
            raise ValueError("Experiment config cannot define runtime endpoint fields: " + ", ".join(found))
        repository_root = base_dir or Path(__file__).resolve().parents[1]
        obsolete_fields = {
            "seed_prompts", "seed_prompt_template", "generation_prompt",
            "generation_backend", "alignment_backend", "opponent",
            "matches_per_candidate", "map_path",
        }
        obsolete = sorted(obsolete_fields.intersection(payload))
        if obsolete:
            raise ValueError(
                "Obsolete experiment fields are not supported: " + ", ".join(obsolete)
                + ". Store prompts in prompts/*.txt and use execution_mode."
            )
        seed_prompt_files = _parse_prompt_files(
            payload.get("seed_prompt_files", (DEFAULT_SEED_POLICY_PATH,)),
            repository_root,
            "seed_prompt_files",
            allow_empty=True,
        )
        seed_prompts = tuple(path.read_text(encoding="utf-8").strip() for path in seed_prompt_files)
        if not seed_prompts:
            raise ValueError("Experiment config must define at least one seed_prompt_files entry.")
        generation_prompt_file_value = payload.get("generation_prompt_file")
        generation_prompt_file = (
            _parse_prompt_files((generation_prompt_file_value,), repository_root, "generation_prompt_file")[0]
            if generation_prompt_file_value is not None
            else DEFAULT_PROMPT_DIR / "initial_generation.txt"
        )
        generation_prompt = generation_prompt_file.read_text(encoding="utf-8").strip()
        model = _parse_model(payload.get("model"), repository_root)
        llm_settings = payload.get("llm", {})
        if not isinstance(llm_settings, dict):
            raise ValueError("Experiment llm settings must be a mapping.")
        max_tokens = llm_settings.get("max_tokens")
        if "roles" in llm_settings:
            raise ValueError("llm.roles is obsolete; use llm.match_commentator for commentator settings.")
        commentator_settings = llm_settings.get("match_commentator", {})
        if not isinstance(commentator_settings, dict):
            raise ValueError("llm.match_commentator must be a mapping.")
        evaluation_settings = payload.get("evaluation", {})
        if not isinstance(evaluation_settings, dict):
            raise ValueError("evaluation must be a mapping.")
        if "matches_per_candidate" in evaluation_settings:
            raise ValueError(
                "evaluation.matches_per_candidate is derived from maps, rounds, sides, and opponents."
            )
        tick_limit = int(payload.get("tick_limit", 100))
        evaluation_maps, evaluation_map_tick_limits = _parse_evaluation_maps(
            evaluation_settings.get("maps", payload.get("evaluation_maps", DEFAULT_EVALUATION_MAPS)),
            default_tick_limit=tick_limit,
        )
        rounds_per_map = int(evaluation_settings.get("rounds_per_map", payload.get("rounds_per_map", 3)))
        swap_player_sides = bool(evaluation_settings.get("swap_player_sides", payload.get("swap_player_sides", True)))
        if "evaluation_opponents" in payload:
            raise ValueError("evaluation_opponents is fixed by eagle.opponent_cases and must not be overridden.")
        evaluation_opponents = DEFAULT_SEARCH_OPPONENTS
        configured_opponents = evaluation_settings.get("opponents")
        if configured_opponents is not None:
            parsed_opponents = _parse_evaluation_opponents(configured_opponents)
            if parsed_opponents != evaluation_opponents:
                raise ValueError("evaluation.opponents must equal the canonical ten-opponent roster and weights.")
        if "aos" in payload:
            raise ValueError(
                "The nested aos config is obsolete. Use reflection_operator_mode, "
                "strategy_reflection_probability, code_reflection_probability, "
                "balance_reflection_probability, and "
                "aos_minimum_probability at the top level."
            )
        reflection_operator_mode = ReflectionOperatorMode.parse(
            payload.get("reflection_operator_mode", ReflectionOperatorMode.AOS_HEAD2HEAD.value)
        )
        if "eagle_opponent" in payload:
            raise ValueError("eagle_opponent is obsolete; evolutionary evaluation uses only the ten fixed opponents.")
        if "match_seeds" in payload:
            raise ValueError(
                "match_seeds is obsolete: MicroRTS never consumed the configured values. "
                "Remove match_seeds and use round_index to identify repeated matches."
            )
        return cls(
            seed_prompts=seed_prompts,
            seed_prompt_files=seed_prompt_files,
            experiment_name=str(payload.get("experiment_name", "eagle_experiment")),
            model=model,
            generations=int(payload.get("generations", 1)),
            population_size=int(payload.get("population_size", max(1, len(seed_prompts)))),
            mutation_max_attempts=int(payload.get("mutation_max_attempts", cls.mutation_max_attempts)),
            generation_max_attempts=int(payload.get("generation_max_attempts", cls.generation_max_attempts)),
            crossover_rate=float(payload.get("crossover_rate", 0.75)),
            mutation_rate=float(payload.get("mutation_rate", 0.85)),
            random_seed=int(payload.get("random_seed", 7)),
            survivor_selection=survivor_selection,
            execution_mode=str(payload.get("execution_mode", "openai")),
            llm_temperature=float(llm_settings.get("temperature", 0.2)),
            llm_max_tokens=None if max_tokens is None else int(max_tokens),
            match_commentator_enabled=bool(commentator_settings.get("enabled", True)),
            match_commentator_temperature=float(commentator_settings.get("temperature", 0.2)),
            match_commentator_sample_count=int(commentator_settings.get("sample_count", 10)),
            microrts_dir=Path(payload.get("microrts_dir", "third_party/microrts")),
            runs_dir=Path(payload.get("runs_dir", "runs")),
            agent_template_path=_repository_path(payload.get("agent_template_path"), DEFAULT_AGENT_TEMPLATE_PATH),
            initial_java_seed_path=_repository_path(
                payload.get("initial_java_seed_path"),
                DEFAULT_INITIAL_JAVA_SEED_PATH,
            ),
            candidate_java_mode=str(payload.get("candidate_java_mode", "generated_phenotype")),
            tick_limit=tick_limit,
            match_timeout_seconds=float(payload.get("match_timeout_seconds", 120.0)),
            match_artifact_mode=str(payload.get("match_artifact_mode", "compact")),
            evaluation_maps=evaluation_maps,
            evaluation_map_tick_limits=evaluation_map_tick_limits,
            rounds_per_map=rounds_per_map,
            swap_player_sides=swap_player_sides,
            evaluation_opponents=evaluation_opponents,
            max_prompt_chars=int(payload.get("max_prompt_chars", 4000)),
            max_prompt_lines=int(payload.get("max_prompt_lines", 80)),
            generation_prompt=generation_prompt,
            generation_prompt_file=generation_prompt_file,
            mock_score_base=float(payload.get("mock_score_base", 10.0)),
            mock_score_step=float(payload.get("mock_score_step", 1.0)),
            result_win_score=float(payload.get("result_win_score", 100.0)),
            result_draw_score=float(payload.get("result_draw_score", 0.0)),
            result_loss_score=float(payload.get("result_loss_score", -100.0)),
            material_scale=float(payload.get("material_scale", 10.0)),
            resource_scale=float(payload.get("resource_scale", 10.0)),
            unit_material_values=_parse_unit_material_values(payload.get("unit_material_values")),
            stagnation_generations=int(payload.get("stagnation_generations", 10)),
            reflection_operator_mode=reflection_operator_mode,
            strategy_reflection_probability=float(payload.get("strategy_reflection_probability", 0.20)),
            code_reflection_probability=float(payload.get("code_reflection_probability", 0.80)),
            balance_reflection_probability=float(payload.get("balance_reflection_probability", 0.0)),
            aos_minimum_probability=float(payload.get("aos_minimum_probability", 0.10)),
        )

    def validate(self) -> None:
        if not self.experiment_name.strip():
            raise ValueError("experiment_name must not be empty.")
        self.model.validate()
        if self.generations < 1:
            raise ValueError("generations must be at least 1.")
        if self.population_size < 1:
            raise ValueError("population_size must be at least 1.")
        if self.survivor_selection != MU_PLUS_LAMBDA_SELECTION:
            raise ValueError(
                "survivor_selection must be the canonical mu_plus_lambda mode."
            )
        if not 0.0 <= self.crossover_rate <= 1.0:
            raise ValueError("crossover_rate must be in [0, 1].")
        if not 0.0 <= self.mutation_rate <= 1.0:
            raise ValueError("mutation_rate must be in [0, 1].")
        if self.mutation_max_attempts < 1:
            raise ValueError("mutation_max_attempts must be at least 1.")
        if self.generation_max_attempts < 1:
            raise ValueError("generation_max_attempts must be at least 1.")
        if self.stagnation_generations < 0:
            raise ValueError("stagnation_generations must be at least 0.")
        self.reflection_operator_settings.validate()
        if self.tick_limit < 1:
            raise ValueError("tick_limit must be at least 1.")
        if self.execution_mode not in {"mock", "openai"}:
            raise ValueError("execution_mode must be mock or openai.")
        if self.candidate_java_mode not in CANDIDATE_JAVA_MODES:
            raise ValueError(
                "candidate_java_mode must be generated_phenotype or inherited_genotype."
            )
        if self.candidate_java_mode == "inherited_genotype" and len(self.seed_prompts) != 1:
            raise ValueError(
                "candidate_java_mode=inherited_genotype requires exactly one seed_prompt_files entry."
            )
        if len(self.evaluation_maps) != 3:
            raise ValueError("evaluation.maps must contain exactly three maps.")
        map_tick_limits = self.resolved_evaluation_map_tick_limits
        if len(map_tick_limits) != len(self.evaluation_maps):
            raise ValueError("evaluation map tick limits must align with evaluation.maps.")
        if any(limit < 1 for limit in map_tick_limits):
            raise ValueError("evaluation map tick limits must be at least 1.")
        if self.rounds_per_map != 3:
            raise ValueError("evaluation.rounds_per_map must be exactly 3.")
        if not self.swap_player_sides:
            raise ValueError("evaluation.swap_player_sides must be true.")
        microrts_root = self.microrts_dir
        for map_path in self.evaluation_maps:
            if not (microrts_root / map_path).is_file():
                raise ValueError(f"Configured evaluation map does not exist: {microrts_root / map_path}")
        if self.match_timeout_seconds <= 0:
            raise ValueError("match_timeout_seconds must be greater than zero.")
        if self.match_artifact_mode not in {"compact", "full"}:
            raise ValueError("match_artifact_mode must be compact or full.")
        if tuple(item[0] for item in self.evaluation_opponents) != LEXICASE_CASES:
            raise ValueError("evaluation_opponents must use the canonical ten-opponent order.")
        if any(weight <= 0 for _, weight in self.evaluation_opponents):
            raise ValueError("evaluation opponent weights must be positive.")
        if abs(self.fixed_opponent_weight_sum - FIXED_OPPONENT_WEIGHT_SUM) > 1e-9:
            raise ValueError(f"fixed opponent weights must sum to {FIXED_OPPONENT_WEIGHT_SUM}.")
        if self.llm_temperature < 0:
            raise ValueError("llm.temperature must not be negative.")
        if self.llm_max_tokens is not None and self.llm_max_tokens < 1:
            raise ValueError("llm.max_tokens must be positive.")
        if self.match_commentator_temperature < 0:
            raise ValueError("llm.match_commentator.temperature must not be negative.")
        if self.match_commentator_sample_count < 1:
            raise ValueError("llm.match_commentator.sample_count must be positive.")
        from generation.agent_template import JavaTemplatePaths, validate_java_template
        if self.material_scale <= 0 or self.resource_scale <= 0:
            raise ValueError("material_scale and resource_scale must be greater than zero.")
        if not self.unit_material_values:
            raise ValueError("unit_material_values must not be empty.")
        if any(value < 0 for _, value in self.unit_material_values):
            raise ValueError("unit material values must be non-negative.")
        validate_java_template(JavaTemplatePaths(self.agent_template_path))
        validate_java_template(JavaTemplatePaths(self.initial_java_seed_path))

    def validate_runtime_files(self) -> None:
        """Validate external model assets immediately before a production launch."""

        self.model.validate(require_files=True)

    def to_mapping(self, *, mock: bool = False) -> dict[str, Any]:
        """Return the complete resolved experiment document persisted by a run."""

        return {
            "schema_version": "experiment-v2",
            "experiment_name": self.experiment_name,
            "algorithm": "lexicase",
            "survivor_selection": self.survivor_selection,
            "application": "microrts",
            "objectives": {"opponent_cases": "maximize"},
            "model": {
                "name": self.model.name,
                "path": None if self.model.path is None else str(self.model.path),
                "llama_server": None if self.model.llama_server is None else str(self.model.llama_server),
                "host": self.model.host,
                "port": self.model.port,
                "context_size": self.model.context_size,
                "gpu_layers": self.model.gpu_layers,
                "threads": self.model.threads,
                "batch_size": self.model.batch_size,
                "parallel": self.model.parallel,
                "startup_timeout_seconds": self.model.startup_timeout_seconds,
                "health_timeout_seconds": self.model.health_timeout_seconds,
            },
            "seed_prompt_files": [str(path) for path in self.seed_prompt_files],
            "generations": self.generations,
            "population_size": self.population_size,
            "mutation_max_attempts": self.mutation_max_attempts,
            "generation_max_attempts": self.generation_max_attempts,
            "crossover_rate": self.crossover_rate,
            "mutation_rate": self.mutation_rate,
            "random_seed": self.random_seed,
            "execution_mode": "mock" if mock else self.execution_mode,
            "reflection_operator_mode": self.reflection_operator_mode.value,
            "strategy_reflection_probability": self.strategy_reflection_probability,
            "code_reflection_probability": self.code_reflection_probability,
            "balance_reflection_probability": self.balance_reflection_probability,
            "aos_minimum_probability": self.aos_minimum_probability,
            "llm": {
                "temperature": self.llm_temperature,
                "max_tokens": self.llm_max_tokens,
                "match_commentator": {
                    "enabled": self.match_commentator_enabled,
                    "temperature": self.match_commentator_temperature,
                    "sample_count": self.match_commentator_sample_count,
                },
            },
            "microrts_dir": str(self.microrts_dir.resolve()),
            "runs_dir": str(self.runs_dir.resolve()),
            "agent_template_path": str(self.agent_template_path.resolve()),
            "initial_java_seed_path": str(self.initial_java_seed_path.resolve()),
            "candidate_java_mode": self.candidate_java_mode,
            "tick_limit": self.tick_limit,
            "match_timeout_seconds": self.match_timeout_seconds,
            "match_artifact_mode": self.match_artifact_mode,
            "evaluation": {
                "maps": [
                    {"path": path, "tick_limit": tick_limit}
                    for path, tick_limit in zip(
                        self.evaluation_maps,
                        self.resolved_evaluation_map_tick_limits,
                        strict=True,
                    )
                ],
                "rounds_per_map": self.rounds_per_map,
                "swap_player_sides": self.swap_player_sides,
                "opponents": [
                    {"id": opponent_id, "weight": weight}
                    for opponent_id, weight in self.evaluation_opponents
                ],
            },
            "max_prompt_chars": self.max_prompt_chars,
            "max_prompt_lines": self.max_prompt_lines,
            "generation_prompt_file": str(self.generation_prompt_file),
            "mock_score_base": self.mock_score_base,
            "mock_score_step": self.mock_score_step,
            "result_win_score": self.result_win_score,
            "result_draw_score": self.result_draw_score,
            "result_loss_score": self.result_loss_score,
            "material_scale": self.material_scale,
            "resource_scale": self.resource_scale,
            "unit_material_values": dict(self.unit_material_values),
            "stagnation_generations": self.stagnation_generations,
        }

    @property
    def llm_base_url(self) -> str:
        return self.model.base_url

    @property
    def llm_model(self) -> str:
        return self.model.name

    @property
    def llm_model_path(self) -> str | None:
        return None if self.model.path is None else str(self.model.path)

    @property
    def reflection_operator_settings(self) -> ReflectionOperatorSettings:
        return ReflectionOperatorSettings(
            mode=ReflectionOperatorMode.parse(self.reflection_operator_mode),
            strategy_probability=self.strategy_reflection_probability,
            code_probability=self.code_reflection_probability,
            balance_probability=self.balance_reflection_probability,
            minimum_probability=self.aos_minimum_probability,
        )

    @property
    def fixed_matches_per_opponent(self) -> int:
        return len(self.evaluation_maps) * self.rounds_per_map * 2

    @property
    def resolved_evaluation_map_tick_limits(self) -> tuple[int, ...]:
        """Return one effective tick cap for each configured evaluation map."""

        if not self.evaluation_map_tick_limits:
            return (self.tick_limit,) * len(self.evaluation_maps)
        return tuple(int(limit) for limit in self.evaluation_map_tick_limits)

    @property
    def expected_match_count(self) -> int:
        return self.fixed_matches_per_opponent * len(self.evaluation_opponents)

    @property
    def fixed_opponent_weight_sum(self) -> float:
        return round(sum(weight for _, weight in self.evaluation_opponents), 6)

    @property
    def evaluation_opponent_ids(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.evaluation_opponents)


def _parse_evaluation_opponents(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, list | tuple):
        raise ValueError("evaluation_opponents must be a list of {id, weight} mappings.")
    parsed: list[tuple[str, float]] = []
    for item in value:
        if isinstance(item, dict):
            opponent_id = str(item.get("id", ""))
            weight = float(item.get("weight"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            opponent_id, weight = str(item[0]), float(item[1])
        else:
            raise ValueError("Each evaluation opponent must contain id and weight.")
        if not opponent_id:
            raise ValueError("Evaluation opponent id must not be empty.")
        parsed.append((opponent_id, weight))
    return tuple(parsed)


def _parse_prompt_files(
    value: object,
    base_dir: Path,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[Path, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list of prompt file paths.")
    paths: list[Path] = []
    for item in value:
        path = Path(str(item)).expanduser()
        path = path.resolve() if path.is_absolute() else (base_dir / path).resolve()
        if path.suffix != ".txt":
            raise ValueError(f"{field_name} entries must be .txt files: {path}")
        if not path.is_file():
            raise ValueError(f"{field_name} prompt file does not exist: {path}")
        if not allow_empty and not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"{field_name} prompt file must not be empty: {path}")
        paths.append(path)
    return tuple(paths)


def _parse_model(value: object, base_dir: Path) -> ModelConfig:
    if value is None:
        return ModelConfig()
    if not isinstance(value, dict):
        raise ValueError("model must be a mapping.")

    def path_value(key: str) -> Path | None:
        raw = value.get(key)
        if raw in (None, ""):
            return None
        path = Path(str(raw)).expanduser()
        return path.resolve() if path.is_absolute() else (base_dir / path).resolve()

    try:
        result = ModelConfig(
            name=str(value.get("name", "")).strip(),
            path=path_value("path"),
            llama_server=path_value("llama_server"),
            host=str(value.get("host", "127.0.0.1")).strip(),
            port=int(value.get("port", 8080)),
            context_size=int(value.get("context_size", 32768)),
            gpu_layers=int(value.get("gpu_layers", -1)),
            threads=int(value.get("threads", 8)),
            batch_size=int(value.get("batch_size", 512)),
            parallel=int(value.get("parallel", 1)),
            startup_timeout_seconds=float(value.get("startup_timeout_seconds", 180)),
            health_timeout_seconds=float(value.get("health_timeout_seconds", 5)),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid model configuration: {exc}") from exc
    result.validate()
    return result


def _parse_evaluation_maps(
    value: object,
    *,
    default_tick_limit: int,
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("evaluation.maps must be a list of paths or {path, tick_limit} mappings.")
    paths: list[str] = []
    tick_limits: list[int] = []
    for item in value:
        if isinstance(item, dict):
            path_value = item.get("path")
            tick_limit_value = item.get("tick_limit", default_tick_limit)
        else:
            path_value = item
            tick_limit_value = default_tick_limit
        path = str(path_value or "").strip()
        if not path:
            raise ValueError("evaluation map paths must not be empty.")
        try:
            tick_limit = int(tick_limit_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"evaluation map tick_limit must be an integer: {path}") from exc
        paths.append(path)
        tick_limits.append(tick_limit)
    return tuple(paths), tuple(tick_limits)

def _parse_unit_material_values(value: object) -> tuple[tuple[str, float], ...]:
    resolved = dict(DEFAULT_UNIT_MATERIAL_VALUES)
    if value is None:
        return tuple(resolved.items())
    if not isinstance(value, dict):
        raise ValueError("unit_material_values must be a mapping.")
    resolved.update({str(name): float(cost) for name, cost in value.items()})
    return tuple(sorted(resolved.items()))


def _repository_path(value: object | None, default: Path) -> Path:
    if value is None:
        return default
    path = Path(str(value))
    return path if path.is_absolute() else DEFAULT_AGENT_TEMPLATE_PATH.parents[2] / path
