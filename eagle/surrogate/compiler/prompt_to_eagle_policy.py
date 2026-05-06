"""Compile MicroRTS strategy prompts into the fixed eaglePolicy schema."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, TypedDict


class Policy(TypedDict):
    """A validated fixed policy for eaglePolicy evaluation."""

    strategy_identity: str
    opening_plan: str
    unit_preference: str
    attack_timing: str


ALLOWED_VALUES: dict[str, tuple[str, ...]] = {
    "strategy_identity": ("economic", "aggressive", "balanced", "defensive"),
    "opening_plan": ("worker_first", "barracks_first", "harvest_first"),
    "unit_preference": ("worker", "light", "heavy", "ranged", "balanced"),
    "attack_timing": ("early", "mid", "late"),
}

DEFAULT_POLICY: Policy = {
    "strategy_identity": "balanced",
    "opening_plan": "harvest_first",
    "unit_preference": "balanced",
    "attack_timing": "mid",
}

COMPILER_PROMPT_TEMPLATE = """You are a strategy compiler for MicroRTS.

Your task is to convert a natural-language strategy prompt into a fixed policy schema.

Choose exactly one value for each field.

Allowed values:
- strategy_identity: economic, aggressive, balanced, defensive
- opening_plan: worker_first, barracks_first, harvest_first
- unit_preference: worker, light, heavy, ranged, balanced
- attack_timing: early, mid, late

Rules:
- Use only the allowed values.
- Do not invent new fields.
- Do not output explanations.
- If the strategy prompt does not clearly specify a field, choose the default neutral value.
- Compress mixed or conditional strategies into a single dominant policy.
- Return JSON only.

Default values:
- strategy_identity = balanced
- opening_plan = harvest_first
- unit_preference = balanced
- attack_timing = mid

Strategy prompt:
{{STRATEGY_PROMPT}}

Return exactly this JSON shape:
{
  "strategy_identity": "...",
  "opening_plan": "...",
  "unit_preference": "...",
  "attack_timing": "..."
}
"""


def build_compiler_prompt(strategy_prompt: str) -> str:
    """Build the strict compiler prompt used for LLM-based policy compilation."""

    return COMPILER_PROMPT_TEMPLATE.replace("{{STRATEGY_PROMPT}}", strategy_prompt)


def validate_policy(policy: Mapping[str, Any] | None) -> Policy:
    """Return a fully valid policy with only the fixed schema fields."""

    validated: dict[str, str] = {}
    source = policy or {}

    for field_name, allowed_values in ALLOWED_VALUES.items():
        # Validation is intentionally field-local so malformed inputs can be repaired deterministically.
        value = source.get(field_name)
        if value in allowed_values:
            validated[field_name] = str(value)
        else:
            validated[field_name] = DEFAULT_POLICY[field_name]

    return Policy(**validated)


def _parse_llm_policy(raw_response: Any) -> Mapping[str, Any]:
    """Parse a JSON-like LLM response into a mapping."""

    # Accepting an already parsed mapping keeps integration simple for callers with custom LLM clients.
    if isinstance(raw_response, Mapping):
        return raw_response
    if isinstance(raw_response, str):
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Return whether the normalized prompt contains any keyword."""

    return any(keyword in text for keyword in keywords)


def _compile_rule_based(prompt: str) -> Policy:
    """Compile a policy using deterministic keyword heuristics."""

    # Normalize spacing once so substring checks stay simple and deterministic.
    normalized = " ".join(prompt.lower().split())
    policy: dict[str, str] = dict(DEFAULT_POLICY)

    # The first matching identity wins to compress mixed prompts into one dominant label.
    if _contains_any(
        normalized,
        ("economic", "economy", "expand", "greed", "greedy", "macro"),
    ):
        policy["strategy_identity"] = "economic"
    elif _contains_any(
        normalized,
        ("aggressive", "aggression", "pressure", "rush", "attack quickly", "all-in"),
    ):
        policy["strategy_identity"] = "aggressive"
    elif _contains_any(
        normalized,
        ("defensive", "defend", "defense", "safe", "safely", "protect", "turtle"),
    ):
        policy["strategy_identity"] = "defensive"

    if _contains_any(
        normalized,
        ("worker first", "workers first", "more workers", "expand economy first"),
    ):
        policy["opening_plan"] = "worker_first"
    elif _contains_any(
        normalized,
        ("barracks first", "military quickly", "build military quickly", "rush"),
    ):
        policy["opening_plan"] = "barracks_first"
    elif _contains_any(
        normalized,
        ("harvest first", "harvest", "gather resources", "collect resources"),
    ):
        policy["opening_plan"] = "harvest_first"

    if _contains_any(normalized, ("workers only", "worker rush", "worker swarm")):
        policy["unit_preference"] = "worker"
    elif _contains_any(
        normalized,
        (
            "light",
            "fast units",
            "cheap units",
            "mobile units",
            "military quickly",
            "build military quickly",
        ),
    ):
        policy["unit_preference"] = "light"
    elif _contains_any(normalized, ("heavy", "armored", "tanky units")):
        policy["unit_preference"] = "heavy"
    elif _contains_any(normalized, ("ranged", "archer", "distance units")):
        policy["unit_preference"] = "ranged"

    # Late cues are checked before early cues so phrases like "avoid early attacks" stay late-oriented.
    if _contains_any(
        normalized,
        ("late", "later", "avoid early attacks", "only attack later", "attack later"),
    ):
        policy["attack_timing"] = "late"
    elif _contains_any(
        normalized,
        ("as early as possible", "early attack", "rush", "pressure early", "attack early"),
    ):
        policy["attack_timing"] = "early"
    elif _contains_any(normalized, ("mid game", "midgame", "mid-game")):
        policy["attack_timing"] = "mid"

    return validate_policy(policy)


def compile_prompt_to_policy(
    prompt: str,
    llm_callable: Callable[[str], Any] | None = None,
) -> Policy:
    """Compile a natural-language strategy prompt into a validated fixed policy."""

    if llm_callable is None:
        return _compile_rule_based(prompt)

    compiler_prompt = build_compiler_prompt(prompt)
    raw_response = llm_callable(compiler_prompt)
    parsed_policy = _parse_llm_policy(raw_response)
    return validate_policy(parsed_policy)


def _demo() -> None:
    """Print a few compiled policies for quick manual inspection."""

    sample_prompts = [
        "Expand economy first and avoid early attacks.",
        "Build military quickly and pressure the enemy as early as possible.",
        "Play safely, defend your base, and only attack later.",
        "Play efficiently and defeat the opponent.",
    ]

    for prompt in sample_prompts:
        policy = compile_prompt_to_policy(prompt)
        print(json.dumps({"prompt": prompt, "policy": policy}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    _demo()
