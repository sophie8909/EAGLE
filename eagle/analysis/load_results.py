"""Load and normalize consistency-analysis CSV inputs."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "prompt_id": ("prompt_id", "prompt", "prompt_digest", "individual_id", "id"),
    "seed": ("seed", "random_seed", "match_seed", "game_seed"),
    "map_name": ("map_name", "map", "map_location", "map_file"),
    "opponent": ("opponent", "enemy", "opponent_name", "ai2"),
}

SCORE_ALIASES: tuple[str, ...] = (
    "win_rate",
    "win_score",
    "fitness",
    "score",
    "aggregate_score",
    "outcome_score",
    "mean_score",
)

OUTCOME_ALIASES: tuple[str, ...] = ("outcome", "result", "win_draw_loss", "match_result")
WIN_COUNT_ALIASES: tuple[str, ...] = ("win", "wins", "win_count")
DRAW_COUNT_ALIASES: tuple[str, ...] = ("draw", "draws", "draw_count")
LOSS_COUNT_ALIASES: tuple[str, ...] = ("loss", "losses", "loss_count")

BEHAVIOR_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "worker_production": ("worker_production_count", "worker_production_rate", "worker_count", "worker_rate"),
    "barracks_build": ("barracks_build_count", "barracks_build_rate", "barracks_count", "barracks_rate"),
    "harvest_action": ("harvest_action_count", "harvest_action_rate", "harvest_count", "harvest_rate"),
    "attack_action": ("attack_action_count", "attack_action_rate", "attack_count", "attack_rate"),
    "idle_ratio": ("idle_ratio", "idle_rate"),
    "first_attack_turn": ("first_attack_turn", "attack_turn_first"),
    "resource_collection_rate": ("resource_collection_rate", "resource_rate", "harvest_rate_per_turn"),
    "combat_unit_composition": ("combat_unit_composition", "combat_comp", "unit_composition"),
}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read one CSV file into a list of row dictionaries."""
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV file has no header row: {path}")
        return [dict(row) for row in reader]


