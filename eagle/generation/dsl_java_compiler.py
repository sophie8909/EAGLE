"""Deterministic, offline Strategy DSL to CandidateAgent Java compiler."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from eagle.generation.agent_template import (
    STRATEGY_END_MARKER, STRATEGY_START_MARKER,
    fixed_scaffold_equivalent, strategy_contract_errors,
)
from eagle.strategy_dsl import normalize_strategy_dsl, validate_strategy_dsl


@dataclass(frozen=True)
class EntitySet:
    owner: Literal["friendly", "enemy", "neutral"]
    types: tuple[str, ...]


@dataclass(frozen=True)
class EntityTarget:
    entities: EntitySet
    selector: str


@dataclass(frozen=True)
class CellTarget:
    selector: str


@dataclass(frozen=True)
class Condition:
    operator: str
    children: tuple[Condition, ...] = ()
    metric: str | None = None
    comparison: str | None = None
    value: int | float | None = None
    entities: EntitySet | None = None
    radius: int | float | None = None


@dataclass(frozen=True)
class Action:
    kind: str
    target: EntityTarget | CellTarget | None = None
    unit: str | None = None
    options: tuple[Action, ...] = ()


@dataclass(frozen=True)
class Rule:
    actor: str
    condition: Condition
    action: Action


@dataclass(frozen=True)
class CompiledDslJava:
    normalized_policy: str
    policy_sha256: str
    compiler_version: str
    scaffold_sha256: str
    strategy_region: str
    complete_source: str
    source_sha256: str
    diagnostics: tuple[str, ...] = ()


_UNIT = {
    "Worker": "workerType", "Base": "baseType", "Barracks": "barracksType",
    "Light": "lightType", "Heavy": "heavyType", "Ranged": "rangedType",
    "Resource": "resourceType",
}
_OWNER = {"friendly": 0, "enemy": 1, "neutral": 2}
_SELECTOR = {
    "nearest": 0, "farthest": 1, "lowest_hp": 2,
    "highest_hp": 3, "lowest_id": 4, "hashed": 5,
}
_KIND = {
    "idle": 0, "harvest": 1, "return": 2, "attack": 3,
    "engage": 4, "move": 5, "build": 6, "train": 7,
}


def _hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _entity_set(data: dict) -> EntitySet:
    return EntitySet(data["owner"], tuple(data["types"]))


def _condition(data: object) -> Condition:
    if isinstance(data, bool):
        return Condition("true" if data else "false")
    assert isinstance(data, dict)
    operator, body = next(iter(data.items()))
    if operator in ("all", "any"):
        return Condition(operator, tuple(_condition(item) for item in body))
    if operator == "not":
        return Condition(operator, (_condition(body),))
    assert operator == "compare" and isinstance(body, dict)
    return Condition(
        operator, metric=body["metric"], comparison=body["op"], value=body["value"],
        entities=_entity_set(body["entities"]) if "entities" in body else None,
        radius=body.get("radius"),
    )


def _action(data: dict) -> Action:
    kind = data["type"]
    if kind == "choose":
        return Action(kind, options=tuple(_action(item) for item in data["options"]))
    target = data.get("target")
    if target is not None:
        if target["kind"] == "cell":
            target = CellTarget(target["selector"])
        else:
            target = EntityTarget(_entity_set(target), target["selector"])
    return Action(kind, target=target, unit=data.get("unit"))


def _rules(data: dict) -> tuple[Rule, ...]:
    return tuple(Rule(item["actor"], _condition(item["when"]), _action(item["action"]))
                 for item in data["rules"])


def _types(entities: EntitySet) -> str:
    return "new UnitType[]{" + ", ".join(_UNIT[item] for item in entities.types) + "}"


def _number(value: int | float) -> str:
    return repr(value) if isinstance(value, float) else str(value)


def _condition_java(node: Condition) -> str:
    if node.operator in ("true", "false"):
        return node.operator
    if node.operator in ("all", "any"):
        joiner = " && " if node.operator == "all" else " || "
        return "(" + joiner.join(_condition_java(child) for child in node.children) + ")"
    if node.operator == "not":
        return "!(" + _condition_java(node.children[0]) + ")"
    assert node.operator == "compare"
    metric = node.metric
    if metric == "stockpile":
        left = "context.gs.getPlayer(context.player).getResources()"
    elif metric == "time":
        left = "context.gs.getTime()"
    elif metric == "actor_hp":
        left = "actor.getHitPoints()"
    elif metric == "actor_resources":
        left = "actor.getResources()"
    elif metric == "actor_id_rank":
        left = "dslActorRank(context, actor)"
    else:
        assert node.entities is not None
        args = f"context, actor, {_OWNER[node.entities.owner]}, {_types(node.entities)}"
        if metric == "count":
            radius = "-1.0" if node.radius is None else _number(node.radius)
            left = f"dslCount({args}, {radius})"
        else:
            left = f"dslDistance({args})"
    return f"({left} {node.comparison} {_number(node.value)})"


def _action_java(node: Action) -> str:
    if node.kind == "choose":
        options = ", ".join(_action_java(option) for option in node.options)
        return f"dslChoose(context, actor, new DslPlan[]{{{options}}})"
    if node.kind == "idle":
        return "dslIdlePlan()"
    assert node.target is not None
    kind = _KIND[node.kind]
    if isinstance(node.target, EntityTarget):
        target = node.target
        return (
            f"dslSelectEntity(context, actor, {kind}, {_OWNER[target.entities.owner]}, "
            f"{_types(target.entities)}, {_SELECTOR[target.selector]})"
        )
    unit = "null" if node.unit is None else _UNIT[node.unit]
    selector = 0 if node.target.selector == "first_free_adjacent" else 1
    return f"dslSelectCell(context, actor, {kind}, {unit}, {selector})"


def _emit_rules(rules: tuple[Rule, ...]) -> str:
    lines = [
        "    private void decide(AgentContext context) {",
        "        actions.clear();",
        "        java.util.List<Unit> actors = new java.util.ArrayList<>(context.units);",
        "        actors.sort((a, b) -> Long.compare(a.getID(), b.getID()));",
        "        for (Unit actor : actors) {",
        "            if (!isIdleAlly(actor, context)) continue;",
        "            if (dslDecideActor(context, actor)) continue;",
        "            commandIdle(actor);",
        "        }",
        "    }",
        "",
        "    private boolean dslDecideActor(AgentContext context, Unit actor) {",
    ]
    for index, rule in enumerate(rules):
        lines += [
            f"        if (actor.getType() == {_UNIT[rule.actor]} && {_condition_java(rule.condition)}) {{",
            f"            DslPlan plan = dslRule{index}(context, actor);",
            "            if (plan != null && dslIssue(context, actor, plan)) return true;",
            "        }",
        ]
    lines += ["        return false;", "    }", ""]
    for index, rule in enumerate(rules):
        lines += [
            f"    private DslPlan dslRule{index}(AgentContext context, Unit actor) {{",
            f"        return {_action_java(rule.action)};",
            "    }", "",
        ]
    return "\n".join(lines)


def compile_strategy_dsl(
    policy: str | dict, *, scaffold: str,
    compiler_version: str = "eagle-dsl-java-v1",
) -> CompiledDslJava:
    """Compile finite, typed policy nodes into fixed Java methods and helpers."""
    if not isinstance(scaffold, str):
        raise TypeError("scaffold must be complete Java source text")
    if not isinstance(compiler_version, str) or not compiler_version:
        raise ValueError("compiler_version must be a nonempty string")
    if scaffold.count(STRATEGY_START_MARKER) != 1 or scaffold.count(STRATEGY_END_MARKER) != 1:
        raise ValueError("scaffold requires exactly one ordered strategy marker pair")
    start = scaffold.index(STRATEGY_START_MARKER) + len(STRATEGY_START_MARKER)
    end = scaffold.index(STRATEGY_END_MARKER)
    if start >= end:
        raise ValueError("scaffold strategy markers are out of order")
    normalized = normalize_strategy_dsl(policy)
    rules = _rules(validate_strategy_dsl(normalized))
    region = _emit_rules(rules) + _JAVA_HELPERS
    source = scaffold[:start] + "\n" + region.rstrip() + "\n    " + scaffold[end:]
    if not fixed_scaffold_equivalent(source, scaffold):
        raise ValueError("compiled source changed fixed scaffold")
    errors = strategy_contract_errors(source)
    if errors:
        raise ValueError("compiled strategy violates Java contract: " + "; ".join(errors))
    return CompiledDslJava(
        normalized, _hash(normalized), compiler_version, _hash(scaffold),
        region, source, _hash(source),
    )
