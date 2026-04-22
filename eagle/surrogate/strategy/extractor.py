"""Extract constrained strategy slots from a natural-language prompt."""

from __future__ import annotations

from ...utils.llm import LLM


EXTRACTION_SYSTEM_PROMPT = (
    "You are converting a high-level RTS strategy into structured decision rules.\n\n"
    "Output STRICT JSON only.\n\n"
    "Each field must contain short pseudo-code or rule description.\n\n"
    "Focus on:\n"
    "- worker behavior\n"
    "- production logic\n"
    "- combat targeting\n"
    "- defense reactions\n\n"
    "DO NOT include explanations."
)

REQUIRED_FIELDS = (
    "worker_rule",
    "base_rule",
    "barracks_rule",
    "combat_rule",
    "defense_rule",
    "strategy_identity",
)

VALID_IDENTITIES = {"aggressive", "economic", "balanced"}


def _fallback_strategy() -> dict[str, str]:
    """Return a conservative fallback strategy when extraction fails."""
    return {
        "worker_rule": "Harvest nearby resources and avoid idle time.",
        "base_rule": "Train workers steadily when resources allow.",
        "barracks_rule": "Train combat units conservatively when affordable.",
        "combat_rule": "Attack the nearest vulnerable enemy unit.",
        "defense_rule": "Protect the base when enemies are nearby.",
        "strategy_identity": "balanced",
    }


def _normalize_strategy(raw_strategy: dict | None) -> dict[str, str]:
    """Clamp one raw extraction result into the required strict slot schema."""
    fallback = _fallback_strategy()
    if not isinstance(raw_strategy, dict):
        return fallback

    normalized: dict[str, str] = {}
    for field_name in REQUIRED_FIELDS:
        value = raw_strategy.get(field_name, fallback[field_name])
        text = str(value).strip()
        normalized[field_name] = text if text else fallback[field_name]

    identity = normalized["strategy_identity"].lower()
    normalized["strategy_identity"] = identity if identity in VALID_IDENTITIES else "balanced"
    return normalized


def extract_strategy(prompt: str) -> dict:
    """
    Convert prompt into structured strategy slots using LLM.
    """
    extraction_prompt = (
        f"{EXTRACTION_SYSTEM_PROMPT}\n\n"
        "Return exactly this JSON shape:\n"
        "{\n"
        '  "worker_rule": "...",\n'
        '  "base_rule": "...",\n'
        '  "barracks_rule": "...",\n'
        '  "combat_rule": "...",\n'
        '  "defense_rule": "...",\n'
        '  "strategy_identity": "aggressive | economic | balanced"\n'
        "}\n\n"
        f"Strategy prompt:\n{prompt}"
    )
    return _normalize_strategy(LLM.ollama_generate_strict_json(extraction_prompt))