def _first_present_value(row: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    """Return the first non-empty value found among alias columns."""
    for alias in aliases:
        value = row.get(alias)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_float(value: Any) -> float | None:
    """Parse one optional numeric value."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_outcome_score(row: dict[str, Any]) -> float | None:
    """Convert an outcome or explicit score field into a normalized score."""
    explicit_score = _first_present_value(row, SCORE_ALIASES)
    parsed_explicit = _parse_float(explicit_score)
    if parsed_explicit is not None:
        return parsed_explicit

    outcome_text = _first_present_value(row, OUTCOME_ALIASES)
    if outcome_text is not None:
        normalized = outcome_text.strip().lower()
        if normalized in {"win", "w", "1", "true"}:
            return 1.0
        if normalized in {"draw", "tie", "0.5"}:
            return 0.5
        if normalized in {"loss", "lose", "l", "0", "false"}:
            return 0.0

    wins = _parse_float(_first_present_value(row, WIN_COUNT_ALIASES))
    draws = _parse_float(_first_present_value(row, DRAW_COUNT_ALIASES))
    losses = _parse_float(_first_present_value(row, LOSS_COUNT_ALIASES))
    if wins is not None or draws is not None or losses is not None:
        total = (wins or 0.0) + (draws or 0.0) + (losses or 0.0)
        if total > 0:
            return ((wins or 0.0) + 0.5 * (draws or 0.0)) / total

    return None


def normalize_result_rows(rows: list[dict[str, str]], source_name: str) -> list[dict[str, Any]]:
    """Normalize raw result rows into a merge-friendly schema."""
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        prompt_id = _first_present_value(row, KEY_ALIASES["prompt_id"])
        map_name = _first_present_value(row, KEY_ALIASES["map_name"])
        opponent = _first_present_value(row, KEY_ALIASES["opponent"])
        if prompt_id is None:
            raise ValueError(f"{source_name} row {index} is missing prompt_id-compatible columns")
        if map_name is None:
            map_name = "__unknown_map__"
        if opponent is None:
            opponent = "__unknown_opponent__"
        seed = _first_present_value(row, KEY_ALIASES["seed"]) or "__aggregate__"
        score = _parse_outcome_score(row)
        if score is None:
            raise ValueError(f"{source_name} row {index} is missing a score/outcome-compatible column")
        normalized.append(
            {
                "prompt_id": prompt_id,
                "seed": seed,
                "map_name": map_name,
                "opponent": opponent,
                "score": float(score),
                "source": source_name,
                "raw_row": dict(row),
            }
        )
    return normalized


def aggregate_result_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate repeated rows with the same prompt/map/opponent/seed key."""
    grouped: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        key = (
            str(row["prompt_id"]),
            str(row["seed"]),
            str(row["map_name"]),
            str(row["opponent"]),
        )
        grouped[key].append(float(row["score"]))

    aggregated: list[dict[str, Any]] = []
    for (prompt_id, seed, map_name, opponent), values in grouped.items():
        aggregated.append(
            {
                "prompt_id": prompt_id,
                "seed": seed,
                "map_name": map_name,
                "opponent": opponent,
                "score": sum(values) / len(values),
                "sample_count": len(values),
            }
        )
    return aggregated


def merge_result_rows(prompt_rows: list[dict[str, Any]], java_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inner-join prompt-based and Java result rows by merge key."""
    prompt_by_key = {
        (str(row["prompt_id"]), str(row["seed"]), str(row["map_name"]), str(row["opponent"])): row
        for row in prompt_rows
    }
    java_by_key = {
        (str(row["prompt_id"]), str(row["seed"]), str(row["map_name"]), str(row["opponent"])): row
        for row in java_rows
    }

    merged: list[dict[str, Any]] = []
    for key in sorted(set(prompt_by_key) & set(java_by_key)):
        prompt_row = prompt_by_key[key]
        java_row = java_by_key[key]
        merged.append(
            {
                "prompt_id": key[0],
                "seed": key[1],
                "map_name": key[2],
                "opponent": key[3],
                "prompt_score": float(prompt_row["score"]),
                "java_score": float(java_row["score"]),
                "prompt_sample_count": int(prompt_row.get("sample_count", 1)),
                "java_sample_count": int(java_row.get("sample_count", 1)),
            }
        )
    return merged


def _normalize_behavior_value(metric_name: str, value: str) -> float | str | None:
    """Normalize one behavior metric into numeric or text form."""
    if metric_name == "combat_unit_composition":
        cleaned = str(value).strip()
        return cleaned or None
    return _parse_float(value)


def normalize_behavior_rows(rows: list[dict[str, str]], source_name: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize optional behavior rows into a merge-friendly schema."""
    normalized: list[dict[str, Any]] = []
    available_metrics: set[str] = set()
    for index, row in enumerate(rows):
        prompt_id = _first_present_value(row, KEY_ALIASES["prompt_id"])
        if prompt_id is None:
            raise ValueError(f"{source_name} behavior row {index} is missing prompt_id-compatible columns")
        map_name = _first_present_value(row, KEY_ALIASES["map_name"]) or "__unknown_map__"
        opponent = _first_present_value(row, KEY_ALIASES["opponent"]) or "__unknown_opponent__"
        seed = _first_present_value(row, KEY_ALIASES["seed"]) or "__aggregate__"

        metric_values: dict[str, float | str] = {}
        for metric_name, aliases in BEHAVIOR_FIELD_ALIASES.items():
            raw_value = _first_present_value(row, aliases)
            normalized_value = _normalize_behavior_value(metric_name, raw_value) if raw_value is not None else None
            if normalized_value is not None:
                metric_values[metric_name] = normalized_value
                available_metrics.add(metric_name)

        normalized.append(
            {
                "prompt_id": prompt_id,
                "seed": seed,
                "map_name": map_name,
                "opponent": opponent,
                "metrics": metric_values,
            }
        )
    missing_metrics = [metric_name for metric_name in BEHAVIOR_FIELD_ALIASES if metric_name not in available_metrics]
    return normalized, missing_metrics


def aggregate_behavior_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate repeated behavior rows with the same prompt/map/opponent/seed key."""
    grouped_numeric: dict[tuple[str, str, str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    grouped_text: dict[tuple[str, str, str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for row in rows:
        key = (
            str(row["prompt_id"]),
            str(row["seed"]),
            str(row["map_name"]),
            str(row["opponent"]),
        )
        for metric_name, value in dict(row.get("metrics") or {}).items():
            if isinstance(value, float):
                grouped_numeric[key][metric_name].append(value)
            elif isinstance(value, str):
                grouped_text[key][metric_name].append(value)

    aggregated: list[dict[str, Any]] = []
    for key in sorted(set(grouped_numeric) | set(grouped_text)):
        metric_values: dict[str, float | str] = {}
        for metric_name, values in grouped_numeric.get(key, {}).items():
            metric_values[metric_name] = sum(values) / len(values)
        for metric_name, values in grouped_text.get(key, {}).items():
            counts: dict[str, int] = defaultdict(int)
            for value in values:
                counts[value] += 1
            metric_values[metric_name] = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        aggregated.append(
            {
                "prompt_id": key[0],
                "seed": key[1],
                "map_name": key[2],
                "opponent": key[3],
                "metrics": metric_values,
            }
        )
    return aggregated


def merge_behavior_rows(
    prompt_rows: list[dict[str, Any]],
    java_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inner-join prompt-based and Java behavior rows by merge key."""
    prompt_by_key = {
        (str(row["prompt_id"]), str(row["seed"]), str(row["map_name"]), str(row["opponent"])): row
        for row in prompt_rows
    }
    java_by_key = {
        (str(row["prompt_id"]), str(row["seed"]), str(row["map_name"]), str(row["opponent"])): row
        for row in java_rows
    }
    merged: list[dict[str, Any]] = []
    for key in sorted(set(prompt_by_key) & set(java_by_key)):
        merged.append(
            {
                "prompt_id": key[0],
                "seed": key[1],
                "map_name": key[2],
                "opponent": key[3],
                "prompt_metrics": dict(prompt_by_key[key].get("metrics") or {}),
                "java_metrics": dict(java_by_key[key].get("metrics") or {}),
            }
        )
    return merged


def collect_behavior_rows_from_results(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract behavior rows from the main result CSV when behavior columns are embedded there."""
    return normalize_behavior_rows(rows, "embedded_results")


def split_surrogate_validation_matches(
    rows: list[dict[str, str]],
    *,
    prompt_mode: str = "eagle_final_test",
    java_mode: str = "surrogate_java_final_test",
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split one surrogate_validation_matches.csv into prompt and Java result rows."""
    prompt_rows: list[dict[str, str]] = []
    java_rows: list[dict[str, str]] = []
    for row in rows:
        mode = str(row.get("mode") or row.get("benchmark_mode") or "").strip()
        if mode == prompt_mode:
            prompt_rows.append(dict(row))
        elif mode == java_mode:
            java_rows.append(dict(row))
    return prompt_rows, java_rows
