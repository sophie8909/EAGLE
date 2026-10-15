"""Finite, versioned strategy gene grammar; Java generation implements its semantics."""
import hashlib
import json
import math
import re

VERSION = "eagle-strategy-dsl-v1"
REFERENCE_AGENTS = {"WorkerRush"}
UNIT_TYPES = {"Worker", "Base", "Barracks", "Light", "Heavy", "Ranged"}
MOBILE = {"Worker", "Light", "Heavy", "Ranged"}
MAX_CHARS = 16000


class StrategyJSONLExtractionError(ValueError):
    """A rule stream had no usable policy; ``report`` retains discard evidence."""

    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _json_object(text):
    value = json.loads(text, object_pairs_hook=_unique_json_object)
    return value if isinstance(value, dict) else None


def extract_strategy_jsonl_record(response, *, field_name):
    """Return one complete JSON/JSONL record carrying ``field_name``.

    A whole JSON object remains the preferred compatibility shape.  If prose or
    fence lines surround the answer, each non-empty line is instead treated as
    an independent JSONL record.  Non-JSON and non-object lines are ignored;
    duplicate JSON fields, zero matching records, and multiple matching records
    are rejected.  Parsing is deliberately field-targeted so an echoed parent
    policy cannot be selected as the proposed child policy.
    """
    text = str(response).lstrip("\ufeff").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", text, flags=re.IGNORECASE)
    whole = fenced.group(1) if fenced else text
    try:
        payload = _json_object(whole)
    except json.JSONDecodeError:
        payload = None
    if payload is not None:
        return payload if field_name in payload else None

    matches = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            payload = _json_object(line)
        except json.JSONDecodeError:
            continue
        if payload is not None and field_name in payload:
            matches.append((line_number, payload))
    if len(matches) > 1:
        lines = ", ".join(str(line_number) for line_number, _ in matches)
        raise ValueError(
            f"strategy response contains multiple JSONL records for {field_name}: lines {lines}"
        )
    return matches[0][1] if matches else None


def strategy_dsl_source_from_record(payload, *, field_name):
    """Decode a strategy field, accepting the new object form and legacy string form."""
    if field_name not in payload:
        raise ValueError(f"strategy response must contain {field_name}")
    value = payload[field_name]
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"strategy response {field_name} must be non-empty")
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise ValueError(f"strategy response {field_name} must be a JSON object or serialized JSON string")


def extract_strategy_rule_jsonl(response, *, field_name, max_rules=32):
    """Assemble one policy from independently validated JSONL rule records.

    Each ``strategy_rule`` record is validated independently for the requested
    role field.  Direct rule objects are accepted as a compact compatibility
    form.  Invalid lines and invalid rules are reported and omitted; the
    response fails only when no complete legal rule remains.  ``None`` means
    the response did not use this record format and allows the legacy
    whole-object parser to run.
    """
    text = str(response).lstrip("\ufeff").strip()
    valid_rules = []
    valid_rule_lines = []
    discarded = []
    metadata = {}
    metadata_line = None
    recognized = False
    bounded_max_rules = min(max_rules, 32)

    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = _json_object(line)
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            if '"record_type"' in line and '"strategy_rule"' in line:
                recognized = True
            discarded.append({
                "line": line_number,
                "reason": f"invalid_json: {exc}",
            })
            continue
        if record is None:
            discarded.append({"line": line_number, "reason": "not_a_json_object"})
            continue

        record_type = record.get("record_type")
        if record_type == "coach_metadata":
            recognized = True
            if metadata_line is not None:
                discarded.append({"line": line_number, "reason": "duplicate_coach_metadata"})
                continue
            invalid_metadata = []
            for key in ("strategy_changes", "strategy_signature"):
                if key not in record:
                    continue
                if not isinstance(record[key], dict):
                    invalid_metadata.append(key)
                    continue
                metadata[key] = record[key]
            if invalid_metadata:
                discarded.append({
                    "line": line_number,
                    "reason": "invalid_coach_metadata_fields: " + ",".join(invalid_metadata),
                })
            metadata_line = line_number
            continue

        direct_rule = set(record) == {"actor", "when", "action"}
        if record_type != "strategy_rule" and not direct_rule:
            discarded.append({"line": line_number, "reason": "not_a_strategy_record"})
            continue
        recognized = True
        if direct_rule:
            rule = record
        else:
            if record.get("field") != field_name:
                discarded.append({"line": line_number, "reason": "wrong_strategy_field"})
                continue
            if set(record) != {"record_type", "field", "rule"}:
                discarded.append({"line": line_number, "reason": "invalid_strategy_rule_record_fields"})
                continue
            rule = record["rule"]
        if len(valid_rules) >= bounded_max_rules:
            discarded.append({"line": line_number, "reason": "strategy_rule_limit_exceeded"})
            continue
        try:
            validate_strategy_dsl({"version": VERSION, "rules": [rule]})
            normalize_strategy_dsl({
                "version": VERSION,
                "rules": [*valid_rules, rule],
            })
        except (RecursionError, ValueError) as exc:
            discarded.append({"line": line_number, "reason": str(exc)})
            continue
        valid_rules.append(rule)
        valid_rule_lines.append(line_number)

    if not recognized:
        return None
    if not valid_rules:
        report = {
            "schema_version": "eagle-strategy-rule-extraction-v1",
            "status": "failed",
            "mode": "rule_records",
            "field_name": field_name,
            "metadata_line": metadata_line,
            "valid_rule_count": 0,
            "valid_rule_lines": [],
            "discarded_line_count": len(discarded),
            "discarded_lines": discarded,
            "raw_response_sha256": hashlib.sha256(str(response).encode("utf-8")).hexdigest(),
            "extracted_strategy_sha256": None,
            "canonical_strategy_sha256": None,
        }
        raise StrategyJSONLExtractionError(
            "strategy JSONL contains no valid rules",
            report,
        )

    strategy_source = normalize_strategy_dsl({
        "version": VERSION,
        "rules": valid_rules,
    })
    payload = dict(metadata)
    payload[field_name] = strategy_source
    report = {
        "schema_version": "eagle-strategy-rule-extraction-v1",
        "status": "partial" if discarded else "complete",
        "mode": "rule_records",
        "field_name": field_name,
        "metadata_line": metadata_line,
        "valid_rule_count": len(valid_rules),
        "valid_rule_lines": valid_rule_lines,
        "discarded_line_count": len(discarded),
        "discarded_lines": discarded,
        "raw_response_sha256": hashlib.sha256(str(response).encode("utf-8")).hexdigest(),
        "extracted_strategy_sha256": hashlib.sha256(strategy_source.encode("utf-8")).hexdigest(),
        "canonical_strategy_sha256": hashlib.sha256(strategy_source.encode("utf-8")).hexdigest(),
    }
    return payload, strategy_source, report


