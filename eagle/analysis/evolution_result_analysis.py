"""Plot evolution fitness distributions and final-test resource outcomes."""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
from pathlib import Path

from ..project import EAGLE_LOGS_DIR, ensure_directory
from ..utils.checkpoint import deserialize_individual
from ..evolution.component.log_parse import parse_individuals_from_ea_log, parse_population_snapshot_from_ea_log
from .objective_metadata import load_run_objective_specs, objective_axis_labels, objective_names
from ..representation.fitness import fitness_values, normalize_fitness_dict


GENERATION_LOG_PATTERN = re.compile(r"generation_(\d+)_mo\.txt$")
GENERATION_MARKER_PATTERN = re.compile(r"\b(?:generation|gen)\s+\d+|generation_\d+", re.IGNORECASE)
FITNESS_VECTOR_PATTERN = re.compile(r"fitness\s*(?:=|:)\s*[\[(]([^\])]+)[\])]", re.IGNORECASE)
FITNESS_SCALAR_PATTERN = re.compile(r"fitness\s*(?:=|:)\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
GA_GENERATION_PATTERN = re.compile(r"^Generation\s+(\d+)(?!.*Multi-objective).*$", re.IGNORECASE | re.MULTILINE)
MO_GENERATION_PATTERN = re.compile(r"^Generation\s+(\d+).*$", re.IGNORECASE | re.MULTILINE)
PARETO_FRONT_PATTERN = re.compile(r"^Pareto Front\s+(\d+):", re.IGNORECASE | re.MULTILINE)
INDIVIDUAL_FITNESS_PATTERN = re.compile(r"^Individual.*?\s+-\s+Fitness\s*(?:=|:)\s*.+$", re.IGNORECASE)
TIME_LINE_PATTERN = re.compile(
    r"(?P<label>total runtime|generation runtime|average generation time|evaluation time|llm call time|llm time)"
    r"\s*(?:=|:)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s|sec|secs|seconds|m|min|mins|minutes)?",
    re.IGNORECASE,
)
FINAL_TEST_MARKER_PATTERN = re.compile(r"final[_\s-]*test", re.IGNORECASE)
FINAL_TEST_CANDIDATES = ("final_test_results.json", "final_test_result.json")
FINAL_TEST_MODES = ("interval_1", "interval_10", "java_agent_test")


def _require_matplotlib():
    """Import matplotlib lazily so CLI help still works without the package."""
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for plotting. Install requirements.txt before running analysis."
        ) from exc
    return plt


def _require_pillow():
    """Import Pillow lazily for GIF generation."""
    try:
        from PIL import Image  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Pillow is required for GIF generation. Install requirements.txt before running analysis."
        ) from exc
    return Image


def build_analysis_context(log_text, result_data=None) -> dict:
    """Build lightweight feature flags for analysis UI detection."""
    text = str(log_text or "")
    fitness_dimension = max(_fitness_dimension_from_data(result_data), _fitness_dimension_from_log(text))
    has_pareto = "Pareto Front" in text or fitness_dimension > 1
    is_multi_objective = has_pareto or fitness_dimension > 1
    return {
        "has_generation_log": bool(GENERATION_MARKER_PATTERN.search(text)) or _contains_key(result_data, "generation"),
        "has_final_test": "FINAL_TEST" in text.upper() or _contains_key(result_data, "final_test"),
        "has_pareto": has_pareto,
        "fitness_dimension": fitness_dimension,
        "is_multi_objective": is_multi_objective,
        "is_single_objective": fitness_dimension == 1 and not is_multi_objective,
    }


def parse_time_analysis(log_text) -> dict:
    """Parse runtime timing values from log, JSONL, or timing-summary text."""
    text = str(log_text or "")
    summary, events = _time_records_from_text(text)
    result = _time_analysis_from_summary(summary) if summary else {}
    if events:
        event_result = _time_analysis_from_events(events)
        result = {**event_result, **result}
    for key, value in _time_analysis_from_lines(text).items():
        result.setdefault(key, value)
    return {key: value for key, value in result.items() if value is not None}


def parse_final_test_analysis(log_text) -> dict:
    """Parse final-test results from JSON payloads or partial log markers."""
    text = str(log_text or "")
    payload = _final_test_payload_from_text(text)
    result = _final_test_analysis_from_payload(payload) if payload else {}
    marker_result = _final_test_analysis_from_lines(text)
    for key, value in marker_result.items():
        if key == "has_final_test":
            result[key] = bool(result.get(key)) or bool(value)
        elif key in {"maps", "opponents"}:
            result[key] = sorted(set(result.get(key, [])) | set(value))
        else:
            result.setdefault(key, value)
    return {key: value for key, value in result.items() if value not in (None, [], {})}


def parse_ga_convergence(log_text) -> dict:
    """Parse single-objective generation fitness into convergence series."""
    text = str(log_text or "")
    if not build_analysis_context(text).get("is_single_objective"):
        return {}
    generations: list[int] = []
    best_values: list[float] = []
    average_values: list[float] = []
    warnings: list[str] = []
    for generation, block in _ga_generation_blocks(text):
        population = _ga_population_fitness(block)
        if not population:
            continue
        best = max(population)
        average = sum(population) / len(population)
        generations.append(generation)
        best_values.append(best)
        average_values.append(average)
        if best < average:
            warnings.append(f"generation {generation}: best fitness {best} is below average fitness {average}")
    result: dict[str, object] = {"generations": generations, "best_fitness": best_values}
    if len(average_values) == len(generations):
        result["average_fitness"] = average_values
    if warnings:
        result["warnings"] = warnings
    return result if generations else {}


def parse_mo_analysis(log_text, objective_specs: list | None = None) -> dict:
    """Parse Pareto and objective-level summaries from multi-objective logs."""
    text = str(log_text or "")
    if not build_analysis_context(text).get("is_multi_objective"):
        return {}
    blocks = _mo_generation_blocks(text)
    if not blocks:
        blocks = [(0, text)]
    final_generation, final_block = blocks[-1]
    configured_objective_names = objective_names(list(objective_specs or []))
    parsed_objective_names = _mo_objective_names(text)
    objective_names_list = configured_objective_names or parsed_objective_names
    final_records = _mo_records_from_block(final_block, objective_names_list)
    front_one = [record for record in final_records if record.get("front") == 1]
    objective_best = _mo_objective_best(final_records, objective_names_list)
    trends = _mo_objective_trends(blocks, objective_names_list)
    result: dict[str, object] = {
        "final_generation": final_generation,
        "pareto_front_count": _mo_front_count(final_block),
        "final_pareto_front_individuals": front_one,
        "objective_names": objective_names_list,
        "objective_specs": [
            {
                "index": spec.index,
                "name": spec.name,
                "display_name": spec.display_name,
                "direction": spec.direction,
                "axis_label": spec.axis_label,
            }
            for spec in list(objective_specs or [])
        ],
        "objective_best": objective_best,
    }
    if trends:
        result["objective_trends"] = trends
    if "strategic_aggressiveness" in objective_names_list:
        result["aggressiveness_stats"] = _mo_aggressiveness_stats(blocks, objective_names_list)
    return result


def _mo_aggressiveness_stats(blocks: list[tuple[int, str]], objective_names_list: list[str]) -> list[dict[str, float]]:
    """Return strategic aggressiveness stats parsed from MO generation logs."""
    stats: list[dict[str, float]] = []
    for generation, block in blocks:
        records = _mo_records_from_block(block, objective_names_list)
        values = [
            float(record["fitness"]["strategic_aggressiveness"])
            for record in records
            if isinstance(record.get("fitness"), dict)
            and "strategic_aggressiveness" in record["fitness"]
        ]
        if not values:
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        stats.append(
            {
                "generation": generation,
                "mean": mean,
                "std": math.sqrt(variance),
                "min": min(values),
                "max": max(values),
                "count": len(values),
            }
        )
    return stats


def _contains_key(value: object, marker: str) -> bool:
    """Return whether a nested mapping/list contains a marker in any key."""
    if isinstance(value, dict):
        return any(marker in str(key).lower() or _contains_key(item, marker) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, marker) for item in value)
    return False


