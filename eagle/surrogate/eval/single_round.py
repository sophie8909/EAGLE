"""Single-round surrogate helpers that mirror EAGLE.java's LLM call shape."""

from __future__ import annotations

from typing import Any

from ...utils.llm import LLM
from ...utils.move_validator import score_game_round_response


def build_eagle_round_prompt(base_prompt: str, dynamic_prompt_text: str) -> str:
    """Build the same prompt shape that EAGLE.java sends to Ollama for one round."""
    normalized_base = str(base_prompt or "").strip()
    normalized_dynamic = str(dynamic_prompt_text or "").strip()
    if not normalized_base:
        return normalized_dynamic
    if not normalized_dynamic:
        return normalized_base
    return f"{normalized_base}\n\n{normalized_dynamic}\n"


def generate_eagle_round_response(
    base_prompt: str,
    dynamic_prompt_text: str,
) -> dict[str, Any] | None:
    """Call Ollama with an EAGLE-style single-round prompt and parse one JSON response."""
    final_prompt = build_eagle_round_prompt(base_prompt, dynamic_prompt_text)
    # EAGLE.java prepends `/no_think` before calling `/api/generate`.
    return LLM.ollama_generate_json_response(f"/no_think {final_prompt}")


def evaluate_eagle_single_round(
    base_prompt: str,
    dynamic_prompt_text: str,
) -> dict[str, Any]:
    """Run one EAGLE-style single-round helper call and score its move quality."""
    llm_response = generate_eagle_round_response(base_prompt, dynamic_prompt_text)
    score = score_game_round_response(llm_response, dynamic_prompt_text)
    return {
        "final_prompt": build_eagle_round_prompt(base_prompt, dynamic_prompt_text),
        "llm_response": llm_response,
        "response_score": float(score),
    }

