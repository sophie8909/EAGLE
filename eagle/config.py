"""Minimal experiment configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExperimentConfig:
    seed_prompts: tuple[str, ...]
    generations: int = 1
    population_size: int = 2
    generated_agent_dir: Path = Path("agents/generated")
    generation_backend: str = "template"
    microrts_dir: Path = Path("third_party/microrts")
    tick_limit: int = 100
    opponent: str = "ai.RandomBiasedAI"
    dry_run: bool = True

    @classmethod
    def from_json(cls, path: str | Path) -> "ExperimentConfig":
        config_path = Path(path)
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        seed_prompts = tuple(str(item) for item in payload.get("seed_prompts", []))
        if not seed_prompts:
            raise ValueError("Experiment config must define at least one seed prompt.")
        return cls(
            seed_prompts=seed_prompts,
            generations=int(payload.get("generations", 1)),
            population_size=int(payload.get("population_size", max(1, len(seed_prompts)))),
            generated_agent_dir=Path(payload.get("generated_agent_dir", "agents/generated")),
            generation_backend=str(payload.get("generation_backend", "template")),
            microrts_dir=Path(payload.get("microrts_dir", "third_party/microrts")),
            tick_limit=int(payload.get("tick_limit", 100)),
            opponent=str(payload.get("opponent", "ai.RandomBiasedAI")),
            dry_run=bool(payload.get("dry_run", True)),
        )

    def validate(self) -> None:
        if self.generations < 1:
            raise ValueError("generations must be at least 1.")
        if self.population_size < 1:
            raise ValueError("population_size must be at least 1.")
        if self.tick_limit < 1:
            raise ValueError("tick_limit must be at least 1.")

