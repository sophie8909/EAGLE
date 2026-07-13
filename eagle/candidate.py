"""Candidate representation for evolved EAGLE individuals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


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
    "Generate one complete, compilable CandidateAgent.java source file. "
    "Return the entire Java file from the package declaration through the final class brace. "
    "Return raw Java only: no markdown fence, JSON wrapper, explanation, placeholder, ellipsis, or omitted section. "
    "Preserve the package, class name, lifecycle methods, strategy-region comments, six action helpers, lookup helpers, and imports. "
    "Implement the marked strategy region with deterministic Java and do not call network, file, subprocess, environment, or runtime LLM APIs."
)


@dataclass(frozen=True)
class Candidate:
    """One NSGA-II individual that generates one complete Java agent."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    generation: int = 0
    parent_ids: tuple[str, ...] = ()
    strategy_prompt: str = ""
    previous_code: str = ""
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
    generated_java_agent_path: str | None = None
    compile_status: str = "pending"
    game_eval_result: dict[str, Any] = field(default_factory=dict)
    code_quality_result: dict[str, Any] = field(default_factory=dict)
    fitness_objectives: dict[str, float] = field(default_factory=dict)
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)

    def objective_vector(self) -> tuple[float, ...]:
        if not self.fitness_objectives:
            return (0.0, 0.0)
        return (
            float(self.fitness_objectives.get("game_performance", 0.0)),
            float(self.fitness_objectives.get("code_quality", 0.0)),
        )

    def generation_input(self, *, class_name: str = "", module_name: str = "controller") -> str:
        """Build one request for a complete single-file Java agent."""
        from generation.agent_template import (
            JavaTemplatePaths,
            STRATEGY_END_MARKER,
            STRATEGY_START_MARKER,
            load_java_template,
        )

        previous_source = self.previous_code.strip()
        if (
            previous_source.startswith("package ai.generated;")
            and STRATEGY_START_MARKER in previous_source
            and STRATEGY_END_MARKER in previous_source
        ):
            current_source = previous_source
        else:
            current_source = load_java_template(JavaTemplatePaths())
        return f"""Generate the complete Java source file for CandidateAgent.

Overall strategy:
{self.strategy_prompt.strip()}

The editable strategy implementation is the single region between the
EAGLE_AGENT_STRATEGY_START and EAGLE_AGENT_STRATEGY_END comments.
You may freely add, remove, or reorganize strategy helper methods inside that region.
Use the fixed action helpers marked by EAGLE_ACTION_HELPERS_START and
EAGLE_ACTION_HELPERS_END to operate the Agent.

{ACTION_API_GUIDE}

Generation requirements:
{self.generation_prompt.strip()}

Start from this complete known-good source. Return the complete revised Java file, including every unchanged section:

```java
{current_source}
```
FINAL OUTPUT CONTRACT (highest priority):
Your response must contain one complete CandidateAgent.java file and nothing else.
The first non-whitespace text must be package ai.generated; and the final non-whitespace character must be the class closing brace.
Never return JSON, a functions object, individual method bodies, a patch, an explanation, or Markdown fences."""

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_ids"] = list(self.parent_ids)
        return payload
