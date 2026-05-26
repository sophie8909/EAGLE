"""Analysis helpers used by the NiceGUI workflow.

This module keeps reusable artifact parsing for the NiceGUI dashboard without
depending on a desktop GUI implementation.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eagle.utils.log_parse import parse_log_file


@dataclass
class AnalysisReport:
    """Display payload consumed by the NiceGUI services layer."""

    summary: str
    body: str
    rows: list[dict[str, Any]] | None = None


GA_ALGORITHMS = {"ga", "ga_surrogate"}


def build_live_analysis_report(run_dir: Path) -> AnalysisReport:
    """Build a compact live GA/MO analysis report from run artifacts."""
    config = _load_json_file(run_dir / "config.json")
    run_state = _load_json_file(run_dir / "run_state.json")
    algorithm = str(config.get("algorithm") or run_state.get("algorithm") or "unknown")
    mode = "GA" if algorithm.lower() in GA_ALGORITHMS else "MO"
    population = _load_population(run_dir)
    checkpoint_rows = _load_checkpoint_rows(run_dir)
    latest_generation = _latest_value([row.get("generation") for row in checkpoint_rows])
    phase = str(run_state.get("phase") or _latest_value([row.get("phase") for row in checkpoint_rows]) or "unknown")

    lines = [
        f"Run: {run_dir}",
        f"Algorithm: {algorithm} ({mode})",
        f"Current generation: {latest_generation if latest_generation is not None else 'unknown'}",
        f"Current phase: {phase}",
        f"Population records: {len(population)}",
        f"Checkpoint fitness rows: {len(checkpoint_rows)}",
        "",
    ]
    lines.extend(_operator_usage_lines(population, checkpoint_rows))
    lines.append("")
    if mode == "GA":
        lines.extend(_ga_analysis_lines(population, checkpoint_rows))
    else:
        lines.extend(_mo_analysis_lines(population, checkpoint_rows))

    summary = f"{mode} | generation={latest_generation if latest_generation is not None else 'unknown'} | phase={phase}"
    return AnalysisReport(summary=summary, body="\n".join(lines), rows=checkpoint_rows)


def build_timing_analysis_report(run_dir: Path) -> AnalysisReport:
    """Build timing analysis from run-level and per-evaluation profile artifacts."""
    summary = _load_json_file(run_dir / "timing_summary.json")
    profile_rows = _load_jsonl_rows(run_dir / "profiles.jsonl")
    timing_rows = list(summary.get("top_phases") or [])
    if not timing_rows:
        timing_rows = _aggregate_named_profile_times(profile_rows)

    lines = [
        f"Run: {run_dir}",
        f"Timing events: {summary.get('event_count', 0)}",
        f"Total recorded seconds: {float(summary.get('total_recorded_sec', 0.0)):.3f}",
        "",
        "Bottlenecks:",
    ]
    if timing_rows:
        for row in timing_rows[:12]:
            lines.append(
                f"  {row.get('phase')}: total={float(row.get('total_sec', 0.0)):.3f}s "
                f"count={int(row.get('count', 0))} avg={float(row.get('avg_sec', 0.0)):.3f}s"
            )
    else:
        lines.append("  no timing data found yet")

    profile_totals = _aggregate_named_profile_times(profile_rows)
    lines.extend(["", "Evaluation profile totals:"])
    if profile_totals:
        for row in profile_totals[:12]:
            lines.append(
                f"  {row['phase']}: total={row['total_sec']:.3f}s "
                f"count={row['count']} avg={row['avg_sec']:.3f}s"
            )
    else:
        lines.append("  no profile timing rows found yet")

    recommendations = list(summary.get("recommendations") or [])
    for item in _timing_recommendations(timing_rows, profile_totals):
        if item not in recommendations:
            recommendations.append(item)
    lines.extend(["", "Recommendations:"])
    for item in recommendations:
        lines.append(f"  - {item}")

    report_path = run_dir / "timing_report.md"
    if report_path.exists():
        lines.extend(["", "Saved report:", str(report_path)])
    return AnalysisReport(
        summary=f"timing phases={len(timing_rows)} profiles={len(profile_rows)}",
        body="\n".join(lines),
        rows=timing_rows,
    )


def load_prompts(run_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Load prompt-inspection records for the selected run."""
    if run_dir is None:
        return {}
    profile_records = _latest_generation_profile_records(run_dir)
    checkpoint_records = _latest_generation_checkpoint_prompt_records(run_dir)
    if profile_records and checkpoint_records:
        if _records_latest_generation(checkpoint_records) > _records_latest_generation(profile_records):
            return checkpoint_records
        return profile_records
    if profile_records:
        return profile_records
    if checkpoint_records:
        return checkpoint_records
    return _generation_log_prompt_records(run_dir)