def _time_records_from_text(text: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Read timing JSON objects from mixed log text."""
    summary: dict[str, object] = {}
    events: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            payload, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if not isinstance(payload, dict):
            index = start + max(end, 1)
            continue
        index = start + max(end, 1)
        record_type = payload.get("record_type")
        if record_type == "timing_summary":
            summary = payload
        elif record_type == "timing_event":
            events.append(payload)
    return summary, events


def _json_objects_from_text(text: str) -> list[dict[str, object]]:
    """Read JSON objects embedded in plain text."""
    objects: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            payload, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = start + max(end, 1)
        if not isinstance(payload, dict):
            continue
        objects.append(payload)
    return objects


def _final_test_payload_from_text(text: str) -> dict[str, object]:
    """Return the first final-test-shaped JSON object from mixed text."""
    for payload in _json_objects_from_text(text):
        if payload.get("results") is None:
            continue
        if any(key in payload for key in ("source_run_dir", "selection", "config", "mode")):
            return payload
        if any(
            payload.get(key) is not None
            for key in ("generation_log", "selection_rule", "selected_individual_count", "skipped")
        ):
            return payload
    return {}


def _ga_generation_blocks(text: str) -> list[tuple[int, str]]:
    """Split GA generation text into generation-numbered blocks."""
    matches = list(GA_GENERATION_PATTERN.finditer(text))
    blocks: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((int(match.group(1)), text[start:end]))
    return blocks


def _mo_generation_blocks(text: str) -> list[tuple[int, str]]:
    """Split multi-objective text into generation-numbered blocks."""
    matches = list(MO_GENERATION_PATTERN.finditer(text))
    blocks: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        if build_analysis_context(block).get("is_multi_objective"):
            blocks.append((int(match.group(1)), block))
    return blocks


def _mo_front_count(block: str) -> int:
    """Return the number of Pareto front markers in one block."""
    return len(PARETO_FRONT_PATTERN.findall(block))


def _mo_records_from_block(block: str, objective_names: list[str]) -> list[dict[str, object]]:
    """Parse individual fitness rows from one MO generation block."""
    records: list[dict[str, object]] = []
    current_front: int | None = None
    fallback_index = 1
    for line in block.splitlines():
        if line.strip().startswith("Population Snapshot"):
            current_front = None
            continue
        front_match = PARETO_FRONT_PATTERN.match(line.strip())
        if front_match:
            current_front = int(front_match.group(1))
            continue
        if not INDIVIDUAL_FITNESS_PATTERN.match(line.strip()):
            continue
        values, names = _fitness_vector_from_line(line)
        if len(values) < 2:
            continue
        if not objective_names and names:
            objective_names.extend(names)
        if not objective_names:
            objective_names.extend(f"objective_{index}" for index in range(len(values)))
        while len(objective_names) < len(values):
            objective_names.append(f"objective_{len(objective_names)}")
        individual_id = _individual_id_from_line(line) or f"individual_{fallback_index}"
        fallback_index += 1
        records.append(
            {
                "id": individual_id,
                "front": current_front,
                "fitness": {name: values[index] for index, name in enumerate(objective_names[: len(values)])},
            }
        )
    return records


def _mo_objective_names(text: str) -> list[str]:
    """Return objective names from keyed fitness, or generated names by dimension."""
    dimension = 0
    for line in text.splitlines():
        if "fitness" not in line.lower():
            continue
        values, names = _fitness_vector_from_line(line)
        if names:
            return names
        dimension = max(dimension, len(values))
    return [f"objective_{index}" for index in range(dimension)] if dimension else []


def _mo_objective_best(records: list[dict[str, object]], objective_names: list[str]) -> list[dict[str, object]]:
    """Return best individual and value for each objective."""
    best_rows: list[dict[str, object]] = []
    for objective in objective_names:
        candidates = [
            (record, float(record["fitness"][objective]))
            for record in records
            if isinstance(record.get("fitness"), dict) and objective in record["fitness"]
        ]
        if not candidates:
            continue
        best_record, best_value = max(candidates, key=lambda item: item[1])
        best_rows.append({"objective": objective, "individual": best_record.get("id"), "value": best_value})
    return best_rows


def _mo_objective_trends(blocks: list[tuple[int, str]], objective_names: list[str]) -> dict[str, list[float]]:
    """Return per-generation best objective values when multiple generations exist."""
    if len(blocks) < 2:
        return {}
    trends: dict[str, list[float]] = {"generations": []}
    for objective in objective_names:
        trends[objective] = []
    for generation, block in blocks:
        records = _mo_records_from_block(block, list(objective_names))
        best_rows = {row["objective"]: row["value"] for row in _mo_objective_best(records, objective_names)}
        if not best_rows:
            continue
        trends["generations"].append(generation)
        for objective in objective_names:
            trends[objective].append(best_rows.get(objective, float("nan")))
    return trends if trends["generations"] else {}


def _fitness_vector_from_line(line: str) -> tuple[list[float], list[str]]:
    """Return numeric fitness vector and optional objective names from one line."""
    payload = _fitness_payload_from_line(line)
    if isinstance(payload, dict):
        pairs = [(str(key), float(value)) for key, value in payload.items() if _is_number_like(value)]
        return [value for _, value in pairs], [name for name, _ in pairs]
    if isinstance(payload, list):
        values = [float(value) for value in payload if _is_number_like(value)]
        return values, []
    return [], []


def _individual_id_from_line(line: str) -> str | None:
    """Extract an individual id from a logged Individual repr."""
    match = re.search(r"\bid=([^,\)]+)", line)
    return match.group(1).strip().strip("'\"") if match else None


def _ga_best_fitness(block: str) -> float | None:
    """Return the explicit best fitness from one GA generation block."""
    before_population = block.split("\nPopulation:", 1)[0]
    values = _fitness_numbers_from_text(before_population)
    return values[-1] if values else None


def _ga_population_fitness(block: str) -> list[float]:
    """Return population fitness values from one GA generation block."""
    if "\nPopulation:" not in block:
        return []
    return _fitness_numbers_from_text(block.split("\nPopulation:", 1)[1])


def _fitness_numbers_from_text(text: str) -> list[float]:
    """Return first fitness component values from matching log lines."""
    values: list[float] = []
    for line in text.splitlines():
        if "fitness" not in line.lower():
            continue
        value = _first_fitness_number(line)
        if value is not None:
            values.append(value)
    return values


def _first_fitness_number(line: str) -> float | None:
    """Return the first numeric component from a fitness log line."""
    payload = _fitness_payload_from_line(line)
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, list) and len(payload) == 1:
        return _safe_number(payload[0])
    if isinstance(payload, dict) and len(payload) == 1:
        return _safe_number(next(iter(payload.values())))
    vector_match = FITNESS_VECTOR_PATTERN.search(line)
    if vector_match:
        parts = [part.strip() for part in vector_match.group(1).split(",") if part.strip()]
        if len(parts) == 1:
            return _safe_number(parts[0])
        return None
    scalar_match = FITNESS_SCALAR_PATTERN.search(line)
    return _safe_number(scalar_match.group(1)) if scalar_match else None


def _fitness_payload_from_line(line: str) -> object | None:
    """Parse the Python-readable payload after a Fitness marker."""
    marker = re.search(r"fitness\s*(?:=|:)\s*", line, flags=re.IGNORECASE)
    if not marker:
        return None
    raw_payload = re.split(r"\s+-\s+EvalMode:", line[marker.end():], maxsplit=1)[0].strip()
    try:
        return ast.literal_eval(raw_payload)
    except (SyntaxError, ValueError):
        return None


def _final_test_analysis_from_payload(
    payload: dict[str, object],
    *,
    metric: str | None = None,
    aggregation: str = "mean",
    weights: dict[str, float] | None = None,
) -> dict[str, object]:
    """Build final-test fields from final-test result data."""
    records = _final_test_records(payload.get("results"))
    if not records:
        return {
            "has_final_test": False,
            "games": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "win_rate": None,
            "maps": [],
            "opponents": [],
        }

    wins = losses = draws = skipped_games = failed_games = 0
    maps: set[str] = set()
    opponents: set[str] = set()
    metric_values: dict[str, list[float]] = {
        "win_rate": [],
        "score": [],
        "ally_resources": [],
        "enemy_resources": [],
        "total_ally_resources": [],
        "total_enemy_resources": [],
        "resource_difference": [],
        "weighted_resource_score": [],
    }
    for record in records:
        outcome = _final_test_outcome(record)
        wins += int(outcome == "win")
        losses += int(outcome == "loss")
        draws += int(outcome == "draw")
        skipped_games += int(outcome == "skipped")
        failed_games += int(outcome == "failed")
        _add_optional_text(opponents, record.get("opponent"))
        _add_optional_text(maps, record.get("map") or record.get("map_name") or record.get("map_location"))
        record_metrics = _final_test_record_metrics(record, weights=weights)
        for key in metric_values:
            metric_values[key].append(float(record_metrics[key]))

    completed_games = wins + losses + draws
    total_games = len(records)
    summary = {
        "has_final_test": True,
        "games": total_games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": (wins / completed_games) if completed_games else None,
        "maps": sorted(maps),
        "opponents": sorted(opponents),
        "skipped_games": skipped_games or (total_games if payload.get("skipped") else 0),
        "failed_games": failed_games,
        "skipped": bool(payload.get("skipped")),
        "skip_reason": str(payload.get("skip_reason")) if payload.get("skip_reason") else None,
        "source_run_dir": payload.get("source_run_dir"),
        "created_at": payload.get("created_at"),
        "mode": payload.get("mode"),
        "selection": payload.get("selection") or {},
        "config": payload.get("config") or {},
    }
    for key, values in metric_values.items():
        summary[f"mean_{key}"] = _safe_average(values)
        summary[f"best_{key}"] = max(values) if values else None
        summary[f"worst_{key}"] = min(values) if values else None
    if metric is not None:
        metric_values_for_key = metric_values.get(metric, [])
        summary["selected_metric"] = metric
        summary["selected_aggregation"] = aggregation
        summary["selected_metric_value"] = _aggregate_metric_values(metric_values_for_key, aggregation)
    return summary


def _final_test_records(results: object) -> list[dict[str, object]]:
    """Flatten final-test result rows from supported result payloads."""
    rows: list[dict[str, object]] = []
    if isinstance(results, dict):
        if isinstance(results.get("results"), list):
            rows = [item for item in list(results.get("results") or []) if isinstance(item, dict)]
        else:
            for value in results.values():
                if isinstance(value, list):
                    rows.extend(item for item in value if isinstance(item, dict))
                elif isinstance(value, dict):
                    rows.append(value)
    elif isinstance(results, list):
        rows = [item for item in results if isinstance(item, dict)]
    return [_normalize_final_test_record(row) for row in rows]


def _normalize_final_test_record(record: dict[str, object]) -> dict[str, object]:
    """Normalize new and legacy final-test rows to the raw-record schema."""
    normalized = dict(record)
    raw = dict(record.get("raw") or {}) if isinstance(record.get("raw"), dict) else {}
    raw.setdefault("win_score", _legacy_final_test_win_score(record))
    raw.setdefault("score", record.get("score", record.get("resource_advantage_score")))
    raw.setdefault("ally", dict(record.get("ally") or {}) if isinstance(record.get("ally"), dict) else {})
    raw.setdefault("enemy", dict(record.get("enemy") or {}) if isinstance(record.get("enemy"), dict) else {})
    normalized["raw"] = raw

    paths = dict(record.get("paths") or {}) if isinstance(record.get("paths"), dict) else {}
    paths.setdefault("log", record.get("log_path", ""))
    paths.setdefault("trace_xml", record.get("trace_xml_path"))
    paths.setdefault("trace_json", record.get("trace_json_path"))
    normalized["paths"] = paths

    runtime = dict(record.get("runtime") or {}) if isinstance(record.get("runtime"), dict) else {}
    runtime.setdefault("interval_mode", record.get("interval_mode"))
    runtime.setdefault("llm_interval", record.get("llm_interval"))
    normalized["runtime"] = runtime

    if str(normalized.get("result") or "").strip().lower() not in {"win", "loss", "draw", "skipped", "failed"}:
        normalized["result"] = _result_from_win_score(raw.get("win_score"))
    return normalized


def _legacy_final_test_win_score(record: dict[str, object]) -> float:
    """Read a legacy final-test win score without using derived resources."""
    result = str(record.get("result") or "").strip().lower()
    if result == "win":
        return 1.0
    if result == "loss":
        return -1.0
    if result == "draw":
        return 0.0
    if "win_score" in record:
        return _safe_float(record.get("win_score"))
    for key in ("match_score", "fitness"):
        value = record.get(key)
        if isinstance(value, dict) and "win_score" in value:
            return _safe_float(value.get("win_score"))
        if isinstance(value, list) and value:
            return _safe_float(value[0])
    if "win" in record:
        return 1.0 if bool(record.get("win")) else -1.0
    return 0.0


def _result_from_win_score(value: object) -> str:
    """Map canonical win scores to result labels."""
    win_score = _safe_float(value)
    if win_score == 1.0:
        return "Win"
    if win_score == -1.0:
        return "Loss"
    return "Draw"


def _final_test_analysis_from_lines(text: str) -> dict[str, object]:
    """Build partial final-test fields from log markers."""
    result: dict[str, object] = {"has_final_test": True} if FINAL_TEST_MARKER_PATTERN.search(text) else {}
    if not result:
        return result
    opponents = set(re.findall(r"opponent\s+\d+/\d+:\s*([^\s(]+)", text, flags=re.IGNORECASE))
    maps = set(re.findall(r"\bmap(?:_location)?[=:]\s*([^\s,]+)", text, flags=re.IGNORECASE))
    if opponents:
        result["opponents"] = sorted(opponents)
    if maps:
        result["maps"] = sorted(maps)
    skipped = len(re.findall(r"\bskipped?\b", text, flags=re.IGNORECASE))
    failed = len(re.findall(r"\b(?:failed|error)\b", text, flags=re.IGNORECASE))
    if skipped:
        result["skipped_games"] = skipped
        result["skipped"] = True
    if failed:
        result["failed_games"] = failed
    return result


def _final_test_outcome(record: dict[str, object]) -> str:
    """Normalize one final-test row outcome."""
    status = str(record.get("status") or record.get("result") or "").strip().lower()
    if status in {"win", "loss", "draw", "skipped", "failed"}:
        return status
    if record.get("skipped") is True:
        return "skipped"
    if record.get("failed") is True or record.get("error"):
        return "failed"
    raw = record.get("raw")
    score = raw.get("win_score") if isinstance(raw, dict) else record.get("win_score")
    win_score = _safe_float(score)
    if math.isnan(win_score):
        return "unknown"
    if win_score == 1.0:
        return "win"
    if win_score == -1.0:
        return "loss"
    return "draw"


def _final_test_record_metrics(record: dict[str, object], weights: dict[str, float] | None = None) -> dict[str, float]:
    """Return derived raw metrics for one final-test replay record."""
    raw = dict(record.get("raw") or {}) if isinstance(record.get("raw"), dict) else {}
    ally = dict(raw.get("ally") or {})
    enemy = dict(raw.get("enemy") or {})
    ally_total = _snapshot_total_resources(ally)
    enemy_total = _snapshot_total_resources(enemy)
    weights = dict(weights or {})
    outcome = _final_test_outcome(record)
    return {
        "win_rate": 1.0 if outcome == "win" else 0.0,
        "score": _safe_float(raw.get("score")),
        "ally_resources": _safe_float(ally.get("resources")),
        "enemy_resources": _safe_float(enemy.get("resources")),
        "total_ally_resources": ally_total,
        "total_enemy_resources": enemy_total,
        "resource_difference": ally_total - enemy_total,
        "weighted_resource_score": _weighted_resource_score(ally, weights) - _weighted_resource_score(enemy, weights),
    }


def _snapshot_total_resources(snapshot: dict[str, object]) -> float:
    """Return the total resource and unit count for one player snapshot."""
    return sum(
        _safe_float(snapshot.get(key))
        for key in ("resources", "base_count", "barracks_count", "worker_count", "light_count", "heavy_count", "ranged_count")
    )


def _weighted_resource_score(snapshot: dict[str, object], weights: dict[str, float]) -> float:
    """Return the weighted resource score for one player snapshot."""
    if not weights:
        weights = {
            "resources": 1.0,
            "base": 1.0,
            "barracks": 1.0,
            "worker": 1.0,
            "light": 1.0,
            "heavy": 1.0,
            "ranged": 1.0,
        }
    key_map = {
        "resources": "resources",
        "base": "base_count",
        "barracks": "barracks_count",
        "worker": "worker_count",
        "light": "light_count",
        "heavy": "heavy_count",
        "ranged": "ranged_count",
    }
    return sum(_safe_float(snapshot.get(field)) * float(weights.get(weight_key, 0.0)) for weight_key, field in key_map.items())


def _safe_average(values: list[float]) -> float | None:
    """Return the arithmetic mean for one numeric series."""
    numeric_values = [value for value in values if value == value]
    if not numeric_values:
        return None
    return sum(numeric_values) / len(numeric_values)


def _aggregate_metric_values(values: list[float], aggregation: str) -> float | None:
    """Aggregate one metric series using the selected reduction."""
    numeric_values = [value for value in values if value == value]
    if not numeric_values:
        return None
    if aggregation == "best":
        return max(numeric_values)
    if aggregation == "worst":
        return min(numeric_values)
    return sum(numeric_values) / len(numeric_values)


def analyze_final_test_run(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    metric: str = "win_rate",
    aggregation: str = "mean",
    individual: str = "all",
    weights: dict[str, float] | None = None,
) -> dict[str, object]:
    """Analyze one raw final-test results directory and render a heatmap plot."""
    resolved_run_dir = Path(run_dir).resolve()
    results_path = _resolve_final_test_results_path(resolved_run_dir)
    if results_path is None:
        raise FileNotFoundError(f"No final_test results.json found under {resolved_run_dir}.")
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected final test payload in {results_path}.")
    individual_ids = _final_test_individual_ids(payload)
    selected_individual = _normalize_final_test_individual(individual, individual_ids)
    analysis_payload = _filter_final_test_payload_by_individual(payload, selected_individual)
    individual_label = _final_test_individual_label(selected_individual)

    resolved_output_dir = ensure_directory(Path(output_dir).resolve()) if output_dir is not None else ensure_directory(
        results_path.parent / "analysis"
    )
    summary = _final_test_analysis_summary(analysis_payload, metric=metric, aggregation=aggregation, weights=weights)
    summary["individual"] = selected_individual
    summary["individual_label"] = individual_label
    pair_rows = _final_test_pair_rows(analysis_payload, metric=metric, weights=weights)
    plot_path = _plot_final_test_heatmap(
        pair_rows,
        metric=metric,
        aggregation=aggregation,
        individual_label=individual_label,
        individual_slug=_final_test_individual_slug(selected_individual),
        output_dir=resolved_output_dir,
    )
    summary_payload = {
        **summary,
        "results_path": str(results_path),
        "analysis_dir": str(resolved_output_dir),
        "individual": selected_individual,
        "individual_label": individual_label,
        "individual_ids": individual_ids,
        "metric": metric,
        "aggregation": aggregation,
        "pair_rows": pair_rows,
        "heatmap_path": str(plot_path) if plot_path is not None else "",
        "text_lines": _final_test_text_lines(summary, pair_rows, metric=metric, aggregation=aggregation),
    }
    summary_path = resolved_output_dir / "analysis_summary.json"
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "results_path": str(results_path),
        "analysis_summary_json": str(summary_path),
        "metric_heatmap": str(plot_path) if plot_path is not None else "",
        "pair_rows_json": str(_write_pair_rows_json(resolved_output_dir, pair_rows)),
        "individual": selected_individual,
        "metric": metric,
        "aggregation": aggregation,
    }


def _final_test_individual_ids(payload: dict[str, object]) -> list[str]:
    """Return sorted individual ids present in a final-test payload."""
    return sorted(
        {
            str(record.get("individual_id"))
            for record in _final_test_records(payload.get("results"))
            if record.get("individual_id")
        }
    )


def _normalize_final_test_individual(individual: str, individual_ids: list[str]) -> str:
    """Return a valid individual filter value."""
    selected = str(individual or "all").strip() or "all"
    if selected == "all":
        return selected
    if selected in individual_ids:
        return selected
    return "all"


def _filter_final_test_payload_by_individual(payload: dict[str, object], individual: str) -> dict[str, object]:
    """Return a payload copy filtered to one individual id for analysis."""
    if individual == "all":
        return payload
    filtered_payload = dict(payload)
    filtered_payload["results"] = [
        record
        for record in _final_test_records(payload.get("results"))
        if str(record.get("individual_id")) == individual
    ]
    return filtered_payload


def _final_test_individual_label(individual: str) -> str:
    """Return the display label for one final-test individual filter."""
    if individual == "all":
        return "All individuals"
    return f"Individual {individual}"


def _final_test_individual_slug(individual: str) -> str:
    """Return a filesystem-safe label for one individual filter."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", individual or "all").strip("_") or "all"


