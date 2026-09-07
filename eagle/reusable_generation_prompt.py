"""Canonical reusable rule set for the evolvable Java-generation prompt."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


RULES_START_MARKER = "EAGLE_REUSABLE_RULES_START"
RULES_END_MARKER = "EAGLE_REUSABLE_RULES_END"
REUSABLE_PROMPT_HEADER = (
    "Translate the supplied policy into deterministic Java inside the editable "
    "strategy region. The separately supplied immutable scaffold, API guide, and "
    "final output contract always take priority."
)
MAX_REUSABLE_RULES = 10
MAX_RULE_CHARS = 240
RULE_DELTA_ADDITIONS = 1
RULE_DELTA_REMOVALS = 1
RULE_CATEGORIES: tuple[str, ...] = (
    "requirement_coverage",
    "priority_ordering",
    "role_assignment",
    "state_continuity",
    "targeting_fallback",
    "policy_grounding",
    "api_compliance",
)

_RULE_LINE = re.compile(
    r"^\[(?P<rule_id>[a-z0-9][a-z0-9-]{2,63})\]\s+"
    r"(?P<category>[a-z_]+)\s+\|\s+(?P<instruction>.+)$"
)
_JAVA_CALL = re.compile(r"\b[A-Za-z_$][A-Za-z0-9_$]*\s*\(")
_FORBIDDEN_RUNTIME_MECHANISM = re.compile(
    r"\b(?:loop|loops|poll|polling|schedule|scheduled|scheduling|queue|queued|"
    r"state machine|tracking|persistent state|state attributes?)\b",
    re.IGNORECASE,
)
_FORBIDDEN_IDLE_BYPASS = re.compile(
    r"\b(?:omit|omitting|skip|skipping|ignore|ignoring|bypass|bypassing)\b.{0,40}"
    r"\bidle(?:-friendly-unit)?\s+(?:check|checks|guard|guards|condition|conditions|state|states)\b|"
    r"\b(?:remove|removes|removing)\b.{0,40}"
    r"\bidle(?:-friendly-unit)?\s+(?:check|checks|guard|guards|condition|conditions|state|states)\b|"
    r"\bwithout\s+(?:relying\s+on|checking|requiring|using)\b.{0,40}"
    r"\bidle(?:-friendly-unit)?\s+(?:check|checks|guard|guards|condition|conditions|state|states)\b|"
    r"\bwithout\b.{0,64}\bidle(?:-friendly-unit)?\s+"
    r"(?:check|checks|guard|guards|condition|conditions|state|states)\b",
    re.IGNORECASE,
)
_FORBIDDEN_SPECIFIC_TERMS = (
    "allinbot",
    "agentcontext",
    "barracks",
    "candidateagent",
    "coac",
    "commandattack",
    "commandbuild",
    "commandharvest",
    "commandidle",
    "commandmove",
    "commandtrain",
    "base",
    "build",
    "defend",
    "harvest",
    "heavy",
    "heavy rush",
    "heavyrush",
    "light",
    "light rush",
    "lightrush",
    "mayari",
    "produce",
    "ranged",
    "resource",
    "tma",
    "train",
    "worker",
    "worker rush",
    "workerrush",
)
_FORBIDDEN_SPECIFIC_PATTERN = re.compile(
    r"\b(?:" + "|".join(
        sorted((re.escape(term) for term in _FORBIDDEN_SPECIFIC_TERMS), key=len, reverse=True)
    ) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReusableGenerationRule:
    rule_id: str
    category: str
    instruction: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "instruction": self.instruction,
        }


def parse_reusable_generation_rules(prompt: str) -> tuple[ReusableGenerationRule, ...]:
    """Parse a canonical prompt, treating legacy free-form prompts as no rules.

    Legacy prompts remain readable genotype values.  Their next successful Code
    Reflection canonicalizes them from the structured delta rather than copying
    policy-specific prose into the new rule set.
    """

    source = str(prompt or "").strip()
    start_count = source.count(RULES_START_MARKER)
    end_count = source.count(RULES_END_MARKER)
    if start_count == 0 and end_count == 0:
        return ()
    if start_count != 1 or end_count != 1:
        raise ValueError("Reusable generation prompt must contain one ordered rule-marker pair.")
    start = source.index(RULES_START_MARKER) + len(RULES_START_MARKER)
    end = source.index(RULES_END_MARKER)
    if start >= end:
        raise ValueError("Reusable generation prompt rule markers are out of order.")

    rules: list[ReusableGenerationRule] = []
    seen_ids: set[str] = set()
    for raw_line in source[start:end].splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _RULE_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"Invalid reusable generation rule line: {line!r}")
        rule = ReusableGenerationRule(
            rule_id=match.group("rule_id"),
            category=match.group("category"),
            instruction=_normalize_instruction(match.group("instruction")),
        )
        _validate_rule(rule.category, rule.instruction)
        if rule.rule_id in seen_ids:
            raise ValueError(f"Duplicate reusable generation rule id: {rule.rule_id}")
        seen_ids.add(rule.rule_id)
        rules.append(rule)
    if len(rules) > MAX_REUSABLE_RULES:
        raise ValueError(f"Reusable generation prompt exceeds {MAX_REUSABLE_RULES} rules.")
    return tuple(rules)


def reusable_rules_json(
    prompt: str,
    *,
    recover_invalid_current: bool = False,
) -> str:
    try:
        rules = parse_reusable_generation_rules(prompt)
    except ValueError as exc:
        if not recover_invalid_current:
            raise
        return json.dumps(
            {
                "validation_status": "invalid",
                "validation_error": str(exc),
                "recoverable_rules": [
                    rule.to_dict() for rule in _recover_valid_rules(prompt)
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return json.dumps(
        [rule.to_dict() for rule in rules],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def apply_reusable_rule_delta(
    current_prompt: str,
    payload: dict[str, object],
    *,
    recover_invalid_current: bool = False,
) -> str:
    """Validate and deterministically apply one Code-Rewriter rule delta."""

    if set(payload) != {"remove_rule_ids", "add_rules"}:
        raise ValueError(
            "Code Rewrite response must contain exactly remove_rule_ids and add_rules."
        )
    remove_rule_ids = payload["remove_rule_ids"]
    add_rules = payload["add_rules"]
    if not isinstance(remove_rule_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in remove_rule_ids
    ):
        raise ValueError("Code Rewrite remove_rule_ids must be an array of rule-id strings.")
    if not isinstance(add_rules, list):
        raise ValueError("Code Rewrite add_rules must be an array.")

    current_rules = list(
        _current_rules_for_rewrite(
            current_prompt,
            recover_invalid_current=recover_invalid_current,
        )
    )
    current_ids = {rule.rule_id for rule in current_rules}
    normalized_removals = [item.strip() for item in remove_rule_ids]
    if len(normalized_removals) != len(set(normalized_removals)):
        raise ValueError("Code Rewrite remove_rule_ids must not contain duplicates.")
    if len(normalized_removals) > RULE_DELTA_REMOVALS:
        raise ValueError(
            f"Code Rewrite remove_rule_ids may contain at most {RULE_DELTA_REMOVALS} rule."
        )
    unknown = [rule_id for rule_id in normalized_removals if rule_id not in current_ids]
    if unknown:
        raise ValueError(f"Code Rewrite cannot remove unknown rule ids: {unknown}")
    if len(add_rules) != RULE_DELTA_ADDITIONS:
        raise ValueError(
            f"Code Rewrite add_rules must contain exactly {RULE_DELTA_ADDITIONS} rule."
        )

    retained = [rule for rule in current_rules if rule.rule_id not in normalized_removals]
    known_instructions = {
        (rule.category, rule.instruction.casefold()) for rule in retained
    }
    additions: list[ReusableGenerationRule] = []
    for index, item in enumerate(add_rules):
        if not isinstance(item, dict) or set(item) != {"category", "instruction"}:
            raise ValueError(
                f"Code Rewrite add_rules[{index}] must contain exactly category and instruction."
            )
        category = item["category"]
        instruction = item["instruction"]
        if not isinstance(category, str) or not isinstance(instruction, str):
            raise ValueError("Code Rewrite rule category and instruction must be strings.")
        category = category.strip()
        instruction = _normalize_instruction(instruction)
        try:
            _validate_rule(category, instruction)
        except ValueError as exc:
            raise ValueError(f"Code Rewrite add_rules[{index}] is invalid: {exc}") from exc
        key = (category, instruction.casefold())
        if key in known_instructions:
            continue
        known_instructions.add(key)
        additions.append(
            ReusableGenerationRule(
                rule_id=_derived_rule_id(category, instruction),
                category=category,
                instruction=instruction,
            )
        )

    result = retained + additions
    if not normalized_removals and not additions:
        raise ValueError("Code Rewrite rule delta must make at least one effective change.")
    if not result:
        raise ValueError("Code Rewrite cannot remove every reusable generation rule.")
    if len(result) > MAX_REUSABLE_RULES:
        raise ValueError(
            f"Code Rewrite result exceeds the {MAX_REUSABLE_RULES}-rule limit."
        )
    ids = [rule.rule_id for rule in result]
    if len(ids) != len(set(ids)):
        raise ValueError("Code Rewrite produced duplicate deterministic rule ids.")
    return render_reusable_generation_prompt(tuple(result))


def render_reusable_generation_prompt(
    rules: tuple[ReusableGenerationRule, ...],
) -> str:
    if not rules:
        raise ValueError("Reusable generation prompt requires at least one rule.")
    lines = [REUSABLE_PROMPT_HEADER, "", RULES_START_MARKER]
    lines.extend(
        f"[{rule.rule_id}] {rule.category} | {rule.instruction}"
        for rule in rules
    )
    lines.append(RULES_END_MARKER)
    return "\n".join(lines)


def _derived_rule_id(category: str, instruction: str) -> str:
    digest = hashlib.sha256(
        f"{category}\0{instruction.casefold()}".encode("utf-8")
    ).hexdigest()[:12]
    return f"rule-{digest}"


def _current_rules_for_rewrite(
    prompt: str,
    *,
    recover_invalid_current: bool,
) -> tuple[ReusableGenerationRule, ...]:
    try:
        return parse_reusable_generation_rules(prompt)
    except ValueError:
        if not recover_invalid_current:
            raise
        # Older whole-prompt rewrites and previously accepted bad deltas may
        # leave one tainted rule among valid canonical rules. At an explicit
        # repair boundary, retain only rules that individually satisfy the
        # current contract; the validated addition then replaces the discarded
        # defect without erasing unrelated core translation invariants.
        return _recover_valid_rules(prompt)


def _recover_valid_rules(prompt: str) -> tuple[ReusableGenerationRule, ...]:
    """Recover individually valid canonical lines from an invalid prompt."""

    source = str(prompt or "").strip()
    if source.count(RULES_START_MARKER) != 1 or source.count(RULES_END_MARKER) != 1:
        return ()
    start = source.index(RULES_START_MARKER) + len(RULES_START_MARKER)
    end = source.index(RULES_END_MARKER)
    if start >= end:
        return ()

    recovered: list[ReusableGenerationRule] = []
    seen_ids: set[str] = set()
    for raw_line in source[start:end].splitlines():
        match = _RULE_LINE.fullmatch(raw_line.strip())
        if match is None:
            continue
        rule = ReusableGenerationRule(
            rule_id=match.group("rule_id"),
            category=match.group("category"),
            instruction=_normalize_instruction(match.group("instruction")),
        )
        try:
            _validate_rule(rule.category, rule.instruction)
        except ValueError:
            continue
        if rule.rule_id in seen_ids:
            continue
        seen_ids.add(rule.rule_id)
        recovered.append(rule)
        if len(recovered) == MAX_REUSABLE_RULES - RULE_DELTA_ADDITIONS:
            break
    return tuple(recovered)


def _normalize_instruction(value: str) -> str:
    return " ".join(str(value).strip().split())


def _validate_rule(category: str, instruction: str) -> None:
    if category not in RULE_CATEGORIES:
        raise ValueError(
            f"Reusable generation rule category must be one of {RULE_CATEGORIES}."
        )
    if len(instruction) < 12 or len(instruction) > MAX_RULE_CHARS:
        raise ValueError(
            f"Reusable generation rule has {len(instruction)} characters; "
            f"expected 12-{MAX_RULE_CHARS}."
        )
    forbidden_specific = _FORBIDDEN_SPECIFIC_PATTERN.search(instruction)
    if forbidden_specific:
        raise ValueError(
            "Reusable generation rules must not name a concrete strategy, unit type, "
            f"agent, or Java/API symbol; rejected term: {forbidden_specific.group(0)!r}."
        )
    if any(character in instruction for character in ("`", "{", "}", ";")) or _JAVA_CALL.search(instruction):
        raise ValueError("Reusable generation rules must be plain policy-agnostic prose, not Java.")
    runtime_claim = re.sub(
        r"\b(?:without|never|do\s+not|don't)\b.{0,64}"
        r"\b(?:loops?|polling|scheduling|queues?|state\s+machines?|tracking|"
        r"persistent\s+state|state\s+attributes?)\b",
        "",
        instruction,
        flags=re.IGNORECASE,
    )
    mechanism = _FORBIDDEN_RUNTIME_MECHANISM.search(runtime_claim)
    if mechanism:
        raise ValueError(
            "Reusable generation rules must describe translation invariants, not invented "
            f"runtime mechanisms; rejected term: {mechanism.group(0)!r}."
        )
    idle_bypass = _FORBIDDEN_IDLE_BYPASS.search(instruction)
    if idle_bypass:
        raise ValueError(
            "Reusable generation rules must preserve the idle-friendly-unit action guard; "
            f"rejected phrase: {idle_bypass.group(0)!r}."
        )
