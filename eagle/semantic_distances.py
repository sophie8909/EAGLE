"""Canonical pairwise distances for compiled-agent semantic signatures."""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any, Protocol


SEMANTIC_DISTANCE_PAIR_SCHEMA_VERSION = "eagle-semantic-distance-pair-v1"
SemanticSummary = tuple[str, tuple[str, ...], tuple[str, ...], str]


class SemanticCandidate(Protocol):
    id: str
    semantic_signature: Mapping[str, Any]


def semantic_summary(candidate: SemanticCandidate) -> SemanticSummary | None:
    """Return the comparable ordered action vector for one candidate."""

    value = getattr(candidate, "semantic_signature", None)
    if not isinstance(value, Mapping) or value.get("status") != "complete":
        return None
    dataset_id = value.get("dataset_id")
    probe_ids = value.get("probe_ids")
    action_hashes = value.get("action_hashes")
    global_hash = value.get("global_hash")
    if not isinstance(dataset_id, str) or not dataset_id:
        return None
    if not isinstance(global_hash, str) or not global_hash:
        return None
    if not isinstance(probe_ids, (list, tuple)) or not isinstance(action_hashes, (list, tuple)):
        return None
    if not probe_ids or len(probe_ids) != len(action_hashes):
        return None
    if any(not isinstance(item, str) or not item for item in probe_ids):
        return None
    if any(not isinstance(item, str) or not item for item in action_hashes):
        return None
    ordered_probes = tuple(probe_ids)
    if len(set(ordered_probes)) != len(ordered_probes):
        return None
    return dataset_id, ordered_probes, tuple(action_hashes), global_hash


def semantic_distance(left: SemanticSummary, right: SemanticSummary) -> float | None:
    """Return normalized Hamming distance for compatible semantic vectors."""

    left_dataset, left_probes, left_actions, _ = left
    right_dataset, right_probes, right_actions, _ = right
    if left_dataset != right_dataset or left_probes != right_probes:
        return None
    mismatches = sum(a != b for a, b in zip(left_actions, right_actions, strict=True))
    return mismatches / len(left_actions)


def candidate_semantic_distance(
    left: SemanticCandidate,
    right: SemanticCandidate,
) -> float | None:
    """Return the canonical distance between two candidates when comparable."""

    left_summary = semantic_summary(left)
    right_summary = semantic_summary(right)
    if left_summary is None or right_summary is None:
        return None
    return semantic_distance(left_summary, right_summary)


def pairwise_semantic_distance_records(
    population: Sequence[SemanticCandidate],
    *,
    generation: int,
) -> list[dict[str, Any]]:
    """Record every unordered survivor pair, including unavailable comparisons."""

    records: list[dict[str, Any]] = []
    for left, right in combinations(sorted(population, key=lambda item: item.id), 2):
        left_summary = semantic_summary(left)
        right_summary = semantic_summary(right)
        distance = (
            None
            if left_summary is None or right_summary is None
            else semantic_distance(left_summary, right_summary)
        )
        if left_summary is None or right_summary is None:
            reason = "signature_unavailable"
        elif left_summary[0] != right_summary[0]:
            reason = "dataset_mismatch"
        elif left_summary[1] != right_summary[1]:
            reason = "probe_order_mismatch"
        else:
            reason = None
        records.append({
            "schema_version": SEMANTIC_DISTANCE_PAIR_SCHEMA_VERSION,
            "generation": generation,
            "left_candidate_id": left.id,
            "right_candidate_id": right.id,
            "status": "comparable" if distance is not None else "unavailable",
            "distance": distance,
            "unavailable_reason": reason,
        })
    return records


def semantic_distance_statistics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize comparable pair distances without converting missing data to zero."""

    distances = [
        float(item["distance"])
        for item in records
        if isinstance(item.get("distance"), (int, float))
    ]
    return {
        "pair_count": len(records),
        "comparable_pair_count": len(distances),
        "unavailable_pair_count": len(records) - len(distances),
        "minimum": min(distances) if distances else None,
        "mean": statistics.fmean(distances) if distances else None,
        "maximum": max(distances) if distances else None,
    }
