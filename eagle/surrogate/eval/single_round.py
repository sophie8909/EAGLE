"""Single-round surrogate helpers that mirror EAGLE.java's LLM call shape."""

from __future__ import annotations


def build_eagle_round_prompt(base_prompt: str, dynamic_prompt_text: str) -> str:
    """Build the same prompt shape that EAGLE.java sends to Ollama for one round."""
    normalized_base = str(base_prompt or "").strip()
    normalized_dynamic = str(dynamic_prompt_text or "").strip()
    if not normalized_base:
        return normalized_dynamic
    if not normalized_dynamic:
        return normalized_base
    return f"{normalized_base}\n\n{normalized_dynamic}\n"

