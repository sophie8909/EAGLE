"""Deterministic component priors for strategic aggressiveness."""

from __future__ import annotations

import re
from typing import Any


COMPONENT_AGGRESSIVENESS_PRIORS: dict[str, float] = {
    "rush_strategy": 0.9,
    "worker_pressure": 0.8,
    "early_game_plan": 0.7,
    "attack_style": 0.75,
    "unit_commitment": 0.7,
    "barracks_pressure": 0.65,
    "economy_first": 0.2,
    "defensive_rules": 0.1,
    "defense": 0.15,
    "economic": 0.25,
}

KEYWORD_AGGRESSIVENESS_PRIORS: dict[str, float] = {
    "rush": 0.9,
    "pressure": 0.8,
    "attack": 0.75,
    "harass": 0.7,
    "frontline": 0.65,
    "barracks": 0.6,
    "defend": 0.15,
    "defensive": 0.1,
    "economy": 0.2,
    "harvest": 0.25,
}


def compute_component_aggressiveness(individual: Any) -> float:
    """Return a deterministic normalized aggressiveness prior for one individual."""
    scores = _component_scores(individual)
    if not scores:
        return 0.0
    return _clamp01(sum(scores) / len(scores))


def _component_scores(individual: Any) -> list[float]:
    """Collect prior scores from component keys and static prompt text."""
    scores: list[float] = []
    component_indices = getattr(individual, "component_indices", {}) or {}
    if isinstance(component_indices, dict):
        for key in component_indices:
            score = _prior_for_text(str(key))
            if score is not None:
                scores.append(score)

    metadata = getattr(individual, "metadata", {}) or {}
    if isinstance(metadata, dict):
        for key in ("strategy", "strategy_identity", "component_names"):
            value = metadata.get(key)
            if isinstance(value, (str, list, tuple)):
                score = _prior_for_text(" ".join(value) if not isinstance(value, str) else value)
                if score is not None:
                    scores.append(score)

    prompt = str(getattr(individual, "rendered_prompt", "") or "")
    if prompt:
        prompt_scores = [
            score
            for token, score in KEYWORD_AGGRESSIVENESS_PRIORS.items()
            if re.search(rf"\b{re.escape(token)}\b", prompt, flags=re.IGNORECASE)
        ]
        if prompt_scores:
            scores.append(sum(prompt_scores) / len(prompt_scores))
    return scores


def _prior_for_text(text: str) -> float | None:
    """Return the highest matching prior for one component-like text value."""
    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    matches = [
        score
        for key, score in COMPONENT_AGGRESSIVENESS_PRIORS.items()
        if key in normalized
    ]
    if matches:
        return _clamp01(max(matches))
    keyword_matches = [
        score
        for key, score in KEYWORD_AGGRESSIVENESS_PRIORS.items()
        if key in normalized
    ]
    if keyword_matches:
        return _clamp01(max(keyword_matches))
    return None


def _clamp01(value: float) -> float:
    """Clamp one score to the closed unit interval."""
    return min(1.0, max(0.0, float(value)))
