"""Finite, versioned strategy gene grammar; Java generation implements its semantics."""
import json
import math

VERSION = "eagle-strategy-dsl-v1"
UNIT_TYPES = {"Worker", "Base", "Barracks", "Light", "Heavy", "Ranged"}
MOBILE = {"Worker", "Light", "Heavy", "Ranged"}
MAX_CHARS = 16000


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError(f"expected fields {sorted(required)}, optional {sorted(optional)}")


def _choice(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"invalid value {value!r}; expected {sorted(choices)}")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1000000 or not math.isfinite(value):
        raise ValueError("numeric value must be finite and within +/-1000000")


def _entities(value):
    _fields(value, {"owner", "types"})
    _choice(value["owner"], {"friendly", "enemy", "neutral"})
    types = value["types"]
    if not isinstance(types, list) or not types or len(types) > 6:
        raise ValueError("types must be a nonempty unique unit-type list")
    allowed = {"Resource"} if value["owner"] == "neutral" else UNIT_TYPES
    for unit in types:
        _choice(unit, allowed)
    if len(set(types)) != len(types):
        raise ValueError("types must be unique")


def _condition(value, depth=0):
    if depth > 6:
        raise ValueError("condition depth exceeds 6")
    if isinstance(value, bool):
        return
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("condition requires one operator")
    key, body = next(iter(value.items()))
    if key in {"all", "any"}:
        if not isinstance(body, list) or not 1 <= len(body) <= 8:
            raise ValueError("boolean operator requires 1..8 conditions")
        for item in body:
            _condition(item, depth + 1)
    elif key == "not":
        _condition(body, depth + 1)
    elif key == "compare":
        _fields(body, {"metric", "op", "value"}, {"entities", "radius"})
        _choice(body["op"], {"<", "<=", "==", "!=", ">=", ">"})
        _number(body["value"])
        _choice(body["metric"], {"stockpile", "time", "actor_hp", "actor_resources", "actor_id_rank", "count", "distance"})
        if body["metric"] in {"count", "distance"}:
            if "entities" not in body:
                raise ValueError("count/distance requires entities")
            _entities(body["entities"])
        elif "entities" in body or "radius" in body:
            raise ValueError("entities/radius only apply to count/distance")
        if "radius" in body:
            if body["metric"] != "count":
                raise ValueError("radius applies only to count")
            _number(body["radius"])
            if body["radius"] < 0:
                raise ValueError("radius must be nonnegative")
    else:
        raise ValueError(f"unknown condition {key}")


def _target(value, kind):
    if kind == "cell":
        _fields(value, {"kind", "selector"})
        _choice(value["kind"], {"cell"})
        _choice(value["selector"], {"first_free_adjacent", "hashed_free_adjacent"})
    else:
        _fields(value, {"kind", "owner", "types", "selector"})
        _choice(value["kind"], {"entity"})
        _entities({"owner": value["owner"], "types": value["types"]})
        _choice(value["selector"], {"nearest", "farthest", "lowest_hp", "highest_hp", "lowest_id", "hashed"})


def _action(action, actor):
    if isinstance(action, dict) and action.get("type") == "choose":
        _fields(action, {"type", "options"})
        if not isinstance(action["options"], list) or not 1 <= len(action["options"]) <= 8:
            raise ValueError("choose requires 1..8 action options")
        for option in action["options"]:
            if isinstance(option, dict) and option.get("type") == "choose":
                raise ValueError("nested choose is prohibited")
            _action(option, actor)
        return
    _fields(action, {"type"}, {"target", "unit"})
    kind = action["type"]
    allowed = {"idle"}
    if actor in MOBILE:
        allowed |= {"move", "attack", "engage"}
    if actor == "Worker":
        allowed |= {"harvest", "return", "build"}
    if actor in {"Base", "Barracks"}:
        allowed.add("train")
    _choice(kind, allowed)
    if kind == "idle":
        _fields(action, {"type"})
        return
    if kind in {"build", "train"}:
        _fields(action, {"type", "unit", "target"})
        units = {"Base", "Barracks"} if kind == "build" else ({"Worker"} if actor == "Base" else {"Light", "Heavy", "Ranged"})
        _choice(action["unit"], units)
        _target(action["target"], "cell")
        return
    _fields(action, {"type", "target"})
    target = action["target"]
    if kind == "move" and isinstance(target, dict) and target.get("kind") == "cell":
        _target(target, "cell")
        return
    _target(target, "entity")
    if kind == "harvest":
        if target["owner"] != "neutral" or target["types"] != ["Resource"]:
            raise ValueError("harvest target must be neutral Resource")
    elif kind == "return":
        if target["owner"] != "friendly" or target["types"] != ["Base"]:
            raise ValueError("return target must be friendly Base")
    elif target["owner"] == "neutral" or (kind in {"attack", "engage"} and target["owner"] != "enemy"):
        raise ValueError("combat targets must be enemy; Resource is harvest-only")


def validate_strategy_dsl(source, *, max_chars=MAX_CHARS, max_rules=32):
    """Return validated policy data, rejecting legacy prose and unknown grammar."""
    max_chars = min(max_chars, MAX_CHARS)
    max_rules = min(max_rules, 32)
    if isinstance(source, str):
        if len(source) > max_chars:
            raise ValueError("strategy DSL exceeds size limit")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON field {key}")
                result[key] = value
            return result
        try:
            data = json.loads(source, object_pairs_hook=unique)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("strategy_prompt must be versioned JSON strategy DSL") from exc
    else:
        data = source
    _fields(data, {"version", "rules"})
    _choice(data["version"], {VERSION})
    if not isinstance(data["rules"], list) or len(data["rules"]) > max_rules:
        raise ValueError(f"rules must be a list of at most {max_rules} rules")
    for rule in data["rules"]:
        _fields(rule, {"actor", "when", "action"})
        actor = rule["actor"]
        _choice(actor, UNIT_TYPES)
        _condition(rule["when"])
        _action(rule["action"], actor)
    if len(json.dumps(data, separators=(",", ":"), sort_keys=True)) > max_chars:
        raise ValueError("strategy DSL exceeds size limit")
    return data


def normalize_strategy_dsl(source, *, max_chars=MAX_CHARS, max_rules=32):
    """Canonical JSON preserves rule priority and unit-type lists."""
    return json.dumps(validate_strategy_dsl(source, max_chars=max_chars, max_rules=max_rules), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def worker_rush_policy(worker_limit=1):
    """Deterministic mock and seed policy with one economic Worker."""
    def target(owner, types):
        return {"kind": "entity", "owner": owner, "types": types, "selector": "nearest"}
    rules = [{"actor": "Base", "when": True, "action": {"type": "train", "unit": "Worker", "target": {"kind": "cell", "selector": "first_free_adjacent"}}}]
    for action in ("return", "harvest"):
        rules.append({"actor": "Worker", "when": {"compare": {"metric": "actor_id_rank", "op": "<", "value": worker_limit}}, "action": {"type": action, "target": target("friendly" if action == "return" else "neutral", ["Base" if action == "return" else "Resource"])}})
    rules.append({"actor": "Worker", "when": True, "action": {"type": "engage", "target": target("enemy", ["Base"])}})
    rules.append({"actor": "Worker", "when": True, "action": {"type": "engage", "target": target("enemy", sorted(UNIT_TYPES))}})
    return normalize_strategy_dsl({"version": VERSION, "rules": rules})
