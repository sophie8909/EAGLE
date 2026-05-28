"""Strategic aggressiveness objective."""

from __future__ import annotations

from typing import Any

from eagle.objectives.aggressiveness.component_priors import compute_component_aggressiveness
from eagle.objectives.base import Objective


class StrategicAggressivenessObjective(Objective):
    """Reward static strategic tendency toward proactive aggression."""

    key = "strategic_aggressiveness"
    label = "Strategic aggressiveness"
    direction = "max"
    application = "microrts"
    eval_modes = {"full_game", "java_surrogate"}
    required_metrics = set()

    def compute(self, eval_result: dict[str, Any]) -> float:
        """Return weighted component and LLM aggressiveness in [0, 1]."""
        mode = str(eval_result.get("aggressiveness_mode", "hybrid") or "hybrid").strip().lower()
        component_score = _component_score(eval_result)
        llm_score = _llm_score(eval_result)
        component_weight = _weight(eval_result.get("aggressiveness_component_weight", 0.7))
        llm_weight = _weight(eval_result.get("aggressiveness_llm_weight", 0.3))

        if mode == "component_only":
            return component_score
        if mode == "llm_only":
            return llm_score

        total = component_weight + llm_weight
        if total <= 0.0:
            component_weight, llm_weight, total = 0.7, 0.3, 1.0
        final = (component_weight * component_score + llm_weight * llm_score) / total
        return _clamp01(final)


def _component_score(eval_result: dict[str, Any]) -> float:
    """Read or derive the component-only aggressiveness score."""
    if "aggressiveness_component_score" in eval_result:
        return _clamp01(eval_result.get("aggressiveness_component_score"))
    individual = eval_result.get("individual")
    if individual is not None:
        return compute_component_aggressiveness(individual)
    prompt = str(eval_result.get("prompt", "") or "")
    if not prompt:
        return 0.0
    prompt_proxy = type("PromptAggressivenessProxy", (), {"rendered_prompt": prompt, "component_indices": {}})()
    return compute_component_aggressiveness(prompt_proxy)


def _llm_score(eval_result: dict[str, Any]) -> float:
    """Read or derive the LLM aggressiveness score."""
    if "aggressiveness_llm_score" in eval_result:
        return _clamp01(eval_result.get("aggressiveness_llm_score"))
    judgment = eval_result.get("aggressiveness_judgment")
    if not isinstance(judgment, dict):
        return 0.0
    return _clamp01(
        0.35 * _clamp01(judgment.get("attack_priority"))
        + 0.25 * _clamp01(judgment.get("early_pressure"))
        + 0.20 * _clamp01(judgment.get("economy_sacrifice"))
        + 0.10 * _clamp01(judgment.get("expansion_risk"))
        + 0.10 * _clamp01(judgment.get("unit_commitment"))
    )


def _weight(value: Any) -> float:
    """Clamp an objective weight to [0, 1]."""
    return _clamp01(value)


def _clamp01(value: Any) -> float:
    """Clamp one score to the closed unit interval."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