def _resolve_final_test_results_path(run_dir: Path) -> Path | None:
    """Find the newest final-test results JSON file for one run."""
    direct = run_dir / "results.json"
    if direct.exists():
        return direct
    final_test_dir = run_dir / "final_test"
    if not final_test_dir.exists():
        return None
    candidates = [
        path
        for path in final_test_dir.glob("*/results.json")
        if path.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.parent.stat().st_mtime, path.parent.name))


def _final_test_analysis_summary(
    payload: dict[str, object],
    *,
    metric: str,
    aggregation: str,
    weights: dict[str, float] | None,
) -> dict[str, object]:
    """Build summary statistics for one final-test results payload."""
    records = _final_test_records(payload.get("results"))
    metrics = [_final_test_record_metrics(record, weights=weights) for record in records]
    wins = sum(int(_final_test_outcome(record) == "win") for record in records)
    losses = sum(int(_final_test_outcome(record) == "loss") for record in records)
    draws = sum(int(_final_test_outcome(record) == "draw") for record in records)
    maps = sorted({str(record.get("map")) for record in records if record.get("map")})
    opponents = sorted({str(record.get("opponent")) for record in records if record.get("opponent")})
    return {
        "has_final_test": bool(records),
        "source_run_dir": payload.get("source_run_dir"),
        "created_at": payload.get("created_at"),
        "mode": payload.get("mode"),
        "selection": payload.get("selection") or {},
        "config": payload.get("config") or {},
        "games": len(records),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": (wins / len(records)) if records else None,
        "maps": maps,
        "opponents": opponents,
        "mean_score": _safe_average([item["score"] for item in metrics]),
        "worst_score": min((item["score"] for item in metrics), default=None),
        "best_score": max((item["score"] for item in metrics), default=None),
        "mean_ally_resources": _safe_average([item["ally_resources"] for item in metrics]),
        "mean_enemy_resources": _safe_average([item["enemy_resources"] for item in metrics]),
        "mean_total_ally_resources": _safe_average([item["total_ally_resources"] for item in metrics]),
        "mean_total_enemy_resources": _safe_average([item["total_enemy_resources"] for item in metrics]),
        "mean_resource_difference": _safe_average([item["resource_difference"] for item in metrics]),
        "mean_weighted_resource_score": _safe_average([item["weighted_resource_score"] for item in metrics]),
        "metric": metric,
        "aggregation": aggregation,
    }