def strategy_extraction_report(response, strategy_source, *, field_name, mode):
    """Build the audit record for a legacy whole-object extraction."""
    try:
        canonical = normalize_strategy_dsl(strategy_source)
        valid_rule_count = len(validate_strategy_dsl(canonical)["rules"])
    except (RecursionError, ValueError):
        canonical = None
        valid_rule_count = None
    return {
        "schema_version": "eagle-strategy-rule-extraction-v1",
        "status": "complete" if canonical is not None else "unvalidated",
        "mode": mode,
        "field_name": field_name,
        "metadata_line": None,
        "valid_rule_count": valid_rule_count,
        "valid_rule_lines": [],
        "discarded_line_count": 0,
        "discarded_lines": [],
        "raw_response_sha256": hashlib.sha256(str(response).encode("utf-8")).hexdigest(),
        "extracted_strategy_sha256": hashlib.sha256(strategy_source.encode("utf-8")).hexdigest(),
        "canonical_strategy_sha256": (
            hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if canonical is not None
            else None
        ),
    }


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
        try:
            data = json.loads(source, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("strategy_prompt must be versioned JSON strategy DSL") from exc
    else:
        data = source
    _fields(data, {"version", "rules"}, {"reference_agent"})
    _choice(data["version"], {VERSION})
    if "reference_agent" in data:
        _choice(data["reference_agent"], REFERENCE_AGENTS)
        if data["rules"] != []:
            raise ValueError("reference policies must have an empty rules list")
        return data
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


def normalize_strategy_dsl(
    source, *, max_chars=MAX_CHARS, max_rules=32, allow_reference=True,
):
    """Canonical JSON preserves rule priority and unit-type lists."""
    validated = validate_strategy_dsl(source, max_chars=max_chars, max_rules=max_rules)
    if not allow_reference and "reference_agent" in validated:
        raise ValueError("reference_agent is reserved for checked-in configured seeds")
    return json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def worker_rush_reference_policy():
    """Policy that materializes the vendored canonical MicroRTS WorkerRush."""
    return normalize_strategy_dsl({
        "version": VERSION,
        "rules": [],
        "reference_agent": "WorkerRush",
    })


def worker_rush_policy(worker_limit=1):
    """Deterministic WorkerRush-like rule policy used by mocks and examples."""
    def target(owner, types):
        return {"kind": "entity", "owner": owner, "types": types, "selector": "nearest"}
    rules = [{"actor": "Base", "when": True, "action": {"type": "train", "unit": "Worker", "target": {"kind": "cell", "selector": "first_free_adjacent"}}}]
    for action in ("return", "harvest"):
        rules.append({"actor": "Worker", "when": {"compare": {"metric": "actor_id_rank", "op": "<", "value": worker_limit}}, "action": {"type": action, "target": target("friendly" if action == "return" else "neutral", ["Base" if action == "return" else "Resource"])}})
    rules.append({"actor": "Worker", "when": True, "action": {"type": "engage", "target": target("enemy", ["Base"])}})
    rules.append({"actor": "Worker", "when": True, "action": {"type": "engage", "target": target("enemy", sorted(UNIT_TYPES))}})
    return normalize_strategy_dsl({"version": VERSION, "rules": rules})
