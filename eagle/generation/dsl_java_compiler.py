"""Deterministic, offline Strategy DSL to CandidateAgent Java compiler."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from eagle.generation.agent_template import (
    STRATEGY_END_MARKER, STRATEGY_START_MARKER,
    extract_strategy_region, fixed_scaffold_equivalent, strategy_contract_errors,
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
        "            commandPlannedAction(actor, new rts.UnitAction(rts.UnitAction.TYPE_NONE, 10), context);",
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
    if compiler_version != "eagle-dsl-java-v1":
        raise ValueError("unsupported compiler_version")
    if scaffold.count(STRATEGY_START_MARKER) != 1 or scaffold.count(STRATEGY_END_MARKER) != 1:
        raise ValueError("scaffold requires exactly one ordered strategy marker pair")
    start = scaffold.index(STRATEGY_START_MARKER) + len(STRATEGY_START_MARKER)
    end = scaffold.index(STRATEGY_END_MARKER)
    if start >= end:
        raise ValueError("scaffold strategy markers are out of order")
    if "private boolean commandPlannedAction(Unit actor, UnitAction action, AgentContext context)" not in scaffold or "private boolean commandReturn(Unit worker, Unit base, AgentContext context, UnitAction planned)" not in scaffold or "final ResourceUsage reservations;" not in scaffold:
        raise ValueError("scaffold lacks the deterministic planned-action API")
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
        extract_strategy_region(source), source, _hash(source),
    )

_JAVA_HELPERS = r"""
    private static final class DslPlan {
        final int kind;
        final rts.UnitAction action;
        final Unit target;
        DslPlan(int kind, rts.UnitAction action, Unit target) {
            this.kind = kind;
            this.action = action;
            this.target = target;
        }
    }

    private DslPlan dslIdlePlan() {
        return new DslPlan(0, null, null);
    }

    private long dslHash(AgentContext context, Unit actor) {
        return ((long) context.gs.getTime()) * 31L
                + ((long) context.player) * 17L + actor.getID() * 13L;
    }

    private int dslActorRank(AgentContext context, Unit actor) {
        int rank = 0;
        for (Unit other : context.units) {
            if (other.getPlayer() == context.player && other.getType() == actor.getType()
                    && other.getID() < actor.getID()) rank++;
        }
        return rank;
    }

    private boolean dslMatches(Unit unit, int owner, UnitType[] types, int player) {
        boolean ownership = owner == 0 ? unit.getPlayer() == player
                : owner == 1 ? unit.getPlayer() >= 0 && unit.getPlayer() != player
                : unit.getPlayer() < 0;
        if (!ownership) return false;
        for (UnitType type : types) if (unit.getType() == type) return true;
        return false;
    }

    private int dslManhattan(Unit a, Unit b) {
        return Math.abs(a.getX() - b.getX()) + Math.abs(a.getY() - b.getY());
    }

    private int dslCount(AgentContext context, Unit actor, int owner, UnitType[] types, double radius) {
        int count = 0;
        for (Unit other : context.units) {
            if (dslMatches(other, owner, types, context.player)
                    && (radius < 0 || dslManhattan(actor, other) <= radius)) count++;
        }
        return count;
    }

    private double dslDistance(AgentContext context, Unit actor, int owner, UnitType[] types) {
        double best = Double.POSITIVE_INFINITY;
        for (Unit other : context.units) {
            if (dslMatches(other, owner, types, context.player))
                best = Math.min(best, dslManhattan(actor, other));
        }
        return best;
    }

    private int dslPosition(AgentContext context, int x, int y) {
        return x + y * context.gs.getPhysicalGameState().getWidth();
    }

    private boolean dslLegal(AgentContext context, Unit actor, DslPlan plan) {
        if (plan == null) return false;
        if (plan.kind == 0) return true;
        if (!actor.canExecuteAction(plan.action, context.gs)
                || !context.gs.isUnitActionAllowed(actor, plan.action)) return false;
        return context.reservations.consistentWith(
                plan.action.resourceUsage(actor, context.gs.getPhysicalGameState()), context.gs);
    }

    private DslPlan dslPrimitive(AgentContext context, Unit actor, int kind,
            rts.UnitAction action, Unit target) {
        if (action == null) return null;
        DslPlan plan = new DslPlan(kind, action, target);
        return dslLegal(context, actor, plan) ? plan : null;
    }

    private rts.UnitAction dslPath(AgentContext context, Unit actor, Unit target, int range) {
        int position = dslPosition(context, target.getX(), target.getY());
        return pf.findPathToPositionInRange(actor, position, range,
                context.gs, context.reservations);
    }

    private int dslDirection(Unit actor, Unit target) {
        int dx = target.getX() - actor.getX();
        int dy = target.getY() - actor.getY();
        if (dx == 0 && dy == -1) return rts.UnitAction.DIRECTION_UP;
        if (dx == 1 && dy == 0) return rts.UnitAction.DIRECTION_RIGHT;
        if (dx == 0 && dy == 1) return rts.UnitAction.DIRECTION_DOWN;
        if (dx == -1 && dy == 0) return rts.UnitAction.DIRECTION_LEFT;
        return -1;
    }
