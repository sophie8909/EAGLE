"""Experiment configuration for the generated-agent EAGLE pipeline."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generation.agent_template import DEFAULT_AGENT_TEMPLATE_PATH, get_seed_prompt_template

from .candidate import DEFAULT_GENERATION_PROMPT


TRAINING_OPPONENT = "ai.abstraction.LightRush"
MATCHES_PER_CANDIDATE = 10

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
    llm_base_url: str = "http://localhost:8080"
    llm_model: str = "local-model"
    microrts_dir: Path = Path("third_party/microrts")
    runs_dir: Path = Path("runs")
    agent_template_path: Path = DEFAULT_AGENT_TEMPLATE_PATH
    tick_limit: int = 100
    opponent: str = TRAINING_OPPONENT
    matches_per_candidate: int = MATCHES_PER_CANDIDATE
    map_path: str = "maps/8x8/basesWorkers8x8.xml"
    match_timeout_seconds: float = 120.0
    match_seeds: tuple[int, ...] = ()
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
    raw_config: str = ""

    @classmethod
    def from_file(cls, path: str | Path) -> "ExperimentConfig":
        config_path = Path(path)
        raw_config = config_path.read_text(encoding="utf-8")
        payload = json.loads(raw_config) if config_path.suffix.lower() == ".json" else parse_minimal_yaml(raw_config)
        return cls.from_mapping(payload, raw_config=raw_config)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], *, raw_config: str = "") -> "ExperimentConfig":
        seed_prompts = tuple(str(item) for item in payload.get("seed_prompts", []))
        template_name = payload.get("seed_prompt_template")
        if template_name:
            seed_prompts = (get_seed_prompt_template(str(template_name)), *seed_prompts)
        if not seed_prompts:
            raise ValueError("Experiment config must define at least one seed prompt or seed_prompt_template.")
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
            llm_base_url=str(payload.get("llm_base_url", "http://localhost:8080")),
            llm_model=str(payload.get("llm_model", "local-model")),
            microrts_dir=Path(payload.get("microrts_dir", "third_party/microrts")),
            runs_dir=Path(payload.get("runs_dir", "runs")),
            agent_template_path=_repository_path(payload.get("agent_template_path"), DEFAULT_AGENT_TEMPLATE_PATH),
            tick_limit=int(payload.get("tick_limit", 100)),
            opponent=TRAINING_OPPONENT,
            matches_per_candidate=MATCHES_PER_CANDIDATE,
            map_path=str(payload.get("map_path", "maps/8x8/basesWorkers8x8.xml")),
            match_timeout_seconds=float(payload.get("match_timeout_seconds", 120.0)),
            match_seeds=tuple(int(value) for value in payload.get("match_seeds", ())),
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
        if self.tick_limit < 1:
            raise ValueError("tick_limit must be at least 1.")
        if self.matches_per_candidate != MATCHES_PER_CANDIDATE:
            raise ValueError(f"matches_per_candidate must be exactly {MATCHES_PER_CANDIDATE}.")
        if self.match_timeout_seconds <= 0:
            raise ValueError("match_timeout_seconds must be greater than zero.")
        if len(self.resolved_match_seeds) != MATCHES_PER_CANDIDATE:
            raise ValueError(f"match_seeds must contain exactly {MATCHES_PER_CANDIDATE} values.")
        if len(set(self.resolved_match_seeds)) != MATCHES_PER_CANDIDATE:
            raise ValueError("match_seeds must be distinct.")
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
        """Return the explicit or deterministically derived ten match seeds."""

        if self.match_seeds:
            return self.match_seeds
        rng = random.Random(self.random_seed)

        return tuple(rng.sample(range(1, 2_147_483_647), MATCHES_PER_CANDIDATE))

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
