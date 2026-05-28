"""Runtime wiring for strategic aggressiveness metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from eagle.logging import trace
from eagle.objectives.aggressiveness.cache import judge_aggressiveness_cached
from eagle.objectives.aggressiveness.component_priors import compute_component_aggressiveness


def maybe_add_aggressiveness_metrics(
    eval_result: dict[str, Any],
    *,
    individual: Any,
    config: Any,
    run_dir: str | Path | None,
    generation: int | None,
) -> None:
    """Add aggressiveness metrics when the configured MO objective needs them."""
    if not _should_compute(config):
        return
    prompt = str(eval_result.get("prompt", "") or getattr(individual, "rendered_prompt", "") or "")
    component_score = compute_component_aggressiveness(individual)
    mode = str(getattr(config, "aggressiveness_mode", "hybrid") or "hybrid").strip().lower()
    component_weight = _clamp01(getattr(config, "aggressiveness_component_weight", 0.7))
    llm_weight = _clamp01(getattr(config, "aggressiveness_llm_weight", 0.3))
    llm_score = 0.0
    judgment: dict[str, Any] = {}

    if mode in {"llm_only", "hybrid"} and prompt:
        try:
            cached = judge_aggressiveness_cached(
                prompt,
                model=str(getattr(config, "aggressiveness_judge_model", "local") or "local"),
                temperature=float(getattr(config, "aggressiveness_judge_temperature", 0.0) or 0.0),
                run_dir=run_dir,
                generation=generation,
            )
            judgment = dict(cached.get("parsed_json") or {})
            llm_score = _llm_score(judgment)
        except (OSError, ValueError, TypeError, requests.RequestException) as exc:
            mode = "component_only"
            eval_result["aggressiveness_judge_error"] = repr(exc)
            trace.record(
                "aggressiveness_judgment",
                {
                    "generation": "unknown" if generation is None else generation,
                    "error": repr(exc),
                    "final_score": component_score,
                    "cache_hit": False,
                },
                {"log_dir": run_dir, "generation": "unknown" if generation is None else generation},
            )

    final_score = _final_score(
        mode=mode,
        component_score=component_score,
        llm_score=llm_score,
        component_weight=component_weight,
        llm_weight=llm_weight,
    )
    eval_result.update(
        {
            "aggressiveness_mode": mode,
            "aggressiveness_component_weight": component_weight,
            "aggressiveness_llm_weight": llm_weight,
            "aggressiveness_component_score": component_score,
            "aggressiveness_llm_score": llm_score,
            "aggressiveness_judgment": judgment,
            "strategic_aggressiveness": final_score,
        }
    )
    trace.record(
        "aggressiveness_judgment",
        {
            "generation": "unknown" if generation is None else generation,
            "parsed_json": judgment,
            "final_score": final_score,
            "cache_hit": None,
            "fallback_component_only": mode == "component_only" and not judgment,
        },
        {"log_dir": run_dir, "generation": "unknown" if generation is None else generation},
    )


def _should_compute(config: Any) -> bool:
    """Return whether strategic aggressiveness is active for this run."""
    if not bool(getattr(config, "aggressiveness_objective_enabled", False)):
        return False
    algorithm = str(getattr(config, "algorithm", "") or "").strip().lower()
    if algorithm in {"ga", "ga_surrogate"}:
        return False
    objective_config = dict(getattr(config, "objective_config", {}) or {})
    objectives = {str(item) for item in objective_config.get("objectives", [])}
    return "strategic_aggressiveness" in objectives


def _final_score(
    *,
    mode: str,
    component_score: float,
    llm_score: float,
    component_weight: float,
    llm_weight: float,
) -> float:
    """Compute final strategic aggressiveness in [0, 1]."""
    if mode == "component_only":
        return _clamp01(component_score)
    if mode == "llm_only":
        return _clamp01(llm_score)
    total = component_weight + llm_weight
    if total <= 0.0:
        component_weight, llm_weight, total = 0.7, 0.3, 1.0
    return _clamp01((component_weight * component_score + llm_weight * llm_score) / total)


def _llm_score(judgment: dict[str, Any]) -> float:
    """Compute weighted LLM score from strict judge dimensions."""
    return _clamp01(
        0.35 * _clamp01(judgment.get("attack_priority"))
        + 0.25 * _clamp01(judgment.get("early_pressure"))
        + 0.20 * _clamp01(judgment.get("economy_sacrifice"))
        + 0.10 * _clamp01(judgment.get("expansion_risk"))
        + 0.10 * _clamp01(judgment.get("unit_commitment"))
    )


def _clamp01(value: Any) -> float:
    """Clamp one score to [0, 1]."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
