"""Deterministic strategy signatures, niches, and diversity metrics."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any, Iterable, Mapping


STRATEGY_SIGNATURE_FIELDS = (
    "opening",
    "economy",
    "production",
    "attack_timing",
    "combat_style",
    "expansion",
    "defense",
    "target_priority",
)
UNKNOWN = "unknown"

_SYNONYMS = {
    "worker first": "worker_first",
    "workers first": "worker_first",
    "worker opening": "worker_first",
    "fast worker": "worker_first",
    "early rush": "fast_combat",
    "fast rush": "fast_combat",
    "aggressive early attack": "fast_combat",
    "early barracks": "early_barracks",
    "barracks first": "early_barracks",
    "balanced workers": "balanced_worker",
    "balanced worker": "balanced_worker",
    "many workers": "high_worker",
    "high workers": "high_worker",
    "few workers": "low_worker",
    "low workers": "low_worker",
    "mixed units": "mixed",
    "mixed production": "mixed",
    "early attack": "early",
    "mid attack": "mid",
    "late attack": "late",
    "counter attack": "counter_attack",
    "counterattack": "counter_attack",
    "base focused": "base_focused",
    "worker focused": "worker_focused",
}

_TOKEN_SYNONYMS = {
    "workers": "worker",
    "worker": "worker",
    "lights": "light",
    "light": "light",
    "heavies": "heavy",
    "heavy": "heavy",
    "ranged": "ranged",
    "range": "ranged",
    "bases": "base",
    "barracks": "barracks",
}


def normalize_strategy_signature(value: object) -> dict[str, Any]:
    """Normalize Coach output without using another LLM or raw prompt text."""

    source = value if isinstance(value, Mapping) else {}
    normalized: dict[str, Any] = {}
    for field in STRATEGY_SIGNATURE_FIELDS:
        raw = source.get(field)
        if field == "production":
            normalized[field] = _normalize_production(raw)
        else:
            normalized[field] = _normalize_label(raw, field=field)
    return normalized


def build_strategy_niche(signature: object) -> str:
    """Build a stable major-structure label from a normalized signature."""

    normalized = normalize_strategy_signature(signature)
    attack = _niche_label(normalized.get("attack_timing"))
    production = normalized.get("production") or []
    if len(production) > 1 or production == ["mixed"]:
        primary_production = "mixed"
    else:
        primary_production = _niche_label(production[0] if production else UNKNOWN)
    combat = _niche_label(normalized.get("combat_style"))
    economy = _niche_label(normalized.get("economy"))
    if combat not in {UNKNOWN, "balanced"}:
        third = combat
    elif economy == "balanced_worker":
        third = "balanced"
    elif economy != UNKNOWN:
        third = "economy"
    else:
        third = UNKNOWN
    if attack == UNKNOWN and primary_production == UNKNOWN and third == UNKNOWN:
        return UNKNOWN
    return f"{attack}-{primary_production}-{third}"


def strategy_distance(left: object, right: object) -> float:
    """Return normalized categorical Hamming/Jaccard distance in ``[0, 1]``."""

    a = normalize_strategy_signature(left)
    b = normalize_strategy_signature(right)
    distances: list[float] = []
    for field in STRATEGY_SIGNATURE_FIELDS:
        if field == "production":
            distances.append(_jaccard_distance(a[field], b[field]))
        else:
            av = a[field]
            bv = b[field]
            if av == UNKNOWN and bv == UNKNOWN:
                continue
            distances.append(0.0 if av == bv else 1.0)
    return 0.0 if not distances else sum(distances) / len(distances)


def generation_diversity_metrics(
    population: Iterable[object],
    *,
    previous_archive_niches: Iterable[str] = (),
) -> dict[str, Any]:
    """Calculate analysis-only diversity metrics for one surviving population."""

    candidates = [item for item in population if hasattr(item, "strategy_niche")]
    known = [item for item in candidates if _known_niche(str(getattr(item, "strategy_niche", UNKNOWN)))]
    counts = Counter(str(item.strategy_niche) for item in known)
    previous = {str(item) for item in previous_archive_niches if _known_niche(str(item))}
    current = set(counts)
    dominant_niche, dominant_count = (counts.most_common(1)[0] if counts else (UNKNOWN, 0))
    distances = [
        strategy_distance(left.strategy_signature, right.strategy_signature)
        for left, right in combinations(known, 2)
    ]
    comparable = [
        item for item in candidates
        if str(getattr(item, "mutation_type", "")) == "strategy"
        and _known_niche(str(getattr(item, "parent_strategy_niche", UNKNOWN)))
        and _known_niche(str(getattr(item, "strategy_niche", UNKNOWN)))
    ]
    changed = [bool(getattr(item, "niche_changed", False)) for item in comparable]
    intent_rates: dict[str, float | None] = {}
    for intent in ("REFINE", "COUNTER", "STRUCTURAL", "ALTERNATIVE"):
        intent_items = [item for item in comparable if getattr(item, "mutation_intent", None) == intent]
        intent_rates[intent] = (
            sum(bool(getattr(item, "niche_changed", False)) for item in intent_items) / len(intent_items)
            if intent_items else None
        )
    return {
        "unique_niches": len(current),
        "unique_strategy_niches": len(current),
        "dominant_niche": dominant_niche,
        "dominant_niche_count": dominant_count,
        "dominant_niche_ratio": dominant_count / len(candidates) if candidates else 0.0,
        "niche_distribution": dict(sorted(counts.items())),
        "known_signature_count": len(known),
        "unknown_signature_count": len(candidates) - len(known),
        "mean_strategy_distance": sum(distances) / len(distances) if distances else 0.0,
        "new_niches": len(current - previous),
        "revisited_niches": sum(1 for item in known if str(item.strategy_niche) in previous),
        "niche_change_rate": sum(changed) / len(changed) if changed else None,
        "intent_niche_change_rates": intent_rates,
    }


def diversity_console_summary(generation: int, metrics: Mapping[str, Any]) -> str:
    """Return the concise generation summary used by normal EA logging."""

    dominant = str(metrics.get("dominant_niche") or UNKNOWN)
    ratio = float(metrics.get("dominant_niche_ratio") or 0.0)
    distance = float(metrics.get("mean_strategy_distance") or 0.0)
    change = metrics.get("niche_change_rate")
    change_text = "n/a" if change is None else f"{float(change):.0%}"
    return (
        f"[gen {generation}] diversity: niches={int(metrics.get('unique_niches') or 0)} "
        f"dominant={dominant} ({ratio:.0%}) mean_distance={distance:.2f} "
        f"new_niches={int(metrics.get('new_niches') or 0)} "
        f"mutation_niche_change={change_text}"
    )


def _normalize_label(value: object, *, field: str | None = None) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    if not text:
        return UNKNOWN
    if text in _SYNONYMS:
        label = _SYNONYMS[text]
    else:
        slug = text.replace("-", " ").replace("/", " ")
        label = "_".join(part for part in slug.split() if part)
    # The same natural-language phrase can describe different categorical
    # fields.  Keep the normalization deterministic while respecting that
    # ``fast rush`` is an opening label but a combat style of ``rush``.
    if field == "combat_style" and label == "fast_combat":
        label = "rush"
    elif field == "attack_timing" and label == "fast_combat":
        label = "early"
    return label[:48] or UNKNOWN


def _normalize_production(value: object) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    labels = []
    for item in values:
        label = _normalize_label(item)
        if label == UNKNOWN:
            continue
        label = _TOKEN_SYNONYMS.get(label, label)
        if label not in labels:
            labels.append(label)
    if "mixed" in labels and len(labels) > 1:
        labels.remove("mixed")
    return sorted(labels)


def _niche_label(value: object) -> str:
    return _normalize_label(value)


def _jaccard_distance(left: object, right: object) -> float:
    a = set(left if isinstance(left, (list, tuple, set)) else ())
    b = set(right if isinstance(right, (list, tuple, set)) else ())
    if not a and not b:
        return 0.0
    return 1.0 - len(a & b) / len(a | b)


def _known_niche(value: str) -> bool:
    return bool(value and value != UNKNOWN and value != "unknown-unknown-balanced")