"""

_JAVA_HELPERS += r"""
    private DslPlan dslPlanEntity(AgentContext context, Unit actor, int kind, Unit target) {
        rts.UnitAction action;
        if (kind == 1 || kind == 2) {
            if (actor.getType() != workerType || (kind == 1 ? actor.getResources() != 0
                    : actor.getResources() <= 0)) return null;
            int direction = dslDirection(actor, target);
            if (direction >= 0) action = new rts.UnitAction(
                    kind == 1 ? rts.UnitAction.TYPE_HARVEST : rts.UnitAction.TYPE_RETURN, direction);
            else action = dslPath(context, actor, target, 1);
        } else if (kind == 3 || kind == 4) {
            if (!actor.getType().canAttack) return null;
            int dx = target.getX() - actor.getX();
            int dy = target.getY() - actor.getY();
            boolean inRange = ((long) dx * dx + (long) dy * dy)
                    <= ((long) actor.getType().attackRange * actor.getType().attackRange);
            if (inRange) action = new rts.UnitAction(rts.UnitAction.TYPE_ATTACK_LOCATION,
                    target.getX(), target.getY());
            else if (kind == 4) action = dslPath(context, actor, target, actor.getType().attackRange);
            else return null;
        } else if (kind == 5) {
            if (!actor.getType().canMove || target == actor || dslManhattan(actor, target) <= 1)
                return null;
            action = dslPath(context, actor, target, 1);
        } else return null;
        return dslPrimitive(context, actor, kind, action, target);
    }

    private DslPlan dslSelectEntity(AgentContext context, Unit actor,
            int kind, int owner, UnitType[] types, int selector) {
        java.util.List<DslPlan> legal = new java.util.ArrayList<>();
        for (Unit target : context.units) {
            if (!dslMatches(target, owner, types, context.player)) continue;
            DslPlan plan = dslPlanEntity(context, actor, kind, target);
            if (plan != null) legal.add(plan);
        }
        if (legal.isEmpty()) return null;
        legal.sort((a, b) -> {
            int value = 0;
            if (selector == 0 || selector == 1) {
                value = Integer.compare(dslManhattan(actor, a.target), dslManhattan(actor, b.target));
                if (selector == 1) value = -value;
            } else if (selector == 2 || selector == 3) {
                value = Integer.compare(a.target.getHitPoints(), b.target.getHitPoints());
                if (selector == 3) value = -value;
            }
            return value != 0 ? value : Long.compare(a.target.getID(), b.target.getID());
        });
        int index = selector == 5
                ? (int) Math.floorMod(dslHash(context, actor), (long) legal.size()) : 0;
        return legal.get(index);
    }

    private DslPlan dslSelectCell(AgentContext context, Unit actor,
            int kind, UnitType unitType, int selector) {
        java.util.List<DslPlan> legal = new java.util.ArrayList<>();
        for (int y = actor.getY() - 1; y <= actor.getY() + 1; y++) {
            for (int x = actor.getX() - 1; x <= actor.getX() + 1; x++) {
                if (Math.abs(x - actor.getX()) + Math.abs(y - actor.getY()) != 1
                        || !isFreeCell(context, x, y)) continue;
                int direction = x < actor.getX() ? rts.UnitAction.DIRECTION_LEFT
                        : x > actor.getX() ? rts.UnitAction.DIRECTION_RIGHT
                        : y < actor.getY() ? rts.UnitAction.DIRECTION_UP
                        : rts.UnitAction.DIRECTION_DOWN;
                rts.UnitAction action = kind == 5
                        ? new rts.UnitAction(rts.UnitAction.TYPE_MOVE, direction)
                        : new rts.UnitAction(rts.UnitAction.TYPE_PRODUCE, direction, unitType);
                DslPlan plan = dslPrimitive(context, actor, kind, action, null);
                if (plan != null) legal.add(plan);
            }
        }
        if (legal.isEmpty()) return null;
        int index = selector == 0 ? 0
                : (int) Math.floorMod(dslHash(context, actor), (long) legal.size());
        return legal.get(index);
    }

    private DslPlan dslChoose(AgentContext context, Unit actor, DslPlan[] options) {
        java.util.List<DslPlan> legal = new java.util.ArrayList<>();
        for (DslPlan option : options) if (dslLegal(context, actor, option)) legal.add(option);
        return legal.isEmpty() ? null
                : legal.get((int) Math.floorMod(dslHash(context, actor), (long) legal.size()));
    }

    private boolean dslIssue(AgentContext context, Unit actor, DslPlan plan) {
        if (!dslLegal(context, actor, plan)) return false;
        if (plan.kind == 0) return commandPlannedAction(actor, new rts.UnitAction(rts.UnitAction.TYPE_NONE, 10), context);
        if (plan.kind == 2) return commandReturn(actor, plan.target, context, plan.action);
        return commandPlannedAction(actor, plan.action, context);
    }
"""