def _final_test_pair_rows(
    payload: dict[str, object],
    *,
    metric: str,
    weights: dict[str, float] | None,
) -> list[dict[str, object]]:
    """Aggregate final-test rows by map/opponent combination."""
    records = _final_test_records(payload.get("results"))
    pair_map: dict[tuple[str, str], list[dict[str, float]]] = {}
    for record in records:
        map_name = str(record.get("map") or record.get("map_name") or record.get("map_location") or "")
        opponent = str(record.get("opponent") or "")
        if not map_name or not opponent:
            continue
        pair_map.setdefault((map_name, opponent), []).append(_final_test_record_metrics(record, weights=weights))

    rows: list[dict[str, object]] = []
    for (map_name, opponent), metrics in sorted(pair_map.items()):
        row = {
            "map": map_name,
            "opponent": opponent,
            "count": len(metrics),
        }
        for key in (
            "win_rate",
            "score",
            "ally_resources",
            "enemy_resources",
            "total_ally_resources",
            "total_enemy_resources",
            "resource_difference",
            "weighted_resource_score",
        ):
            values = [float(item[key]) for item in metrics]
            row[f"mean_{key}"] = _safe_average(values)
            row[f"best_{key}"] = max(values) if values else None
            row[f"worst_{key}"] = min(values) if values else None
        row["selected_metric"] = metric
        row["selected_metric_mean"] = _aggregate_metric_values(
            [float(item.get(metric, 0.0)) for item in metrics if metric in item],
            "mean",
        )
        row["selected_metric_best"] = _aggregate_metric_values(
            [float(item.get(metric, 0.0)) for item in metrics if metric in item],
            "best",
        )
        row["selected_metric_worst"] = _aggregate_metric_values(
            [float(item.get(metric, 0.0)) for item in metrics if metric in item],
            "worst",
        )
        rows.append(row)
    return rows


