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

    @property
    def prompt(self) -> str:
        """Backward-friendly alias for the strategy prompt."""
        return self.strategy_prompt

    @property
    def generated_source_path(self) -> str | None:
        """Backward-friendly alias for generated Java source path."""
        return self.generated_java_agent_path

    @property
    def fitness(self) -> tuple[float, float] | None:
        """Return NSGA-II objectives as a stable two-value vector."""
        if not self.fitness_objectives:
            return None
        return (
            float(self.fitness_objectives.get("game_performance", 0.0)),
            float(self.fitness_objectives.get("strategy_alignment", 0.0)),
        )

    def with_updates(self, **updates: Any) -> "Candidate":
        payload = asdict(self)
        if "prompt" in updates and "strategy_prompt" not in updates:
            updates["strategy_prompt"] = updates.pop("prompt")
        if "generated_source_path" in updates and "generated_java_agent_path" not in updates:
            updates["generated_java_agent_path"] = updates.pop("generated_source_path")
        if "fitness" in updates and "fitness_objectives" not in updates:
            game, alignment = updates.pop("fitness")
            updates["fitness_objectives"] = {
                "game_performance": float(game),
                "strategy_alignment": float(alignment),
            }
        payload.update(updates)
        payload["parent_ids"] = tuple(payload.get("parent_ids") or ())
        return Candidate(**payload)

    def objective_vector(self) -> tuple[float, float]:
        return self.fitness or (0.0, 0.0)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_ids"] = list(self.parent_ids)
        payload["prompt"] = self.strategy_prompt
        payload["generated_source_path"] = self.generated_java_agent_path
        payload["fitness"] = list(self.objective_vector()) if self.fitness_objectives else None
        return payload

