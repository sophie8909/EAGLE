"""Prompt-hash cache for aggressiveness LLM judgments."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from eagle.logging import trace
from eagle.objectives.aggressiveness.llm_judge import judge_aggressiveness


_JUDGMENT_CACHE: dict[str, dict[str, Any]] = {}


def judge_aggressiveness_cached(
    prompt_text: str,
    *,
    model: str,
    temperature: float,
    run_dir: str | Path | None = None,
    generation: int | str | None = None,
    final_score: float | None = None,
) -> dict[str, Any]:
    """Return an aggressiveness judgment cached by static prompt hash."""
    prompt_hash = _prompt_hash(prompt_text)
    cached = _JUDGMENT_CACHE.get(prompt_hash)
    if cached is not None:
        result = dict(cached)
        result["cache_hit"] = True
        _record_judgment(run_dir, generation, prompt_hash, result, final_score)
        return result

    judgment = judge_aggressiveness(
        prompt_text,
        model=model,
        temperature=temperature,
        debug_log_dir=str(run_dir) if run_dir is not None else None,
        debug_context={"generation": generation, "mode": "aggressiveness_judge"},
    )
    result = {
        "raw_response": str(judgment.get("raw_response", "")),
        "parsed_json": {
            key: value
            for key, value in judgment.items()
            if key != "raw_response"
        },
        "cache_hit": False,
    }
    _JUDGMENT_CACHE[prompt_hash] = dict(result)
    _record_judgment(run_dir, generation, prompt_hash, result, final_score)
    return dict(result)


def clear_aggressiveness_cache() -> None:
    """Clear process-local aggressiveness judgments."""
    _JUDGMENT_CACHE.clear()


def _record_judgment(
    run_dir: str | Path | None,
    generation: int | str | None,
    prompt_hash: str,
    result: dict[str, Any],
    final_score: float | None,
) -> None:
    """Record one aggressiveness judgment trace row."""
    if run_dir is None:
        return
    trace.record(
        "aggressiveness_judgment",
        {
            "generation": "unknown" if generation is None else generation,
            "prompt_hash": prompt_hash,
            "raw_response": result.get("raw_response", ""),
            "parsed_json": dict(result.get("parsed_json") or {}),
            "final_score": final_score,
            "cache_hit": bool(result.get("cache_hit")),
        },
        {"log_dir": run_dir, "generation": "unknown" if generation is None else generation},
    )


def _prompt_hash(prompt_text: str) -> str:
    """Return a stable hash for one static prompt."""
    return hashlib.sha256(str(prompt_text or "").encode("utf-8")).hexdigest()