def _plot_final_test_heatmap(
    pair_rows: list[dict[str, object]],
    *,
    metric: str,
    aggregation: str,
    individual_label: str,
    individual_slug: str,
    output_dir: Path,
) -> Path | None:
    """Render one map/opponent heatmap for the selected final-test metric."""
    plt = _require_matplotlib()
    if not pair_rows:
        return None
    maps = sorted({str(row.get("map")) for row in pair_rows if row.get("map")})
    opponents = sorted({str(row.get("opponent")) for row in pair_rows if row.get("opponent")})
    if not maps or not opponents:
        return None

    value_key = f"{aggregation}_{metric}"
    matrix: list[list[float]] = []
    for map_name in maps:
        row_values: list[float] = []
        for opponent in opponents:
            matched = next(
                (row for row in pair_rows if str(row.get("map")) == map_name and str(row.get("opponent")) == opponent),
                None,
            )
            row_values.append(_safe_float(matched.get(value_key)) if matched is not None else float("nan"))
        matrix.append(row_values)

    plt.figure(figsize=(max(8, len(opponents) * 1.2), max(6, len(maps) * 0.6)))
    image = plt.imshow(matrix, cmap="coolwarm", aspect="auto")
    plt.xticks(range(len(opponents)), [_clean_axis_label(name) for name in opponents], rotation=45, ha="right")
    plt.yticks(range(len(maps)), maps)
    plt.xlabel("Opponent")
    plt.ylabel("Map")
    plt.title(_compose_plot_title(f"Final Test {metric} ({aggregation}) - {individual_label}", None))
    colorbar = plt.colorbar(image)
    colorbar.set_label(metric.replace("_", " ").title())
    for row_index, row_values in enumerate(matrix):
        for col_index, value in enumerate(row_values):
            if math.isnan(value):
                continue
            plt.text(col_index, row_index, f"{value:.2f}", ha="center", va="center", fontsize=8, color="black")
    figure_path = output_dir / f"final_test_{metric}_{aggregation}_{individual_slug}.png"
    plt.tight_layout()
    plt.savefig(figure_path, dpi=200)
    plt.close()
    return figure_path


def _final_test_text_lines(
    summary: dict[str, object],
    pair_rows: list[dict[str, object]],
    *,
    metric: str,
    aggregation: str,
) -> list[str]:
    """Render a compact text summary for the final-test analysis panel."""
    lines = [
        f"Source run: {summary.get('source_run_dir')}",
        f"Mode: {summary.get('mode')}",
        f"Selection: {dict(summary.get('selection') or {}).get('type', 'unknown')}",
        f"Individual: {summary.get('individual_label', 'All individuals')}",
        f"Games: {summary.get('games', 0)}",
    ]
    if summary.get("win_rate") is not None:
        lines.append(f"Win rate: {float(summary['win_rate']) * 100:.1f}%")
    lines.append(f"Metric: {metric}")
    lines.append(f"Aggregation: {aggregation}")
    for row in pair_rows[:50]:
        lines.append(
            "- "
            f"{row['map']} | {row['opponent']} | "
            f"mean={_format_metric_value(row.get(f'mean_{metric}'))} "
            f"best={_format_metric_value(row.get(f'best_{metric}'))} "
            f"worst={_format_metric_value(row.get(f'worst_{metric}'))}"
        )
    return lines


