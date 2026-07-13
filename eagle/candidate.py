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
    "controller": "Coordinate the economy, expansion, and combat behavior functions.",
    "economy": "Assign idle Workers to harvest or explicitly idle them when harvesting is impossible.",
    "combat": "Select enemy targets and issue attack or idle commands for allied combat-capable units.",
    "expansion": "Train units and build production structures when resources and idle producers allow it.",
    "target_selection": "Choose a valid enemy target from the provided unit snapshot.",
    "path_selection": "Choose a reachable target coordinate for commandMove.",
}

DEFAULT_MODULE_BODIES: dict[str, str] = {
    "controller": "economy(context);\nexpansion(context);\ncombat(context);",
    "economy": (
        "Unit base = ownBase(context);\n"
        "for (Unit unit : context.units) {\n"
        "    if (!isIdleAlly(unit, context) || unit.getType() != workerType) {\n"
        "        continue;\n"
        "    }\n"
        "    Unit resource = nearestResource(unit, context);\n"
        "    if (resource != null && base != null) {\n"
        "        commandHarvest(unit, resource, base);\n"
        "    } else {\n"
        "        commandIdle(unit);\n"
        "    }\n"
        "}"
    ),
    "combat": (
        "for (Unit unit : context.units) {\n"
        "    if (!isIdleAlly(unit, context) || !unit.getType().canAttack) {\n"
        "        continue;\n"
        "    }\n"
        "    Unit target = selectTarget(context, unit, context.units);\n"
        "    if (target != null) {\n"
        "        commandAttack(unit, target);\n"
        "    } else {\n"
        "        commandIdle(unit);\n"
        "    }\n"
        "}"
    ),
    "expansion": (
        "int resources = context.gs.getPlayer(context.player).getResources();\n"
        "for (Unit unit : context.units) {\n"
        "    if (!isIdleAlly(unit, context)) {\n"
        "        continue;\n"
        "    }\n"
        "    if (unit.getType() == baseType && resources >= workerType.cost) {\n"
        "        commandTrain(unit, workerType);\n"
        "        return;\n"
        "    }\n"
        "    if (unit.getType() == barracksType && resources >= lightType.cost) {\n"
        "        commandTrain(unit, lightType);\n"
        "        return;\n"
        "    }\n"
        "}"
    ),
    "target_selection": (
        "Unit best = null;\n"
        "int bestDistance = Integer.MAX_VALUE;\n"
        "for (Unit candidate : candidates) {\n"
        "    if (candidate.getPlayer() < 0 || candidate.getPlayer() == context.player) {\n"
        "        continue;\n"
        "    }\n"
        "    int distance = Math.abs(candidate.getX() - actor.getX())\n"
        "            + Math.abs(candidate.getY() - actor.getY());\n"
        "    if (distance < bestDistance) {\n"
        "        best = candidate;\n"
        "        bestDistance = distance;\n"
        "    }\n"
        "}\n"
        "return best;"
    ),
    "path_selection": "return new PathChoice(targetX, targetY);",
}

ACTION_API_GUIDE = """Fixed action helpers already implemented in CandidateAgent.java:
- commandMove(Unit unit, int x, int y)
- commandHarvest(Unit worker, Unit resource, Unit base)
- commandTrain(Unit producer, UnitType unitType)
- commandBuild(Unit worker, UnitType buildingType, int x, int y)
- commandAttack(Unit attacker, Unit target)
- commandIdle(Unit unit)

Fixed lookup helpers:
- isIdleAlly(Unit unit, AgentContext context)
- nearestEnemy(Unit source, AgentContext context)
- nearestResource(Unit source, AgentContext context)
- ownBase(AgentContext context)

AgentContext exposes context.player, context.gs, and the snapshot context.units.
Known UnitType fields are resourceType, workerType, lightType, heavyType, rangedType, baseType, and barracksType."""

DEFAULT_GENERATION_PROMPT = (
    "Generate one JSON object containing every required function body. "
    "Return only JSON with a functions object: no markdown fences and no explanation. "
    "Each value must be a Java method body string, not a complete method declaration or nested body object. "
    "Do not output package declarations, imports, classes, constructors, fields, or helper methods. "
    "Use only the fixed action and lookup helpers shown in the prompt; do not invent helper methods. "
    "Do not assemble PlayerAction directly and do not call network, file, subprocess, environment, or LLM APIs at runtime."
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
    code_quality_result: dict[str, Any] = field(default_factory=dict)
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
            float(self.fitness_objectives.get("code_quality", 0.0)),
        )

    def generation_input(self, *, class_name: str = "", module_name: str = "controller") -> str:
        """Build one request for the complete single-file behavior-function collection."""
        declarations = "\n".join(
            f'- "{name}": body for `{contract.declaration}`'
            for name, contract in MODULE_METHOD_CONTRACTS.items()
        )
        previous = "\n".join(f"[{name}]\n{self.module_bodies[name]}" for name in MODULE_NAMES)
        return f"""Candidate class: {class_name}

Overall strategy:
{self.strategy_prompt.strip()}

Required keys and fixed method slots in the single CandidateAgent.java file:
{declarations}

{ACTION_API_GUIDE}

Previous complete function set:
{previous}

Generation guidance:
{self.generation_prompt.strip()}

Regenerate all required function bodies together. Return only JSON shaped as {{"functions": {{...}}}}."""

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_ids"] = list(self.parent_ids)
        return payload