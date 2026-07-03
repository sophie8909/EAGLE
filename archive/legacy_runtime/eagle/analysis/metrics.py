"""Consistency metrics for Java-vs-prompt alignment analysis."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def _mean(values: list[float]) -> float | None:
    """Return the arithmetic mean when at least one value exists."""
    if not values:
        return None
    return sum(values) / len(values)


def _variance(values: list[float], mean_value: float) -> float:
    """Return the population variance around a provided mean."""
    return sum((value - mean_value) ** 2 for value in values) / len(values)


def pearson_correlation(x_values: list[float], y_values: list[float]) -> float | None:
    """Compute Pearson correlation coefficient."""
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    mean_x = _mean(x_values)
    mean_y = _mean(y_values)
    if mean_x is None or mean_y is None:
        return None
    var_x = _variance(x_values, mean_x)
    var_y = _variance(y_values, mean_y)
    if var_x <= 0 or var_y <= 0:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values)) / len(x_values)
    return covariance / math.sqrt(var_x * var_y)


def _average_ranks(values: list[float]) -> list[float]:
    """Assign average ranks, handling ties conservatively."""
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        tie_end = position + 1
        while tie_end < len(indexed) and indexed[tie_end][1] == indexed[position][1]:
            tie_end += 1
        average_rank = (position + 1 + tie_end) / 2.0
        for tie_index in range(position, tie_end):
            original_index = indexed[tie_index][0]
            ranks[original_index] = average_rank
        position = tie_end
    return ranks


def spearman_correlation(x_values: list[float], y_values: list[float]) -> float | None:
    """Compute Spearman rank correlation coefficient."""
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    return pearson_correlation(_average_ranks(x_values), _average_ranks(y_values))


def kendall_tau_b(x_values: list[float], y_values: list[float]) -> float | None:
    """Compute Kendall tau-b rank correlation."""
    n = len(x_values)
    if n != len(y_values) or n < 2:
        return None

    concordant = 0
    discordant = 0
    ties_x = 0
    ties_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = x_values[i] - x_values[j]
            dy = y_values[i] - y_values[j]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                ties_x += 1
                continue
            if dy == 0:
                ties_y += 1
                continue
            if dx * dy > 0:
                concordant += 1
            else:
                discordant += 1

    denominator = math.sqrt((concordant + discordant + ties_x) * (concordant + discordant + ties_y))
    if denominator == 0:
        return None
    return (concordant - discordant) / denominator


def mean_absolute_error(x_values: list[float], y_values: list[float]) -> float | None:
    """Compute mean absolute error."""
    if len(x_values) != len(y_values) or not x_values:
        return None
    return sum(abs(y - x) for x, y in zip(x_values, y_values)) / len(x_values)


def root_mean_squared_error(x_values: list[float], y_values: list[float]) -> float | None:
    """Compute root mean squared error."""
    if len(x_values) != len(y_values) or not x_values:
        return None
    return math.sqrt(sum((y - x) ** 2 for x, y in zip(x_values, y_values)) / len(x_values))


def mean_bias(x_values: list[float], y_values: list[float]) -> float | None:
    """Compute mean signed bias as Java minus prompt."""
    if len(x_values) != len(y_values) or not x_values:
        return None
    return sum((y - x) for x, y in zip(x_values, y_values)) / len(x_values)


def _aggregate_scores_by_prompt(rows: list[dict[str, Any]]) -> list[dict[str, float | str]]:
    """Aggregate prompt and Java scores by prompt_id for ranking comparisons."""
    grouped_prompt: dict[str, list[float]] = defaultdict(list)
    grouped_java: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        prompt_id = str(row["prompt_id"])
        grouped_prompt[prompt_id].append(float(row["prompt_score"]))
        grouped_java[prompt_id].append(float(row["java_score"]))
    aggregated: list[dict[str, float | str]] = []
    for prompt_id in sorted(set(grouped_prompt) & set(grouped_java)):
        aggregated.append(
            {
                "prompt_id": prompt_id,
                "prompt_score": sum(grouped_prompt[prompt_id]) / len(grouped_prompt[prompt_id]),
                "java_score": sum(grouped_java[prompt_id]) / len(grouped_java[prompt_id]),
            }
        )
    return aggregated


def compute_topk_overlap(rows: list[dict[str, Any]], top_ks: tuple[int, ...]) -> dict[int, float | None]:
    """Compute top-k overlap ratios using prompt-level aggregate scores."""
    aggregated = _aggregate_scores_by_prompt(rows)
    if not aggregated:
        return {k: None for k in top_ks}

    prompt_ranked = sorted(aggregated, key=lambda row: (-float(row["prompt_score"]), str(row["prompt_id"])))
    java_ranked = sorted(aggregated, key=lambda row: (-float(row["java_score"]), str(row["prompt_id"])))

    overlaps: dict[int, float | None] = {}
    for k in top_ks:
        actual_k = min(k, len(aggregated))
        if actual_k <= 0:
            overlaps[k] = None
            continue
        prompt_top = {str(row["prompt_id"]) for row in prompt_ranked[:actual_k]}
        java_top = {str(row["prompt_id"]) for row in java_ranked[:actual_k]}
        overlaps[k] = len(prompt_top & java_top) / actual_k
    return overlaps


def compute_group_metrics(
    rows: list[dict[str, Any]],
    *,
    group_type: str,
    group_value: str,
    top_ks: tuple[int, ...],
) -> dict[str, Any]:
    """Compute all requested consistency metrics for one group."""
    prompt_scores = [float(row["prompt_score"]) for row in rows]
    java_scores = [float(row["java_score"]) for row in rows]
    topk = compute_topk_overlap(rows, top_ks)

    result: dict[str, Any] = {
        "group_type": group_type,
        "group_value": group_value,
        "pair_count": len(rows),
        "unique_prompt_count": len({str(row["prompt_id"]) for row in rows}),
        "pearson": pearson_correlation(prompt_scores, java_scores),
        "spearman": spearman_correlation(prompt_scores, java_scores),
        "kendall_tau": kendall_tau_b(prompt_scores, java_scores),
        "mae": mean_absolute_error(prompt_scores, java_scores),
        "rmse": root_mean_squared_error(prompt_scores, java_scores),
        "mean_bias": mean_bias(prompt_scores, java_scores),
    }
    for k, value in topk.items():
        result[f"topk_overlap_{k}"] = value
    return result


def compute_consistency_summary(rows: list[dict[str, Any]], top_ks: tuple[int, ...]) -> list[dict[str, Any]]:
    """Compute overall, per-map, and per-opponent summaries."""
    summaries: list[dict[str, Any]] = []
    summaries.append(compute_group_metrics(rows, group_type="overall", group_value="overall", top_ks=top_ks))

    by_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_opponent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_map[str(row["map_name"])].append(row)
        by_opponent[str(row["opponent"])].append(row)

    for map_name in sorted(by_map):
        summaries.append(compute_group_metrics(by_map[map_name], group_type="map", group_value=map_name, top_ks=top_ks))
    for opponent in sorted(by_opponent):
        summaries.append(
            compute_group_metrics(by_opponent[opponent], group_type="opponent", group_value=opponent, top_ks=top_ks)
        )
    return summaries


def compute_behavior_similarity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute overall behavior similarity metrics for all available numeric behavior fields."""
    metric_names = sorted(
        {
            metric_name
            for row in rows
            for metric_name in set(dict(row.get("prompt_metrics") or {})) | set(dict(row.get("java_metrics") or {}))
        }
    )
    summaries: list[dict[str, Any]] = []
    for metric_name in metric_names:
        paired_prompt: list[float] = []
        paired_java: list[float] = []
        paired_prompt_text: list[str] = []
        paired_java_text: list[str] = []
        for row in rows:
            prompt_value = dict(row.get("prompt_metrics") or {}).get(metric_name)
            java_value = dict(row.get("java_metrics") or {}).get(metric_name)
            if isinstance(prompt_value, float) and isinstance(java_value, float):
                paired_prompt.append(prompt_value)
                paired_java.append(java_value)
            elif isinstance(prompt_value, str) and isinstance(java_value, str):
                paired_prompt_text.append(prompt_value)
                paired_java_text.append(java_value)

        if paired_prompt:
            prompt_values = [
                float(row["prompt_metrics"][metric_name])
                for row in rows
                if isinstance(dict(row.get("prompt_metrics") or {}).get(metric_name), float)
            ]
            java_values = [
                float(row["java_metrics"][metric_name])
                for row in rows
                if isinstance(dict(row.get("java_metrics") or {}).get(metric_name), float)
            ]
            summaries.append(
                {
                    "group_type": "overall",
                    "group_value": "overall",
                    "behavior_metric": metric_name,
                    "pair_count": len(paired_prompt),
                    "prompt_mean": _mean(prompt_values),
                    "java_mean": _mean(java_values),
                    "prompt_mode": None,
                    "java_mode": None,
                    "exact_match_rate": None,
                    "pearson": pearson_correlation(paired_prompt, paired_java),
                    "mae": mean_absolute_error(paired_prompt, paired_java),
                    "rmse": root_mean_squared_error(paired_prompt, paired_java),
                    "mean_bias": mean_bias(paired_prompt, paired_java),
                }
            )
        elif paired_prompt_text:
            prompt_counts: dict[str, int] = defaultdict(int)
            java_counts: dict[str, int] = defaultdict(int)
            exact_matches = 0
            for prompt_value, java_value in zip(paired_prompt_text, paired_java_text):
                prompt_counts[prompt_value] += 1
                java_counts[java_value] += 1
                if prompt_value == java_value:
                    exact_matches += 1
            summaries.append(
                {
                    "group_type": "overall",
                    "group_value": "overall",
                    "behavior_metric": metric_name,
                    "pair_count": len(paired_prompt_text),
                    "prompt_mean": None,
                    "java_mean": None,
                    "prompt_mode": sorted(prompt_counts.items(), key=lambda item: (-item[1], item[0]))[0][0],
                    "java_mode": sorted(java_counts.items(), key=lambda item: (-item[1], item[0]))[0][0],
                    "exact_match_rate": exact_matches / len(paired_prompt_text),
                    "pearson": None,
                    "mae": None,
                    "rmse": None,
                    "mean_bias": None,
                }
            )
    return summaries


def identify_largest_bias_prompts(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Identify prompt_ids with the largest average absolute score gap."""
    grouped_gaps: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped_gaps[str(row["prompt_id"])].append(abs(float(row["java_score"]) - float(row["prompt_score"])))
    ranked = sorted(
        (
            {
                "prompt_id": prompt_id,
                "mean_abs_gap": sum(values) / len(values),
                "pair_count": len(values),
            }
            for prompt_id, values in grouped_gaps.items()
        ),
        key=lambda item: (-float(item["mean_abs_gap"]), str(item["prompt_id"])),
    )
    return ranked[:limit]
