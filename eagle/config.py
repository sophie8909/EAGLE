"""Experiment configuration for the generated-agent EAGLE pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from generation.agent_template import DEFAULT_AGENT_TEMPLATE_PATH, get_seed_prompt_template

from .candidate import DEFAULT_GENERATION_PROMPT
from .opponent_cases import LEXICASE_CASES, OPPONENT_WEIGHTS, OPPONENT_WEIGHT_SUM


TRAINING_OPPONENT = "ai.abstraction.LightRush"
# Canonical fixed search: ten opponents × three maps × three rounds × two sides.
MATCHES_PER_CANDIDATE = 180
FIXED_MATCHES_PER_OPPONENT = 18
DEFAULT_EVALUATION_MAPS = (
    "maps/8x8/basesWorkers8x8.xml",
    "maps/16x16/basesWorkers16x16.xml",
    "maps/24x24/basesWorkers24x24.xml",
)
DEFAULT_SEARCH_OPPONENTS = tuple((case, OPPONENT_WEIGHTS[case]) for case in LEXICASE_CASES)
FIXED_OPPONENT_WEIGHT_SUM = OPPONENT_WEIGHT_SUM

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
class ExperimentConfig:
    seed_prompts: tuple[str, ...]
    generations: int = 1
    population_size: int = 4
    mutation_suffix: str = "Adjust the strategy while keeping the generated Java agent simple and compilable."
    mutation_max_attempts: int = 3
    crossover_rate: float = 0.75
    mutation_rate: float = 0.85
    random_seed: int = 7
    generation_backend: str = "mock"
    alignment_backend: str = "mock"
    llm_base_url: str = "http://localhost:8080"
    llm_model: str = ""
    llm_temperature: float = 0.2
    llm_max_tokens: int | None = None
    llm_model_path: str | None = None
    match_commentator_enabled: bool = True
    match_commentator_temperature: float = 0.2
    match_commentator_chunk_ticks: int = 200
    microrts_dir: Path = Path("third_party/microrts")
    runs_dir: Path = Path("runs")
    agent_template_path: Path = DEFAULT_AGENT_TEMPLATE_PATH
    tick_limit: int = 100
    opponent: str = TRAINING_OPPONENT
    matches_per_candidate: int = MATCHES_PER_CANDIDATE
    map_path: str = DEFAULT_EVALUATION_MAPS[0]
    match_timeout_seconds: float = 120.0
    match_artifact_mode: str = "compact"
    match_seeds: tuple[int, ...] = ()
    evaluation_maps: tuple[str, ...] = DEFAULT_EVALUATION_MAPS
    rounds_per_map: int = 3
    swap_player_sides: bool = True
    evaluation_opponents: tuple[tuple[str, float], ...] = DEFAULT_SEARCH_OPPONENTS
    max_prompt_chars: int = 4000
    max_prompt_lines: int = 80
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
    mock_score_base: float = 10.0
    mock_score_step: float = 1.0
    result_win_score: float = 100.0
    result_draw_score: float = 0.0
    result_loss_score: float = -100.0
    material_scale: float = 10.0
    resource_scale: float = 10.0
    unit_material_values: tuple[tuple[str, float], ...] = DEFAULT_UNIT_MATERIAL_VALUES
    stagnation_generations: int = 10
    raw_config: str = ""

    @classmethod
    def from_file(cls, path: str | Path) -> "ExperimentConfig":
        config_path = Path(path)
        raw_config = config_path.read_text(encoding="utf-8")
        payload = json.loads(raw_config) if config_path.suffix.lower() == ".json" else yaml.safe_load(raw_config)
        if not isinstance(payload, dict):
            raise ValueError("Experiment config must contain a YAML mapping.")
        return cls.from_mapping(payload, raw_config=raw_config)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], *, raw_config: str = "") -> "ExperimentConfig":
        forbidden = {"llm_base_url", "llm_role_topology_path", "servers", "role_mapping", "endpoints"}
        found = sorted(forbidden.intersection(payload))
        if found:
            raise ValueError("Experiment config cannot define runtime endpoint fields: " + ", ".join(found))
        seed_prompts = tuple(str(item) for item in payload.get("seed_prompts", []))
        template_name = payload.get("seed_prompt_template")
        if template_name:
            seed_prompts = (get_seed_prompt_template(str(template_name)), *seed_prompts)
        if not seed_prompts:
            raise ValueError("Experiment config must define at least one seed prompt or seed_prompt_template.")
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
        evaluation_maps = _parse_evaluation_maps(
            evaluation_settings.get("maps", payload.get("evaluation_maps", DEFAULT_EVALUATION_MAPS))
        )
        rounds_per_map = int(evaluation_settings.get("rounds_per_map", payload.get("rounds_per_map", 3)))
        swap_player_sides = bool(evaluation_settings.get("swap_player_sides", payload.get("swap_player_sides", True)))
        if "evaluation_opponents" in payload:
            raise ValueError("evaluation_opponents is fixed by eagle.opponent_cases and must not be overridden.")
        evaluation_opponents = DEFAULT_SEARCH_OPPONENTS
        if "eagle_opponent" in payload:
            raise ValueError("eagle_opponent is obsolete; evolutionary evaluation uses only the ten fixed opponents.")
        return cls(
            seed_prompts=seed_prompts,
            generations=int(payload.get("generations", 1)),
            population_size=int(payload.get("population_size", max(1, len(seed_prompts)))),
            mutation_suffix=str(payload.get("mutation_suffix", cls.mutation_suffix)),
            mutation_max_attempts=int(payload.get("mutation_max_attempts", cls.mutation_max_attempts)),
            crossover_rate=float(payload.get("crossover_rate", 0.75)),
            mutation_rate=float(payload.get("mutation_rate", 0.85)),
            random_seed=int(payload.get("random_seed", 7)),
            generation_backend=str(payload.get("generation_backend", "mock")),
            alignment_backend=str(payload.get("alignment_backend", payload.get("generation_backend", "mock"))),
            llm_base_url=str(payload.get("llm_base_url", "http://localhost:8080")),
            llm_model=str(payload.get("llm_model", "")),
            llm_temperature=float(llm_settings.get("temperature", 0.2)),
            llm_max_tokens=None if max_tokens is None else int(max_tokens),
            llm_model_path=None,
            match_commentator_enabled=bool(commentator_settings.get("enabled", True)),
            match_commentator_temperature=float(commentator_settings.get("temperature", 0.2)),
            match_commentator_chunk_ticks=int(commentator_settings.get("chunk_ticks", 200)),
            microrts_dir=Path(payload.get("microrts_dir", "third_party/microrts")),
            runs_dir=Path(payload.get("runs_dir", "runs")),
            agent_template_path=_repository_path(payload.get("agent_template_path"), DEFAULT_AGENT_TEMPLATE_PATH),
            tick_limit=int(payload.get("tick_limit", 100)),
            opponent=TRAINING_OPPONENT,
            matches_per_candidate=len(evaluation_maps) * rounds_per_map * 2 * len(evaluation_opponents),
            map_path=str(payload.get("map_path", evaluation_maps[0])),
            match_timeout_seconds=float(payload.get("match_timeout_seconds", 120.0)),
            match_artifact_mode=str(payload.get("match_artifact_mode", "compact")),
            match_seeds=tuple(int(value) for value in payload.get("match_seeds", ())),
            evaluation_maps=evaluation_maps,
            rounds_per_map=rounds_per_map,
            swap_player_sides=swap_player_sides,
            evaluation_opponents=evaluation_opponents,
            max_prompt_chars=int(payload.get("max_prompt_chars", 4000)),
            max_prompt_lines=int(payload.get("max_prompt_lines", 80)),
            generation_prompt=str(payload.get("generation_prompt", DEFAULT_GENERATION_PROMPT)),
            mock_score_base=float(payload.get("mock_score_base", 10.0)),
            mock_score_step=float(payload.get("mock_score_step", 1.0)),
            result_win_score=float(payload.get("result_win_score", 100.0)),
            result_draw_score=float(payload.get("result_draw_score", 0.0)),
            result_loss_score=float(payload.get("result_loss_score", -100.0)),
            material_scale=float(payload.get("material_scale", 10.0)),
            resource_scale=float(payload.get("resource_scale", 10.0)),
            unit_material_values=_parse_unit_material_values(payload.get("unit_material_values")),
            stagnation_generations=int(payload.get("stagnation_generations", 10)),
            raw_config=raw_config,
        )

    def validate(self) -> None:
        if self.generations < 1:
            raise ValueError("generations must be at least 1.")
        if self.population_size < 1:
            raise ValueError("population_size must be at least 1.")
        if not 0.0 <= self.crossover_rate <= 1.0:
            raise ValueError("crossover_rate must be in [0, 1].")
        if not 0.0 <= self.mutation_rate <= 1.0:
            raise ValueError("mutation_rate must be in [0, 1].")
        if self.mutation_max_attempts < 1:
            raise ValueError("mutation_max_attempts must be at least 1.")
        if self.stagnation_generations < 0:
            raise ValueError("stagnation_generations must be at least 0.")
        if self.tick_limit < 1:
            raise ValueError("tick_limit must be at least 1.")
        if self.alignment_backend not in {"mock", "openai"}:
            raise ValueError("alignment_backend must be mock or openai.")
        if len(self.evaluation_maps) != 3:
            raise ValueError("evaluation.maps must contain exactly three maps.")
        if self.rounds_per_map != 3:
            raise ValueError("evaluation.rounds_per_map must be exactly 3.")
        if not self.swap_player_sides:
            raise ValueError("evaluation.swap_player_sides must be true.")
        if self.matches_per_candidate != FIXED_MATCHES_PER_OPPONENT * len(self.evaluation_opponents):
            raise ValueError(
                "matches_per_candidate must equal 18 matches per fixed opponent "
                f"({FIXED_MATCHES_PER_OPPONENT * len(self.evaluation_opponents)})."
            )
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
        if self.match_commentator_chunk_ticks < 1:
            raise ValueError("llm.match_commentator.chunk_ticks must be positive.")
        if len(self.resolved_match_seeds) != self.rounds_per_map:
            raise ValueError("match_seeds must contain exactly one seed per round.")
        if self.resolved_match_seeds != tuple(range(self.rounds_per_map)):
            raise ValueError("round seeds must be the canonical deterministic schedule 0, 1, 2.")
        from generation.agent_template import JavaTemplatePaths, validate_java_template
        if self.material_scale <= 0 or self.resource_scale <= 0:
            raise ValueError("material_scale and resource_scale must be greater than zero.")
        if not self.unit_material_values:
            raise ValueError("unit_material_values must not be empty.")
        if any(value < 0 for _, value in self.unit_material_values):
            raise ValueError("unit material values must be non-negative.")
        validate_java_template(JavaTemplatePaths(self.agent_template_path))

    @property
    def resolved_match_seeds(self) -> tuple[int, ...]:
        """Return the stable round seed schedule shared by side-swapped pairs."""

        return tuple(self.match_seeds) if self.match_seeds else tuple(range(self.rounds_per_map))

    @property
    def fixed_matches_per_opponent(self) -> int:
        return len(self.evaluation_maps) * self.rounds_per_map * 2

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


def _parse_evaluation_maps(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("evaluation.maps must be a list of map paths.")
    paths: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("path")
        path = str(item or "").strip()
        if not path:
            raise ValueError("evaluation map paths must not be empty.")
        paths.append(path)
    return tuple(paths)

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


def parse_minimal_yaml(raw: str) -> dict[str, Any]:
    """Parse the small YAML subset used by EAGLE configs."""

    payload: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in raw.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current_key is None:
                raise ValueError("YAML list item has no key.")
            payload.setdefault(current_key, []).append(_parse_scalar(stripped[2:].strip()))
            continue
        if ":" not in line:
            raise ValueError(f"Unsupported YAML line: {raw_line}")
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        payload[current_key] = [] if value == "" else _parse_scalar(value)
    return payload


def _parse_scalar(value: str) -> Any:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