def _write_pair_rows_json(output_dir: Path, pair_rows: list[dict[str, object]]) -> Path:
    """Persist the aggregated pair rows for downstream inspection."""
    path = output_dir / "pair_rows.json"
    path.write_text(json.dumps(pair_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _format_metric_value(value: object) -> str:
    """Format one metric value for text summaries."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(number):
        return "n/a"
    return f"{number:.4g}"


def _add_optional_text(values: set[str], value: object) -> None:
    """Add a non-empty text value to a set."""
    text = str(value or "").strip()
    if text:
        values.add(text)


def _time_analysis_from_summary(summary: dict[str, object]) -> dict[str, float]:
    """Build timing fields from a profiler summary object."""
    by_phase = summary.get("by_phase") if isinstance(summary.get("by_phase"), dict) else {}
    by_generation = summary.get("by_generation") if isinstance(summary.get("by_generation"), dict) else {}
    generation_values = [
        _safe_float(value)
        for generation, value in by_generation.items()
        if str(generation) != "-1" and _safe_float(value) == _safe_float(value)
    ]
    generation_values = [value for value in generation_values if not math.isnan(value)]
    total_runtime = _safe_float(summary.get("total_recorded_sec"))
    generation_runtime = _phase_total(by_phase, "generation_total") or sum(generation_values)
    return {
        "total_runtime": total_runtime if not math.isnan(total_runtime) else None,
        "generation_runtime": generation_runtime or None,
        "average_generation_time": (sum(generation_values) / len(generation_values)) if generation_values else None,
        "evaluation_time": _sum_phase_totals(by_phase, ("evaluate", "evaluation", "gameplay_match")) or None,
        "llm_call_time": _sum_phase_totals(by_phase, ("llm", "ollama")) or None,
    }


def _time_analysis_from_events(events: list[dict[str, object]]) -> dict[str, float]:
    """Build timing fields from profiler event rows."""
    total = 0.0
    generation_totals: dict[str, float] = {}
    evaluation_time = 0.0
    llm_call_time = 0.0
    for event in events:
        elapsed = _safe_float(event.get("elapsed_sec"))
        if math.isnan(elapsed):
            continue
        phase = str(event.get("phase") or "").lower()
        generation = event.get("generation")
        total += elapsed
        if generation is not None and str(generation) != "-1":
            generation_totals[str(generation)] = generation_totals.get(str(generation), 0.0) + elapsed
        if any(marker in phase for marker in ("evaluate", "evaluation", "gameplay_match")):
            evaluation_time += elapsed
        if "llm" in phase or "ollama" in phase:
            llm_call_time += elapsed
    generation_runtime = sum(generation_totals.values())
    return {
        "total_runtime": total or None,
        "generation_runtime": generation_runtime or None,
        "average_generation_time": (generation_runtime / len(generation_totals)) if generation_totals else None,
        "evaluation_time": evaluation_time or None,
        "llm_call_time": llm_call_time or None,
    }


def _time_analysis_from_lines(text: str) -> dict[str, float]:
    """Build timing fields from simple human-readable log lines."""
    result: dict[str, float] = {}
    key_map = {
        "total runtime": "total_runtime",
        "generation runtime": "generation_runtime",
        "average generation time": "average_generation_time",
        "evaluation time": "evaluation_time",
        "llm call time": "llm_call_time",
        "llm time": "llm_call_time",
    }
    for match in TIME_LINE_PATTERN.finditer(text):
        seconds = _duration_to_seconds(match.group("value"), match.group("unit"))
        result[key_map[match.group("label").lower()]] = seconds
    return result


def _phase_total(by_phase: object, phase: str) -> float:
    """Return total seconds for one named phase."""
    if not isinstance(by_phase, dict):
        return 0.0
    row = by_phase.get(phase)
    if not isinstance(row, dict):
        return 0.0
    value = _safe_float(row.get("total_sec"))
    return 0.0 if math.isnan(value) else value


def _sum_phase_totals(by_phase: object, markers: tuple[str, ...]) -> float:
    """Sum phase totals whose names contain any marker."""
    if not isinstance(by_phase, dict):
        return 0.0
    total = 0.0
    for phase, row in by_phase.items():
        if not isinstance(row, dict) or not any(marker in str(phase).lower() for marker in markers):
            continue
        value = _safe_float(row.get("total_sec"))
        if not math.isnan(value):
            total += value
    return total


def _duration_to_seconds(value: str, unit: str | None) -> float:
    """Normalize a parsed duration value to seconds."""
    amount = float(value)
    normalized_unit = str(unit or "s").lower()
    if normalized_unit == "ms":
        return amount / 1000.0
    if normalized_unit in {"m", "min", "mins", "minutes"}:
        return amount * 60.0
    return amount


def _fitness_dimension_from_data(value: object, in_fitness: bool = False) -> int:
    """Infer objective count from nested result data without using algorithm names."""
    if isinstance(value, dict):
        if "fitness" in value:
            return _fitness_dimension_from_data(value["fitness"], True)
        if in_fitness and value and all(_is_number_like(item) for item in value.values()):
            return len(value)
        return max((_fitness_dimension_from_data(item) for item in value.values()), default=0)
    if isinstance(value, (list, tuple)):
        if in_fitness and value and all(_is_number_like(item) for item in value):
            return len(value)
        return max((_fitness_dimension_from_data(item) for item in value), default=0)
    return 0


def _fitness_dimension_from_log(text: str) -> int:
    """Infer objective count from logged fitness vectors."""
    dimension = 0
    for line in text.splitlines():
        if "fitness" not in line.lower():
            continue
        payload = _fitness_payload_from_line(line)
        if isinstance(payload, dict) and payload and all(_is_number_like(value) for value in payload.values()):
            dimension = max(dimension, len(payload))
        elif isinstance(payload, list) and payload and all(_is_number_like(value) for value in payload):
            dimension = max(dimension, len(payload))
        elif isinstance(payload, (int, float)):
            dimension = max(dimension, 1)
    for match in FITNESS_VECTOR_PATTERN.finditer(text):
        values = [part.strip() for part in match.group(1).split(",") if part.strip()]
        dimension = max(dimension, len(values))
    if dimension == 0 and FITNESS_SCALAR_PATTERN.search(text):
        return 1
    return dimension


def _safe_number(value: object) -> float | None:
    """Return a float for numeric-looking text."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_number_like(value: object) -> bool:
    """Return whether a value can represent a numeric fitness component."""
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _extract_generation_number(path: Path) -> int:
    """Return the one-based generation number encoded in a log filename."""
    match = GENERATION_LOG_PATTERN.match(path.name)
    if not match:
        return -1
    return int(match.group(1))


def _find_latest_run_dir() -> Path:
    """Return the newest EAGLE run directory that contains generation logs."""
    candidates = []
    for path in EAGLE_LOGS_DIR.iterdir():
        if not path.is_dir():
            continue
        if any(path.glob("generation_*_mo.txt")):
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"No EA run directories with generation logs found under {EAGLE_LOGS_DIR}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _resolve_run_dir(run_dir: str | Path | None, latest: bool) -> Path:
    """Resolve the analysis target run directory."""
    if run_dir is not None:
        return Path(run_dir).resolve()
    if latest:
        return _find_latest_run_dir()
    raise ValueError("Provide --run-dir or use --latest.")


def _resolve_final_test_path(run_dir: Path) -> Path | None:
    """Find the final-test JSON payload under one run directory."""
    for filename in FINAL_TEST_CANDIDATES:
        candidate = run_dir / filename
        if candidate.exists():
            return candidate
    return None


def _safe_float(value: object) -> float:
    """Convert numeric-looking values to float and fall back to NaN."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _clean_axis_label(label: str) -> str:
    """Shorten fully qualified Java class names for plot labels."""
    return label.split(".")[-1]


def _compose_plot_title(default_title: str, custom_title: str | None) -> str:
    """Compose a plot title with an optional custom prefix."""
    if not custom_title:
        return default_title
    return f"{default_title} - {custom_title}"


def _debug_print(debug: bool, *values: object) -> None:
    """Print only when debug mode is enabled."""
    if debug:
        print(*values)


def _dominates(left_fitness: list[float], right_fitness: list[float]) -> bool:
    """Return whether one fitness vector Pareto-dominates another."""
    better_in_any = False
    for left_value, right_value in zip(left_fitness, right_fitness):
        if left_value < right_value:
            return False
        if left_value > right_value:
            better_in_any = True
    return better_in_any


def _population_objective_names(individuals: list) -> list[str]:
    """Return objective names present in a population without assuming count."""
    names: list[str] = []
    for individual in individuals:
        for name in normalize_fitness_dict(getattr(individual, "fitness", {})).keys():
            if name not in names:
                names.append(name)
    return names or ["objective_0", "objective_1"]


def _xy_fitness(individual, objective_names: list[str], x_objective: str, y_objective: str) -> tuple[float, float]:
    """Return selected objective values for scatter plotting."""
    values = fitness_values(getattr(individual, "fitness", {}), objective_names)
    x_index = objective_names.index(x_objective) if x_objective in objective_names else 0
    y_index = objective_names.index(y_objective) if y_objective in objective_names else 1
    x_value = _safe_float(values[x_index]) if len(values) > x_index else float("nan")
    y_value = _safe_float(values[y_index]) if len(values) > y_index else float("nan")
    return x_value, y_value


def _front_one_ids_from_population(individuals: list) -> set[str]:
    """Compute Front-1 ids directly from one population snapshot."""
    front_one: list = []
    objective_names_list = _population_objective_names(individuals)
    for candidate in individuals:
        candidate_fitness = fitness_values(getattr(candidate, "fitness", {}), objective_names_list)
        dominated = False
        for other in individuals:
            if other is candidate:
                continue
            other_fitness = fitness_values(getattr(other, "fitness", {}), objective_names_list)
            if _dominates(other_fitness, candidate_fitness):
                dominated = True
                break
        if not dominated:
            front_one.append(candidate)
    return {getattr(individual, "id", "") for individual in front_one}


def _load_generation_entries_from_checkpoints(run_dir: Path, debug: bool = False) -> list[tuple[int, list, set[str]]]:
    """Load complete generation populations from checkpoints when available."""
    checkpoints_path = run_dir / "checkpoints.jsonl"
    if not checkpoints_path.exists():
        return []

    latest_by_generation: dict[int, dict] = {}
    for raw_line in checkpoints_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("phase") != "generation_complete":
            continue
        generation = int(payload.get("generation", -999))
        latest_by_generation[generation] = payload

    loaded: list[tuple[int, list, set[str]]] = []
    for generation in sorted(latest_by_generation):
        payload = latest_by_generation[generation]
        individuals = [
            deserialize_individual(individual_payload)
            for individual_payload in list(payload.get("population") or [])
        ]
        if not individuals:
            continue
        _debug_print(debug, f"Loaded {len(individuals)} individuals from checkpoint for generation {generation+1}")
        front_one_ids = _front_one_ids_from_population(individuals)
        display_generation = generation + 1
        loaded.append((display_generation, individuals, front_one_ids))
    return loaded


def _load_generation_entries_from_logs(run_dir: Path) -> list[tuple[int, list, set[str]]]:
    """Load population snapshots plus Front-1 ids from generation logs."""
    generation_logs = sorted(run_dir.glob("generation_*_mo.txt"), key=_extract_generation_number)
    loaded = []
    for generation_log in generation_logs:
        generation_number = _extract_generation_number(generation_log)
        fronts = parse_individuals_from_ea_log(str(generation_log))
        front_one_ids = {
            getattr(individual, "id", "")
            for individual in (fronts[0] if fronts else [])
        }
        population = parse_population_snapshot_from_ea_log(str(generation_log))
        if population:
            loaded.append((generation_number, population, _front_one_ids_from_population(population)))
            continue
        flattened = [individual for front in fronts for individual in front]
        loaded.append((generation_number, flattened, front_one_ids))
    return loaded


def _load_generation_entries(run_dir: Path, debug: bool = False) -> list[tuple[int, list, set[str]]]:
    """Load complete populations for every generation, preferring generation logs."""
    from_logs = _load_generation_entries_from_logs(run_dir)
    if from_logs:
        _debug_print(debug, f"Loaded {len(from_logs)} generations from generation_*_mo.txt logs")
        return from_logs

    from_checkpoints = _load_generation_entries_from_checkpoints(run_dir, debug=debug)
    if from_checkpoints:
        _debug_print(debug, f"Loaded {len(from_checkpoints)} generations from checkpoints fallback")
        return from_checkpoints

    return []


def _plot_generation_scatter(
    run_dir: Path,
    output_dir: Path,
    custom_title: str | None = None,
    debug: bool = False,
    eval_mode: str = "match",
    x_objective: str | None = None,
    y_objective: str | None = None,
) -> list[Path]:
    """Render one combined plot plus one per-generation plot."""
    plt = _require_matplotlib()
    generation_entries = _load_generation_entries(run_dir, debug=debug)
    if not generation_entries:
        return []

    all_x_values: list[float] = []
    all_y_values: list[float] = []
    all_individuals = [individual for _, individuals, _ in generation_entries for individual in individuals]
    data_objective_names = _population_objective_names(all_individuals)
    specs = load_run_objective_specs(run_dir, dimension=len(data_objective_names))
    configured_names = objective_names(specs)
    objective_names_list = configured_names or data_objective_names
    for name in data_objective_names:
        if name not in objective_names_list:
            objective_names_list.append(name)
    if len(objective_names_list) < 2:
        return []
    axis_labels = objective_axis_labels(specs)
    selected_x, x_label = _resolve_plot_axis(x_objective, objective_names_list, axis_labels, fallback_index=0)
    selected_y, y_label = _resolve_plot_axis(y_objective, objective_names_list, axis_labels, fallback_index=1)
    for _, individuals, _ in generation_entries:
        for individual in individuals:
            x_value, y_value = _xy_fitness(individual, objective_names_list, selected_x, selected_y)
            if math.isnan(x_value) or math.isnan(y_value):
                continue
            all_x_values.append(x_value)
            all_y_values.append(y_value)

    if not all_x_values or not all_y_values:
        return []

    x_min = min(all_x_values)
    x_max = max(all_x_values)
    y_min = min(all_y_values)
    y_max = max(all_y_values)

    x_padding = max((x_max - x_min) * 0.08, 1.0)
    y_padding = max((y_max - y_min) * 0.08, 1.0)
    x_limits = (x_min - x_padding, x_max + x_padding)
    y_limits = (y_min - y_padding, y_max + y_padding)

    figure_paths: list[Path] = []
    plt.figure(figsize=(10, 8))
    cmap = plt.get_cmap("viridis", max(1, len(generation_entries)))

    max_gen = max(g[0] for g in generation_entries)

    for color_index, (generation_number, individuals, front_one_ids) in enumerate(generation_entries):
        if not individuals:
            continue

        color = cmap(color_index)
        non_front_pairs = []
        front_one_pairs = []

        for individual in individuals:
            x_value, y_value = _xy_fitness(individual, objective_names_list, selected_x, selected_y)
            _debug_print(
                debug,
                f"Gen {generation_number} - Individual {getattr(individual, 'id', '')}: "
                f"Fitness = ({x_value}, {y_value}), Front 1 = {getattr(individual, 'id', '') in front_one_ids}",
            )
            if math.isnan(x_value) or math.isnan(y_value):
                continue

            if getattr(individual, "id", "") in front_one_ids:
                front_one_pairs.append((x_value, y_value))
            else:
                non_front_pairs.append((x_value, y_value))

        if not non_front_pairs and not front_one_pairs:
            continue

        # 10 generation intervals with labels in the combined plot
        label = f"Gen {generation_number}" if generation_number % 10 == 0 else None

        if non_front_pairs:
            plt.scatter(
                [p[0] for p in non_front_pairs],
                [p[1] for p in non_front_pairs],
                color=color,
                edgecolors="none",
                alpha=0.8,
                label=label,
            )

        #  Front 1（
        if front_one_pairs:
            front_label = "Front 1" if generation_number == max_gen else None
            plt.scatter(
                [p[0] for p in front_one_pairs],
                [p[1] for p in front_one_pairs],
                color=color,
                edgecolors="black",
                linewidths=1.0,
                alpha=0.95,
                label=front_label,
            )

        # ===== per-generation plot =====
        plt.figure(figsize=(8, 6))

        if non_front_pairs:
            plt.scatter(
                [p[0] for p in non_front_pairs],
                [p[1] for p in non_front_pairs],
                color=color,
                edgecolors="none",
                alpha=0.8,
            )

        if front_one_pairs:
            plt.scatter(
                [p[0] for p in front_one_pairs],
                [p[1] for p in front_one_pairs],
                color=color,
                edgecolors="black",
                linewidths=1.0,
                alpha=0.95,
                label="Front 1",
            )

        plt.xlabel(x_label)
        plt.ylabel(y_label)
        plt.title(_compose_plot_title(f"Generation {generation_number} Fitness Distribution", custom_title))
        plt.xlim(*x_limits)
        plt.ylim(*y_limits)
        plt.grid(alpha=0.25)

        plt.legend(loc="best", fontsize=8)

        per_generation_path = output_dir / f"generation_{generation_number:03d}_fitness_scatter.png"
        plt.tight_layout()
        plt.savefig(per_generation_path, dpi=200)
        plt.close()
        figure_paths.append(per_generation_path)

    # ===== combined plot =====
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.title(_compose_plot_title("Generation Fitness Distribution", custom_title))
    plt.xlim(*x_limits)
    plt.ylim(*y_limits)
    plt.grid(alpha=0.25)

    plt.legend(loc="best", fontsize=8, ncols=2)

    figure_path = output_dir / "generation_fitness_scatter_all.png"
    plt.tight_layout()
    plt.savefig(figure_path, dpi=200)
    plt.close()

    figure_paths.insert(0, figure_path)
    return figure_paths


def _resolve_plot_axis(
    selected_objective: str | None,
    objective_names_list: list[str],
    axis_labels: dict[str, str],
    *,
    fallback_index: int,
) -> tuple[str, str]:
    """Return the objective key and display label for one selected plot axis."""
    if not objective_names_list:
        return "", ""

    fallback_name = objective_names_list[min(fallback_index, len(objective_names_list) - 1)]
    selected_text = str(selected_objective or "").strip()
    if selected_text in objective_names_list:
        name = selected_text
    else:
        label_matches = [
            name
            for name in objective_names_list
            if selected_text and selected_text in {axis_labels.get(name, ""), name}
        ]
        name = label_matches[0] if label_matches else fallback_name
    return name, axis_labels.get(name, name)


def _build_generation_gif(image_paths: list[Path], output_path: Path) -> Path | None:
    """Build one animated GIF from the per-generation scatter plots."""
    per_generation_images = [
        path for path in image_paths
        if path.name.startswith("generation_") and path.name != "generation_fitness_scatter_all.png"
    ]
    if not per_generation_images:
        return None

    Image = _require_pillow()
    frames = [Image.open(path).convert("RGBA") for path in per_generation_images]
    try:
        first_frame, *remaining_frames = frames
        first_frame.save(
            output_path,
            save_all=True,
            append_images=remaining_frames,
            duration=300,
            loop=0,
            disposal=2,
        )
    finally:
        for frame in frames:
            frame.close()
    return output_path


def _aggressiveness_values(
    generation_entries: list[tuple[int, list, set[str]]],
) -> list[tuple[int, object, float, dict[str, float]]]:
    """Return strategic aggressiveness values by generation and individual."""
    rows: list[tuple[int, object, float, dict[str, float]]] = []
    for generation, individuals, _ in generation_entries:
        for individual in individuals:
            fitness = normalize_fitness_dict(getattr(individual, "fitness", {}))
            if "strategic_aggressiveness" not in fitness:
                continue
            rows.append((generation, individual, float(fitness["strategic_aggressiveness"]), fitness))
    return rows


def _aggressiveness_generation_stats(rows: list[tuple[int, object, float, dict[str, float]]]) -> list[dict[str, float]]:
    """Return mean/std strategic aggressiveness per generation."""
    stats: list[dict[str, float]] = []
    generations = sorted({generation for generation, _, _, _ in rows})
    for generation in generations:
        values = [value for row_generation, _, value, _ in rows if row_generation == generation]
        if not values:
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        stats.append(
            {
                "generation": generation,
                "mean": mean,
                "std": math.sqrt(variance),
                "min": min(values),
                "max": max(values),
                "count": len(values),
            }
        )
    return stats


def _plot_aggressiveness_analysis(
    run_dir: Path,
    output_dir: Path,
    custom_title: str | None = None,
    debug: bool = False,
) -> dict[str, object]:
    """Render aggressiveness distribution, gameplay scatter, and colored Pareto plots."""
    plt = _require_matplotlib()
    generation_entries = _load_generation_entries(run_dir, debug=debug)
    rows = _aggressiveness_values(generation_entries)
    if not rows:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    stats = _aggressiveness_generation_stats(rows)
    stats_path = output_dir / "aggressiveness_stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    distribution_path = output_dir / "aggressiveness_distribution.png"
    plt.figure(figsize=(9, 5))
    generations = [row["generation"] for row in stats]
    means = [row["mean"] for row in stats]
    stds = [row["std"] for row in stats]
    plt.errorbar(generations, means, yerr=stds, marker="o", capsize=4)
    plt.ylim(-0.05, 1.05)
    plt.xlabel("Generation")
    plt.ylabel("Strategic aggressiveness")
    plt.title(_compose_plot_title("Aggressiveness Distribution", custom_title))
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(distribution_path, dpi=200)
    plt.close()

    gameplay_objective = _aggressiveness_gameplay_objective(rows)
    scatter_path = output_dir / "aggressiveness_vs_gameplay.png"
    if gameplay_objective:
        x_values = [row[2] for row in rows if gameplay_objective in row[3]]
        y_values = [row[3][gameplay_objective] for row in rows if gameplay_objective in row[3]]
        if x_values and y_values:
            plt.figure(figsize=(7, 6))
            plt.scatter(x_values, y_values, alpha=0.8)
            plt.xlim(-0.05, 1.05)
            plt.xlabel("Strategic aggressiveness")
            plt.ylabel(gameplay_objective)
            plt.title(_compose_plot_title("Aggressiveness vs Gameplay", custom_title))
            plt.grid(alpha=0.25)
            plt.tight_layout()
            plt.savefig(scatter_path, dpi=200)
            plt.close()

    colored_path = output_dir / "pareto_colored_by_aggressiveness.png"
    latest_generation = max(generation for generation, _, _, _ in rows)
    latest_entries = [
        entry for entry in generation_entries if entry[0] == latest_generation
    ]
    if latest_entries and gameplay_objective:
        _, individuals, front_one_ids = latest_entries[-1]
        x_name = gameplay_objective
        y_name = _second_plot_objective(individuals, x_name)
        if y_name:
            points = []
            for individual in individuals:
                fitness = normalize_fitness_dict(getattr(individual, "fitness", {}))
                if x_name in fitness and y_name in fitness and "strategic_aggressiveness" in fitness:
                    points.append((fitness[x_name], fitness[y_name], fitness["strategic_aggressiveness"], individual))
            if points:
                plt.figure(figsize=(8, 6))
                scatter = plt.scatter(
                    [point[0] for point in points],
                    [point[1] for point in points],
                    c=[point[2] for point in points],
                    cmap="plasma",
                    vmin=0.0,
                    vmax=1.0,
                    edgecolors=[
                        "black" if getattr(point[3], "id", "") in front_one_ids else "none"
                        for point in points
                    ],
                    linewidths=1.0,
                    alpha=0.9,
                )
                plt.colorbar(scatter, label="Strategic aggressiveness")
                plt.xlabel(x_name)
                plt.ylabel(y_name)
                plt.title(_compose_plot_title("Pareto Colored by Aggressiveness", custom_title))
                plt.grid(alpha=0.25)
                plt.tight_layout()
                plt.savefig(colored_path, dpi=200)
                plt.close()

    return {
        "aggressiveness_distribution": str(distribution_path),
        "aggressiveness_vs_gameplay": str(scatter_path) if scatter_path.exists() else "",
        "pareto_colored_by_aggressiveness": str(colored_path) if colored_path.exists() else "",
        "aggressiveness_stats_json": str(stats_path),
        "aggressiveness_stats": stats,
    }


def _aggressiveness_gameplay_objective(rows: list[tuple[int, object, float, dict[str, float]]]) -> str:
    """Choose a gameplay objective for aggressiveness scatter plots."""
    preferred = ("resource_advantage", "win_score")
    available = {key for _, _, _, fitness in rows for key in fitness if key != "strategic_aggressiveness"}
    for key in preferred:
        if key in available:
            return key
    return sorted(available)[0] if available else ""


def _second_plot_objective(individuals: list, first_objective: str) -> str:
    """Return a second objective for colored Pareto plotting."""
    names = _population_objective_names(individuals)
    for name in names:
        if name not in {first_objective, "strategic_aggressiveness"}:
            return name
    return "strategic_aggressiveness" if "strategic_aggressiveness" in names else ""


def _collect_final_test_mode_rows(results_payload: dict, interval_mode: str) -> tuple[list[str], list[str], list[list[float]]]:
    """Collect one heatmap matrix for one final-test mode."""
    records = _final_test_records(results_payload.get("results"))
    results: dict[str, list[dict[str, object]]] = {}
    for record in records:
        individual_id = str(record.get("individual_id") or "")
        if individual_id:
            results.setdefault(individual_id, []).append(record)
    individual_ids = sorted(results.keys())
    opponent_names: list[str] = []
    matrix: list[list[float]] = []

    for individual_id in individual_ids:
        rows = [
            row for row in list(results.get(individual_id) or [])
            if str(dict(row.get("runtime") or {}).get("interval_mode")) == interval_mode
        ]
        if not opponent_names:
            opponent_names = sorted({str(row.get("opponent")) for row in rows})

        row_values: list[float] = []
        for opponent in opponent_names:
            matched_row = next((row for row in rows if str(row.get("opponent")) == opponent), None)
            metrics = _final_test_record_metrics(matched_row) if matched_row is not None else {}
            row_values.append(
                _safe_float(metrics.get("score")) if matched_row is not None else float("nan")
            )
        matrix.append(row_values)

    return individual_ids, opponent_names, matrix


def _plot_final_test_mode(
    run_dir: Path,
    output_dir: Path,
    final_test_path: Path,
    interval_mode: str,
    custom_title: str | None = None,
) -> Path | None:
    """Render one heatmap for one final-test mode."""
    plt = _require_matplotlib()
    payload = json.loads(final_test_path.read_text(encoding="utf-8"))
    individual_ids, opponent_names, matrix = _collect_final_test_mode_rows(payload, interval_mode)

    if not individual_ids or not opponent_names:
        return None

    plt.figure(figsize=(max(8, len(opponent_names) * 1.2), max(6, len(individual_ids) * 0.6)))
    image = plt.imshow(matrix, cmap="coolwarm", aspect="auto")
    plt.xticks(range(len(opponent_names)), [_clean_axis_label(name) for name in opponent_names], rotation=45, ha="right")
    plt.yticks(range(len(individual_ids)), individual_ids)
    plt.xlabel("Opponent")
    plt.ylabel("Individual")
    plt.title(_compose_plot_title(f"Final Test Resource Advantage: {interval_mode}", custom_title))
    colorbar = plt.colorbar(image)
    colorbar.set_label("Resource Advantage Score")

    for row_index, row_values in enumerate(matrix):
        for col_index, value in enumerate(row_values):
            if math.isnan(value):
                continue
            plt.text(col_index, row_index, f"{value:.1f}", ha="center", va="center", fontsize=8, color="black")

    figure_path = output_dir / f"final_test_resource_{interval_mode}.png"
    plt.tight_layout()
    plt.savefig(figure_path, dpi=200)
    plt.close()
    return figure_path


def analyze_evolution_run(
    run_dir: str | Path | None = None,
    *,
    latest: bool = False,
    output_dir: str | Path | None = None,
    title: str | None = None,
    debug: bool = False,
    eval_mode: str = "match",
    x_objective: str | None = None,
    y_objective: str | None = None,
) -> dict[str, object]:
    """Generate evolution scatter plots and final-test resource heatmaps."""
    if eval_mode not in {"match", "round"}:
        raise ValueError(f"Unsupported eval_mode: {eval_mode!r}")

    resolved_run_dir = _resolve_run_dir(run_dir, latest)
    resolved_output_dir = ensure_directory(Path(output_dir).resolve()) if output_dir is not None else ensure_directory(
        resolved_run_dir / "analysis" / "evolution"
    )

    generation_figures = _plot_generation_scatter(
        resolved_run_dir,
        ensure_directory(resolved_output_dir / "generation_fitness"),
        custom_title=title,
        debug=debug,
        eval_mode=eval_mode,
        x_objective=x_objective,
        y_objective=y_objective,
    )
    generation_gif_path = _build_generation_gif(
        generation_figures,
        resolved_output_dir / "generation_fitness" / "generation_fitness_animation.gif",
    )
    aggressiveness_outputs = _plot_aggressiveness_analysis(
        resolved_run_dir,
        ensure_directory(resolved_output_dir / "aggressiveness"),
        custom_title=title,
        debug=debug,
    )

    final_test_path = _resolve_final_test_path(resolved_run_dir)
    final_test_figures: dict[str, str] = {}
    if final_test_path is not None:
        final_test_output_dir = ensure_directory(resolved_output_dir / "final_test")
        for interval_mode in FINAL_TEST_MODES:
            figure_path = _plot_final_test_mode(
                resolved_run_dir,
                final_test_output_dir,
                final_test_path,
                interval_mode,
                custom_title=title,
            )
            if figure_path is not None:
                final_test_figures[interval_mode] = str(figure_path)

    summary = {
        "run_dir": str(resolved_run_dir),
        "generation_scatter_figures": [str(path) for path in generation_figures],
        "generation_animation_gif": str(generation_gif_path) if generation_gif_path is not None else None,
        "aggressiveness": aggressiveness_outputs,
        "final_test_result_path": str(final_test_path) if final_test_path is not None else None,
        "final_test_figures": final_test_figures,
        "title": title,
        "debug": debug,
        "eval_mode": eval_mode,
        "x_objective": x_objective,
        "y_objective": y_objective,
        "objective_specs": [
            {
                "index": spec.index,
                "name": spec.name,
                "display_name": spec.display_name,
                "direction": spec.direction,
                "axis_label": spec.axis_label,
            }
            for spec in load_run_objective_specs(resolved_run_dir)
        ],
    }
    summary_path = resolved_output_dir / "analysis_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI for plotting one EAGLE evolution run."""
    parser = argparse.ArgumentParser(description="Plot EAGLE evolution fitness and final-test resource results.")
    parser.add_argument("--run-dir", default=None, help="Target EAGLE run directory under logs/eagle.")
    parser.add_argument("--latest", action="store_true", help="Analyze the latest run with generation logs.")
    parser.add_argument("--title", default=None, help="Custom title for the generated plots.")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode and print debug output.")
    parser.add_argument(
        "--eval-mode",
        choices=["match", "round"],
        default="match",
        help="Use 'round' for MicroRTS round legality/alignment objectives.",
    )
    parser.add_argument("--x-objective", default=None, help="Objective key for the scatter plot X axis.")
    parser.add_argument("--y-objective", default=None, help="Objective key for the scatter plot Y axis.")
    return parser


def main() -> None:
    """CLI entry point for evolution-result analysis."""
    parser = build_argument_parser()
    args = parser.parse_args()
    summary = analyze_evolution_run(
        run_dir=args.run_dir,
        latest=args.latest,
        title=args.title,
        debug=args.debug,
        eval_mode=args.eval_mode,
        x_objective=args.x_objective,
        y_objective=args.y_objective,
    )
    _debug_print(args.debug, json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
