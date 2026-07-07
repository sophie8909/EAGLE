"""Candidate representation for evolved strategy prompts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class Candidate:
    """One NSGA-II individual in the prompt-to-Java-agent pipeline."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    generation: int = 0
    parent_ids: tuple[str, ...] = ()
    strategy_prompt: str = ""
    generated_java_agent_path: str | None = None
    compile_status: str = "pending"
    game_eval_result: dict[str, Any] = field(default_factory=dict)
    strategy_alignment_result: dict[str, Any] = field(default_factory=dict)
    fitness_objectives: dict[str, float] = field(default_factory=dict)
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)

    def objective_vector(self) -> tuple[float, ...]:
        if not self.fitness_objectives:
            return (0.0, 0.0)
        return (
            float(self.fitness_objectives.get("game_performance", 0.0)),
            float(self.fitness_objectives.get("strategy_alignment", 0.0)),
            float(self.fitness_objectives.get("prompt_length", 0.0)),
        )

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_ids"] = list(self.parent_ids)
        return payload