def _load_json_file(path: Path) -> dict[str, Any]:
    """Load one JSON object, returning an empty mapping when absent."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    """Load JSONL object rows and ignore blank lines."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line.lstrip("\ufeff"))
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL row must be an object: {path}:{line_number}")
        rows.append(payload)
    return rows


def _load_population(run_dir: Path) -> list[dict[str, Any]]:
    """Load checkpointed population from run_state.json."""
    state = _load_json_file(run_dir / "run_state.json")
    population = state.get("population")
    return [dict(item) for item in population if isinstance(item, dict)] if isinstance(population, list) else []


def _load_checkpoint_rows(run_dir: Path) -> list[dict[str, Any]]:
    """Load checkpoint rows from JSONL artifacts when present."""
    rows: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("checkpoint*.jsonl")):
        rows.extend(_load_jsonl_rows(path))
    if rows:
        return [row for row in rows if isinstance(row.get("individual"), dict)]
    return [{"generation": "state", "phase": "run_state", "individual": item} for item in _load_population(run_dir)]


def _latest_generation_profile_records(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Return profile rows for the latest generation present in profiles.jsonl."""
    rows = [row for row in _load_jsonl_rows(run_dir / "profiles.jsonl") if row.get("record_type") == "evaluation"]
    if not rows:
        return {}
    latest_generation = _latest_generation_value([row.get("generation") for row in rows])
    latest_rows = [row for row in rows if row.get("generation") == latest_generation]
    records: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(latest_rows, start=1):
        prompt = str(row.get("prompt") or "")
        if not prompt:
            continue
        record = dict(row)
        record["raw_generation"] = row.get("generation")
        record["generation"] = _display_generation(row.get("generation"))
        record["prompt"] = prompt
        record["llm_output"] = _llm_output_from_profile_record(record)
        records[_prompt_record_id(record, index)] = record
    return records


def _latest_generation_checkpoint_prompt_records(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Return prompt rows from the latest checkpoint generation when profiles are absent."""
    rows = _load_checkpoint_rows(run_dir)
    if not rows:
        return {}
    latest_generation = _latest_generation_value([row.get("generation") for row in rows])
    latest_rows = [row for row in rows if row.get("generation") == latest_generation]
    records: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(latest_rows, start=1):
        item = dict(row.get("individual") or {})
        prompt = str(item.get("rendered_prompt") or "")
        if not prompt:
            continue
        evaluation = _prompt_evaluation_from_individual(item)
        record = {
            "raw_generation": row.get("generation"),
            "generation": _display_generation(row.get("generation")),
            "phase": row.get("phase", ""),
            "individual_id": item.get("id"),
            "evaluation_mode": item.get("evaluation_mode") or evaluation.get("evaluation_mode", ""),
            "opponent": "",
            "prompt": prompt,
            "llm_output": _llm_output_from_evaluation(evaluation),
            "fitness": item.get("fitness"),
        }
        records[_prompt_record_id(record, index)] = record
    return records


def _generation_log_prompt_records(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Fallback prompt extraction from human-readable generation logs."""
    records: dict[str, dict[str, Any]] = {}
    paths = sorted(run_dir.glob("generation*.txt"))
    if not paths:
        return records
    latest_path = paths[-1]
    text = latest_path.read_text(encoding="utf-8", errors="replace")
    for index, block in enumerate(text.split("Prompt:\n")[1:], start=1):
        prompt = block.split("\nIndividual(", 1)[0].split("\nPopulation", 1)[0].strip()
        if not prompt:
            continue
        record = {
            "generation": latest_path.stem,
            "individual_id": f"prompt-{index}",
            "evaluation_mode": "generation_log",
            "opponent": "",
            "prompt": prompt,
            "llm_output": "No LLM output recorded in generation log.",
        }
        records[_prompt_record_id(record, index)] = record
    return records


def _llm_output_from_profile_record(record: dict[str, Any]) -> str:
    """Return all LLM outputs attached to one profile row."""
    if isinstance(record.get("round_samples"), list):
        return _format_round_samples(record["round_samples"])
    output = _llm_output_from_log_path(record.get("log_path"))
    if output:
        return output
    return "No LLM output recorded for this evaluation."


def _llm_output_from_evaluation(evaluation: dict[str, Any]) -> str:
    """Return all LLM outputs attached to one checkpoint evaluation object."""
    samples = evaluation.get("samples")
    if isinstance(samples, list):
        return _format_round_samples(samples)
    if evaluation.get("raw_response"):
        return str(evaluation["raw_response"])
    per_opponent = evaluation.get("per_opponent")
    if isinstance(per_opponent, list):
        sections = []
        for item in per_opponent:
            if not isinstance(item, dict):
                continue
            output = _llm_output_from_log_path(item.get("log_path"))
            if output:
                sections.append(f"Opponent: {item.get('opponent', '')}\n{output}")
        if sections:
            return "\n\n".join(sections)
    return "No LLM output recorded for this evaluation."


def _format_round_samples(samples: list[Any]) -> str:
    """Format every round-sample LLM response."""
    sections: list[str] = []
    for index, sample in enumerate(samples, start=1):
        if not isinstance(sample, dict):
            continue
        response = str(sample.get("raw_response") or "")
        dynamic_prompt = str(sample.get("dynamic_prompt") or "")
        sections.append(
            f"Sample {sample.get('sample', index)}\n"
            f"Dynamic prompt:\n{dynamic_prompt}\n\n"
            f"LLM output:\n{response}"
        )
    return "\n\n".join(sections) if sections else "No fresh LLM samples; this evaluation reused history."


def _llm_output_from_log_path(path_value: Any) -> str:
    """Parse raw LLM responses from one MicroRTS gameplay log when available."""
    if not path_value:
        return ""
    path = _resolve_runtime_log_path(str(path_value))
    if not path.exists():
        return ""
    parsed = parse_log_file(path)
    sections: list[str] = []
    for segment in parsed.get("segments", []):
        if not isinstance(segment, dict):
            continue
        response = segment.get("raw_llm_response_text")
        if not response:
            continue
        sections.append(f"Turn {segment.get('current_time', segment.get('segment_index', ''))}\n{response}")
    return "\n\n".join(sections)


def _resolve_runtime_log_path(path_text: str) -> Path:
    """Resolve Windows, repo-relative, or WSL-mounted runtime log paths."""
    normalized = path_text.replace("\\", "/")
    drive_match = re.fullmatch(r"/mnt/([a-zA-Z])/(.*)", normalized)
    if drive_match:
        drive = drive_match.group(1).upper()
        rest = drive_match.group(2).replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    path = Path(path_text)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


def _prompt_record_id(record: dict[str, Any], index: int) -> str:
    """Build a stable prompt-table row id."""
    parts = [
        str(record.get("generation", "")),
        str(record.get("individual_id", "")),
        str(record.get("opponent", "")),
        str(index),
    ]
    return "|".join(part.replace("|", "/") for part in parts)


def _prompt_evaluation_from_individual(item: dict[str, Any]) -> dict[str, Any]:
    """Return the most detailed evaluation object stored on one checkpointed individual."""
    for key in ("last_round_evaluation", "last_gameplay_evaluation", "last_surrogate_evaluation"):
        value = item.get(key)
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _records_latest_generation(records: dict[str, dict[str, Any]]) -> int:
    """Return the newest internal generation value from loaded prompt records."""
    values = [record.get("raw_generation", record.get("generation")) for record in records.values()]
    generation = _latest_generation_value(values)
    try:
        return int(generation)
    except (TypeError, ValueError):
        return -1


def _latest_generation_value(values: list[Any]) -> Any:
    """Return the newest internal generation value, treating numeric generations as ordered."""
    numeric_values: list[int] = []
    for value in values:
        try:
            numeric_values.append(int(value))
        except (TypeError, ValueError):
            continue
    if numeric_values:
        return max(numeric_values)
    return _latest_value(values)


def _display_generation(value: Any) -> Any:
    """Convert an internal zero-based generation into the GUI display generation."""
    try:
        return int(value) + 1
    except (TypeError, ValueError):
        return value


def _latest_value(values: list[Any]) -> Any:
    """Return the last non-empty value from a list."""
    for value in reversed(values):
        if value not in (None, ""):
            return value
    return None


def _fitness_values(fitness: Any) -> list[float]:
    """Normalize fitness payloads to an ordered float list."""
    if isinstance(fitness, dict):
        return [float(value) for _, value in sorted(fitness.items()) if _is_number(value)]
    if isinstance(fitness, list):
        return [float(value) for value in fitness if _is_number(value)]
    if _is_number(fitness):
        return [float(fitness)]
    return []


def _is_number(value: Any) -> bool:
    """Return whether value can be interpreted as a finite float."""
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _scalar_score(individual: dict[str, Any]) -> float | None:
    """Return the GA scalar score; the first objective is the canonical scalar."""
    values = _fitness_values(individual.get("fitness"))
    return values[0] if values else None


def _operator_usage_lines(population: list[dict[str, Any]], checkpoint_rows: list[dict[str, Any]]) -> list[str]:
    """Summarize operator and mutation usage from available metadata."""
    items = list(population)
    items.extend(row["individual"] for row in checkpoint_rows if isinstance(row.get("individual"), dict))
    operator_counter: Counter[str] = Counter()
    mutation_counter: Counter[str] = Counter()
    for item in items:
        profile = item.get("operator_profile") or {}
        mutation_metadata = item.get("mutation_metadata") or {}
        operator_type = profile.get("operator_type")
        mutation_mode = profile.get("mutation_mode") or mutation_metadata.get("mutation_mode")
        if operator_type:
            operator_counter[str(operator_type)] += 1
        if mutation_mode:
            mutation_counter[str(mutation_mode)] += 1
    lines = ["Operator usage:"]
    lines.append("  operators: " + (", ".join(f"{key}={value}" for key, value in operator_counter.items()) or "none"))
    lines.append("  mutation modes: " + (", ".join(f"{key}={value}" for key, value in mutation_counter.items()) or "none"))
    return lines


def _ga_analysis_lines(population: list[dict[str, Any]], checkpoint_rows: list[dict[str, Any]]) -> list[str]:
    """Build GA first-objective analysis lines."""
    lines = ["GA analysis:"]
    scored = [(_scalar_score(item), item) for item in population]
    scored = [(score, item) for score, item in scored if score is not None]
    if scored:
        best_score, best = max(scored, key=lambda pair: pair[0])
        lines.append(f"  current best first objective: {best_score:.4f} id={best.get('id')}")
    generation_best: dict[Any, float] = {}
    for row in checkpoint_rows:
        individual = row.get("individual")
        if not isinstance(individual, dict):
            continue
        score = _scalar_score(individual)
        if score is None:
            continue
        generation = row.get("generation")
        generation_best[generation] = max(score, generation_best.get(generation, score))
    if generation_best:
        lines.append("  best by generation:")
        for generation in sorted(generation_best, key=lambda value: (value is None, value)):
            lines.append(f"    gen {generation}: {generation_best[generation]:.4f}")
    else:
        lines.append("  no GA fitness history found yet")
    return lines


def _mo_analysis_lines(population: list[dict[str, Any]], checkpoint_rows: list[dict[str, Any]]) -> list[str]:
    """Build MO Pareto-front analysis lines."""
    active_population = population or [
        row["individual"] for row in checkpoint_rows if isinstance(row.get("individual"), dict)
    ]
    vectors = [(_fitness_values(item.get("fitness")), item) for item in active_population]
    vectors = [(values, item) for values, item in vectors if len(values) >= 2]
    lines = ["MO analysis:"]
    if not vectors:
        lines.append("  no two-objective fitness data found yet")
        return lines
    front = _nondominated_front(vectors)
    lines.append(f"  objective count: {len(vectors[0][0])}")
    lines.append(f"  non-dominated front size: {len(front)}")
    lines.append("  front sample:")
    for values, item in front[:20]:
        vector_text = ", ".join(f"{value:.4f}" for value in values)
        lines.append(f"    id={item.get('id')} fitness=[{vector_text}]")
    return lines


def _nondominated_front(vectors: list[tuple[list[float], dict[str, Any]]]) -> list[tuple[list[float], dict[str, Any]]]:
    """Return maximization non-dominated front for fitness vectors."""
    front: list[tuple[list[float], dict[str, Any]]] = []
    for values, item in vectors:
        if any(_dominates(other_values, values) for other_values, _other_item in vectors if other_values is not values):
            continue
        front.append((values, item))
    return front


def _dominates(left: list[float], right: list[float]) -> bool:
    """Return whether left Pareto-dominates right under maximization."""
    pairs = list(zip(left, right))
    return bool(pairs) and all(a >= b for a, b in pairs) and any(a > b for a, b in pairs)


def _aggregate_named_profile_times(profile_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate numeric `*_time` profile fields across evaluation rows."""
    totals: dict[str, dict[str, float]] = {}
    for row in profile_rows:
        for key, value in row.items():
            if not str(key).endswith("_time") or not _is_number(value):
                continue
            stats = totals.setdefault(str(key), {"count": 0.0, "total_sec": 0.0, "max_sec": 0.0})
            elapsed = float(value)
            stats["count"] += 1.0
            stats["total_sec"] += elapsed
            stats["max_sec"] = max(stats["max_sec"], elapsed)
    rows: list[dict[str, Any]] = []
    for phase, stats in totals.items():
        count = max(1.0, stats["count"])
        rows.append(
            {
                "phase": phase,
                "count": int(stats["count"]),
                "total_sec": stats["total_sec"],
                "avg_sec": stats["total_sec"] / count,
                "max_sec": stats["max_sec"],
            }
        )
    return sorted(rows, key=lambda item: item["total_sec"], reverse=True)


def _timing_recommendations(
    timing_rows: list[dict[str, Any]],
    profile_totals: list[dict[str, Any]],
) -> list[str]:
    """Return simple GUI recommendations from timing rows."""
    rows = list(timing_rows) + list(profile_totals)
    if not rows:
        return ["No timing data has been recorded yet."]
    top_phase = str(rows[0].get("phase") or "")
    hints: list[str] = []
    if "game" in top_phase or "evaluate" in top_phase:
        hints.append("Evaluation is the main cost; reduce game seconds, opponents, gameplay_rate, or one_eval_rounds.")
    if any(str(row.get("phase")) == "microrts_compile_time" and float(row.get("total_sec", 0.0)) > 1.0 for row in rows):
        hints.append("MicroRTS compile time is visible; repeated runs should benefit from incremental compile skipping.")
    if any("round_llm" in str(row.get("phase")) for row in rows):
        hints.append("Round LLM calls are visible; prompt-history reuse and fewer round samples will speed iteration.")
    hints.append("Python precompile is useful for import/startup overhead, not for Java or LLM-heavy sections.")
    return hints
