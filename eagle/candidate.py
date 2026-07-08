"""Candidate representation for evolved EAGLE individuals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


DEFAULT_GENERATION_PROMPT = (
    "Requested class name: {class_name}\n\n"
    "Generate only Java statements for the body of chooseAction(int player, GameState gs). "
    "Return raw Java statements only. No markdown, no explanation, no code fences. "
    "Do not output a package declaration, imports, class declaration, constructors, fields, or helper methods. "
    "Start from the RandomAI behavior shown in the scaffold: create PlayerActionGenerator(gs, player) "
    "and return pag.getRandom(). "
    "Do not define helper methods, do not invent helper methods, and never call nearestIdleAlly. "
    "Do not invent action APIs. "
    "Do not redeclare local variables in the same method, "
    "reuse existing variables or choose unique names, "
    "do not assign UnitType values to Unit variables, "
    "do not use custom imports, Optional, StrategyTable, streams, or lambdas, "
    "prefer the simple MicroRTS API usage shown in the template, "
    "and do not call any network, file, subprocess, environment, or LLM API at runtime."
)


@dataclass(frozen=True)
class Candidate:
    """One NSGA-II individual with explicit prompt/code parts.

    The strategy prompt is the evolvable natural-language strategy. Previous code is reference
    Java carried from the selected parent after evaluation. The generation prompt is the fixed
    instruction that tells the LLM how to turn the strategy and reference code into Java.
    """

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    generation: int = 0
    parent_ids: tuple[str, ...] = ()
    strategy_prompt: str = ""
    previous_code: str = ""
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
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

    def generation_input(self, *, class_name: str = "") -> str:
        """Build the LLM input in the fixed EAGLE order."""

        generation_prompt = self.generation_prompt.replace("{class_name}", class_name)
        previous_code = self.previous_code.strip() or "(empty)"
        return (
            f"Strategy prompt:\n{self.strategy_prompt.strip()}\n\n"
            f"Previous Java code:\n{previous_code}\n\n"
            f"Generation prompt:\n{generation_prompt.strip()}"
        )

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_ids"] = list(self.parent_ids)
        return payload
