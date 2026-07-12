"""Canonical signatures for the six evolvable Java modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleMethodContract:
    method_name: str
    return_type: str
    parameters: tuple[tuple[str, str], ...]

    @property
    def parameter_types(self) -> tuple[str, ...]:
        return tuple(parameter_type for parameter_type, _ in self.parameters)

    @property
    def declaration(self) -> str:
        parameters = ", ".join(f"{parameter_type} {name}" for parameter_type, name in self.parameters)
        return f"private {self.return_type} {self.method_name}({parameters})"


MODULE_METHOD_CONTRACTS: dict[str, ModuleMethodContract] = {
    "controller": ModuleMethodContract("decide", "Decision", (("AgentContext", "context"),)),
    "economy": ModuleMethodContract("economy", "List<ActionProposal>", (("AgentContext", "context"),)),
    "combat": ModuleMethodContract("combat", "List<ActionProposal>", (("AgentContext", "context"),)),
    "expansion": ModuleMethodContract("expansion", "List<ActionProposal>", (("AgentContext", "context"),)),
    "target_selection": ModuleMethodContract(
        "selectTarget",
        "Unit",
        (("AgentContext", "context"), ("Unit", "actor"), ("List<Unit>", "candidates")),
    ),
    "path_selection": ModuleMethodContract(
        "findPath",
        "PathChoice",
        (("AgentContext", "context"), ("Unit", "unit"), ("int", "targetX"), ("int", "targetY")),
    ),
}
