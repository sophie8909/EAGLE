"""Experiment configuration for the generated-agent EAGLE pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExperimentConfig:
    seed_prompts: tuple[str, ...]
    generations: int = 1
    population_size: int = 2
    elite_count: int = 1
    mutation_suffix: str = "Make the Java agent slightly more robust and keep it compilable."
    generation_backend: str = "mock"
    llm_base_url: str = "http://localhost:8080"
    llm_model: str = "local-model"
    microrts_dir: Path = Path("third_party/microrts")
    runs_dir: Path = Path("runs")
    tick_limit: int = 100
    opponent: str = "ai.RandomBiasedAI"
    matches_per_candidate: int = 1
    mock_score_base: float = 10.0
    mock_score_step: float = 1.0
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
    def from_json(cls, path: str | Path) -> "ExperimentConfig":
        return cls.from_file(path)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], *, raw_config: str = "") -> "ExperimentConfig":
        seed_prompts = tuple(str(item) for item in payload.get("seed_prompts", []))
        if not seed_prompts:
            raise ValueError("Experiment config must define at least one seed prompt.")
        return cls(
            seed_prompts=seed_prompts,
            generations=int(payload.get("generations", 1)),
            population_size=int(payload.get("population_size", max(1, len(seed_prompts)))),
            elite_count=int(payload.get("elite_count", 1)),
            mutation_suffix=str(
                payload.get("mutation_suffix", "Make the Java agent slightly more robust and keep it compilable.")
            ),
            generation_backend=str(payload.get("generation_backend", "mock")),
            llm_base_url=str(payload.get("llm_base_url", "http://localhost:8080")),
            llm_model=str(payload.get("llm_model", "local-model")),
            microrts_dir=Path(payload.get("microrts_dir", "third_party/microrts")),
            runs_dir=Path(payload.get("runs_dir", "runs")),
            tick_limit=int(payload.get("tick_limit", 100)),
            opponent=str(payload.get("opponent", "ai.RandomBiasedAI")),
            matches_per_candidate=int(payload.get("matches_per_candidate", 1)),
            mock_score_base=float(payload.get("mock_score_base", 10.0)),
            mock_score_step=float(payload.get("mock_score_step", 1.0)),
            raw_config=raw_config,
        )

    def validate(self) -> None:
        if self.generations < 1:
            raise ValueError("generations must be at least 1.")
        if self.population_size < 1:
            raise ValueError("population_size must be at least 1.")
        if self.elite_count < 1:
            raise ValueError("elite_count must be at least 1.")
        if self.elite_count > self.population_size:
            raise ValueError("elite_count cannot exceed population_size.")
        if self.tick_limit < 1:
            raise ValueError("tick_limit must be at least 1.")
        if self.matches_per_candidate < 1:
            raise ValueError("matches_per_candidate must be at least 1.")


def parse_minimal_yaml(raw: str) -> dict[str, Any]:
    """Parse the small YAML subset used by configs/eagle_minimal.yaml."""

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
