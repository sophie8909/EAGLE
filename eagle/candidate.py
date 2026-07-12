"""Candidate representation for evolved EAGLE individuals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from .module_contract import MODULE_METHOD_CONTRACTS


MODULE_NAMES: tuple[str, ...] = (
    "controller",
    "economy",
    "combat",
    "expansion",
    "target_selection",
    "path_selection",
)

DEFAULT_MODULE_PROMPTS: dict[str, str] = {
    "controller": "Decide how to combine economy, combat, expansion, target, and path proposals.",
    "economy": "Propose simple economy actions such as waiting, harvesting, or keeping units available.",
    "combat": "Propose simple combat priorities without directly issuing MicroRTS actions.",
    "expansion": "Propose simple expansion or production priorities without direct action assembly.",
    "target_selection": "Choose a target unit from a provided candidate list.",
    "path_selection": "Choose a target location for a unit.",
}

DEFAULT_MODULE_BODIES: dict[str, str] = {
    "controller": (
        "private Decision decide(AgentContext context) {\n"
        "    Decision decision = new Decision();\n"
        "    decision.proposals.addAll(economy(context));\n"
        "    decision.proposals.addAll(expansion(context));\n"
        "    decision.proposals.addAll(combat(context));\n"
        "    return decision;\n"
        "}"
    ),
    "economy": "private List<ActionProposal> economy(AgentContext context) {\n    return new ArrayList<>();\n}",
    "combat": "private List<ActionProposal> combat(AgentContext context) {\n    return new ArrayList<>();\n}",
    "expansion": "private List<ActionProposal> expansion(AgentContext context) {\n    return new ArrayList<>();\n}",
    "target_selection": ("private Unit selectTarget(AgentContext context, Unit actor, List<Unit> candidates) {\n" "    return candidates.isEmpty() ? null : candidates.get(0);\n}"),
    "path_selection": ("private PathChoice findPath(AgentContext context, Unit unit, int targetX, int targetY) {\n" "    return new PathChoice(targetX, targetY);\n}"),
}

DEFAULT_GENERATION_PROMPT = (
    "Requested class name: {class_name}\n"
    "Requested module: {module_name}\n\n"
    "Generate exactly one complete Java method declaration for the requested module. "
    "Return only that raw Java method: no markdown fences and no explanation. "
    "Do not output a package declaration, imports, class declaration, constructors, fields, or helper methods. "
    "Do not define helper methods, do not invent helper methods, and never call nearestIdleAlly. "
    "Do not directly assemble PlayerAction objects; return structured Decision, ActionProposal, Unit, or PathChoice values. "
    "Do not redeclare local variables in the same method, "
    "reuse existing variables or choose unique names, "
    "do not assign UnitType values to Unit variables, "
    "do not use custom imports, Optional, StrategyTable, streams, or lambdas, "
    "prefer the simple MicroRTS API usage shown in the template, "
    "and do not call any network, file, subprocess, environment, or LLM API at runtime."
)


@dataclass(frozen=True)
class Candidate:
    """One NSGA-II individual with six evolvable Java function modules."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    generation: int = 0
    parent_ids: tuple[str, ...] = ()
    strategy_prompt: str = ""
    previous_code: str = ""
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
    module_prompts: dict[str, str] = field(default_factory=dict)
    module_bodies: dict[str, str] = field(default_factory=dict)
    generated_java_agent_path: str | None = None
    compile_status: str = "pending"
    game_eval_result: dict[str, Any] = field(default_factory=dict)
    strategy_alignment_result: dict[str, Any] = field(default_factory=dict)
    fitness_objectives: dict[str, float] = field(default_factory=dict)
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        prompts = {name: DEFAULT_MODULE_PROMPTS[name] for name in MODULE_NAMES}
        prompts.update(self.module_prompts)
        if self.strategy_prompt:
            prompts["controller"] = self.strategy_prompt

        bodies = {name: DEFAULT_MODULE_BODIES[name] for name in MODULE_NAMES}
        bodies.update({key: value for key, value in self.module_bodies.items() if key in MODULE_NAMES})
        object.__setattr__(self, "module_prompts", prompts)
        object.__setattr__(self, "module_bodies", bodies)

    def objective_vector(self) -> tuple[float, ...]:
        if not self.fitness_objectives:
            return (0.0, 0.0)
        return (
            float(self.fitness_objectives.get("game_performance", 0.0)),
            float(self.fitness_objectives.get("strategy_alignment", 0.0)),
        )

    def generation_input(self, *, class_name: str = "", module_name: str = "controller") -> str:
        """Build one function-generation prompt for a single evolvable module."""

        generation_prompt = self.generation_prompt.replace("{class_name}", class_name).replace(
            "{module_name}", module_name
        )
        existing_body = self.module_bodies.get(module_name, "").strip() or "(empty)"
        required_declaration = MODULE_METHOD_CONTRACTS[module_name].declaration
        return (
            f"Module name:\n{module_name}\n\n"
            f"Required method declaration (must match exactly):\n{required_declaration}\n\n"
            f"Module prompt:\n{self.module_prompts.get(module_name, '').strip()}\n\n"
            f"Previous module body:\n{existing_body}\n\n"
            f"Generation prompt:\n{generation_prompt.strip()}"
        )

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_ids"] = list(self.parent_ids)
        return payload
