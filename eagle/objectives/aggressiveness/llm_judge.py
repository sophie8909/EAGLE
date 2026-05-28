"""LLM judge for static strategic aggressiveness."""

from __future__ import annotations

import json
from typing import Any

from eagle.llm import LLM


AGGRESSIVENESS_JUDGE_FIELDS = (
    "attack_priority",
    "early_pressure",
    "economy_sacrifice",
    "expansion_risk",
    "unit_commitment",
)


def judge_aggressiveness(
    prompt_text: str,
    *,
    model: str = "local",
    temperature: float = 0.0,
    debug_log_dir: str | None = None,
    debug_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Judge static prompt aggressiveness from strategy tendency only."""
    judge_prompt = _build_judge_prompt(prompt_text)
    raw_output = LLM.llama_cpp_generate_text(
        prompt=judge_prompt,
        model=model,
        temperature=temperature,
        debug_log_dir=debug_log_dir,
        debug_context={**dict(debug_context or {}), "mode": "aggressiveness_judge"},
    )
    parsed = json.loads(raw_output)
    if not isinstance(parsed, dict):
        raise ValueError("Aggressiveness judge response must be a JSON object.")
    return normalize_aggressiveness_judgment(parsed, raw_response=raw_output)


def normalize_aggressiveness_judgment(parsed: dict[str, Any], *, raw_response: str = "") -> dict[str, Any]:
    """Clamp and validate one strict aggressiveness judge response."""
    normalized = {field: _clamp01(parsed.get(field, 0.0)) for field in AGGRESSIVENESS_JUDGE_FIELDS}
    evidence = parsed.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("Aggressiveness judge evidence must be a list.")
    normalized["evidence"] = [str(item) for item in evidence]
    normalized["raw_response"] = raw_response
    return normalized


def _build_judge_prompt(prompt_text: str) -> str:
    """Build the deterministic static-strategy judge prompt."""
    return f"""
You judge only the static strategy tendency in an RTS prompt.
Do not use gameplay outcomes, match scores, traces, or imagined results.
Return strict JSON only, with exactly these fields:
{{
  "attack_priority": 0.0,
  "early_pressure": 0.0,
  "economy_sacrifice": 0.0,
  "expansion_risk": 0.0,
  "unit_commitment": 0.0,
  "evidence": []
}}

Scoring rules:
- Every numeric field must be in [0, 1].
- attack_priority: direct preference for attacking enemy units, bases, or production.
- early_pressure: preference for early harassment, rushes, or tempo pressure.
- economy_sacrifice: willingness to trade economy/harvesting for aggression.
- expansion_risk: willingness to expand, expose units, or take map-control risk.
- unit_commitment: willingness to commit combat units instead of waiting defensively.
- evidence must contain short phrases from the prompt, not gameplay outcomes.

Static prompt:
{prompt_text}
""".strip()


def _clamp01(value: Any) -> float:
    """Clamp one numeric judge value to [0, 1]."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
