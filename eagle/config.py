"""Experiment configuration for the generated-agent EAGLE pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generation.agent_template import get_seed_prompt_template

from .candidate import DEFAULT_GENERATION_PROMPT


TRAINING_OPPONENT = "ai.abstraction.LightRush"


@dataclass(frozen=True)
class ExperimentConfig:
    seed_prompts: tuple[str, ...]
    generations: int = 1
    population_size: int = 4
    mutation_suffix: str = "Adjust the strategy while keeping the generated Java agent simple and compilable."
    crossover_rate: float = 0.75
    mutation_rate: float = 0.85
    random_seed: int = 7
    generation_backend: str = "mock"
    alignment_backend: str = "mock"
    llm_base_url: str = "http://localhost:8080"
    llm_model: str = "local-model"
    microrts_dir: Path = Path("third_party/microrts")
    runs_dir: Path = Path("runs")
    tick_limit: int = 100
    opponent: str = TRAINING_OPPONENT
    matches_per_candidate: int = 1
    max_prompt_chars: int = 4000
    max_prompt_lines: int = 80
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
    mock_score_base: float = 10.0
    mock_score_step: float = 1.0
    result_win_score: float = 1000.0
    result_draw_score: float = 0.0
    result_loss_score: float = -1000.0
    result_error_score: float = -2000.0
    state_army_weight: float = 1.0
    state_building_weight: float = 1.0
    state_resource_weight: float = 1.0
    survival_weight: float = 200.0
    final_resource_weight: float = 1.0
    raw_config: str = ""

    @classmethod
    def from_file(cls, path: str | Path) -> "ExperimentConfig":
        config_path = Path(path)
        raw_config = config_path.read_text(encoding="utf-8")
        if config_path.suffix.lower() == ".json":
            payload = json.loads(raw_config)
        else:
            payload = parse_minimal_yaml(raw_config)
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
            crossover_rate=float(payload.get("crossover_rate", 0.75)),
            mutation_rate=float(payload.get("mutation_rate", 0.85)),
            random_seed=int(payload.get("random_seed", 7)),
            generation_backend=str(payload.get("generation_backend", "mock")),
            alignment_backend=str(payload.get("alignment_backend", payload.get("generation_backend", "mock"))),
            llm_base_url=str(payload.get("llm_base_url", "http://localhost:8080")),
            llm_model=str(payload.get("llm_model", "local-model")),
            microrts_dir=Path(payload.get("microrts_dir", "third_party/microrts")),
            runs_dir=Path(payload.get("runs_dir", "runs")),
            tick_limit=int(payload.get("tick_limit", 100)),
            # EA training always evaluates the generated candidate as player 0 against LightRush as player 1.
            opponent=TRAINING_OPPONENT,
            matches_per_candidate=int(payload.get("matches_per_candidate", 1)),
            max_prompt_chars=int(payload.get("max_prompt_chars", 4000)),
            max_prompt_lines=int(payload.get("max_prompt_lines", 80)),
            generation_prompt=str(payload.get("generation_prompt", DEFAULT_GENERATION_PROMPT)),
            mock_score_base=float(payload.get("mock_score_base", 10.0)),
            mock_score_step=float(payload.get("mock_score_step", 1.0)),
            result_win_score=float(payload.get("result_win_score", 1000.0)),
            result_draw_score=float(payload.get("result_draw_score", 0.0)),
            result_loss_score=float(payload.get("result_loss_score", -1000.0)),
            result_error_score=float(payload.get("result_error_score", -2000.0)),
            state_army_weight=float(payload.get("state_army_weight", 1.0)),
            state_building_weight=float(payload.get("state_building_weight", 1.0)),
            state_resource_weight=float(payload.get("state_resource_weight", 1.0)),
            survival_weight=float(payload.get("survival_weight", 200.0)),
            final_resource_weight=float(payload.get("final_resource_weight", 1.0)),
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
        if self.tick_limit < 1:
            raise ValueError("tick_limit must be at least 1.")
        if self.matches_per_candidate < 1:
            raise ValueError("matches_per_candidate must be at least 1.")


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
