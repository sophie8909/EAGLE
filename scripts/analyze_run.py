"""Summarize EAGLE run failures from saved artifacts."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eagle.analysis.errors import compile_root_cause as shared_compile_root_cause
from eagle.analysis.errors import first_javac_error as shared_first_javac_error
from eagle.analysis.errors import normalize_failure_category
from eagle.analysis.final_tests import load_final_test_summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze an EAGLE run directory.")
    parser.add_argument("run_dir", help="Path to runs/<run_id>")
    args = parser.parse_args()
    print(format_report(analyze_run(Path(args.run_dir))))


def analyze_run(run_dir: Path) -> dict[str, Any]:
    records = read_candidate_results(run_dir)
    used_fallback = False
    if not records:
        records = read_results_jsonl(run_dir)
    if not records:
        records = read_failed_candidate_debug(run_dir)
        used_fallback = True

    failure_records = [record for record in records if record.get("failure_category")]
    success_count = None if used_fallback else len(records) - len(failure_records)

    category_counts = Counter(record["failure_category"] for record in failure_records)
    reason_counts = Counter(record.get("failure_reason") or "" for record in failure_records)
    validation_counts = Counter(
        validation_error(record)
        for record in failure_records
        if validation_error(record)
    )
    compile_counts = Counter(
        compile_root_cause(record)
        for record in failure_records
        if compile_root_cause(record)
    )
    representatives: dict[str, str] = {}
    for record in failure_records:
        category = record["failure_category"]
        representatives.setdefault(category, record.get("candidate_path", ""))

    return {
        "run_dir": str(run_dir),
        "total_candidates": len(records),
        "failed_candidates": len(failure_records),
        "success_count": success_count,
        "failure_category_counts": category_counts,
        "top_failure_reasons": reason_counts,
        "compile_root_cause_counts": compile_counts,
        "validation_failure_counts": validation_counts,
        "representatives": representatives,
        "final_tests": load_final_test_summaries(run_dir),
    }


def read_candidate_results(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "candidates").glob("*/candidate_result.json")):
        payload = read_json(path)
        payload["final_score"] = migrate_legacy_objectives(payload.get("final_score"))
        payload["candidate_path"] = str(path.parent)
        records.append(payload)
    return records


def read_failed_candidate_debug(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "failed_candidates").glob("*/failure.json")):
        payload = read_json(path)
        payload["candidate_id"] = path.parent.name
        payload["candidate_path"] = str(path.parent)
        records.append(payload)
    return records


def read_results_jsonl(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            candidate = payload.get("candidate") or {}
            failure_category = ""
            failure_reason = payload.get("error") or ""
            compile_result = payload.get("compile")
            validation_result = None
            if candidate.get("status") == "failed" or failure_reason:
                failure_category = category_from_legacy_record(candidate, failure_reason)
                if failure_category == "Java compile failure" and compile_result:
                    failure_reason = first_javac_error(str(compile_result.get("stderr") or ""))
                if failure_category == "Java validation failure":
                    validation_result = {"ok": False, "error": failure_reason}
            records.append(
                {
                    "candidate_id": candidate.get("id", ""),
                    "parent_ids": candidate.get("parent_ids", []),
                    "validation_result": validation_result,
                    "compile_result": compile_result,
                    "final_score": migrate_legacy_objectives(candidate.get("fitness_objectives")),
                    "failure_category": failure_category,
                    "failure_reason": failure_reason,
                    "candidate_path": str(run_dir / "candidates" / str(candidate.get("id", ""))),
                }
            )
    return records


def read_objective_scatter_records(run_dir: Path) -> list[dict[str, Any]]:
    records = read_results_jsonl_objective_records(run_dir)
    if not records:
        records = read_individual_objective_records(run_dir)
    if not records:
        records = read_generation_manifest_objective_records(run_dir)
    if not records:
        records = read_candidate_result_objective_records(run_dir)
    return sorted_objective_records(dedupe_objective_records(records))


def read_results_jsonl_objective_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            candidate = payload.get("candidate") or {}
            record = objective_record_from_candidate(candidate)
            if record is not None:
                records.append(record)
    return records


def read_individual_objective_records(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "candidates").glob("*/individual.json")):
        candidate = read_json(path)
        result_path = path.parent / "candidate_result.json"
        final_score = read_json(result_path).get("final_score") if result_path.exists() else None
        record = objective_record_from_candidate(candidate, final_score=final_score)
        if record is not None:
            records.append(record)
    return records


def read_generation_manifest_objective_records(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("generation_*_population.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        manifest_generation = generation_from_manifest_path(path)
        for candidate in payload:
            if not isinstance(candidate, dict):
                continue
            record = objective_record_from_candidate(candidate)
            if record is None:
                continue
            record["manifest_generation"] = manifest_generation
            records.append(record)
    return records


def read_candidate_result_objective_records(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "candidates").glob("*/candidate_result.json")):
        payload = read_json(path)
        record = objective_record_from_candidate_result(payload, candidate_id=path.parent.name)
        if record is not None:
            records.append(record)
    return records


def objective_record_from_candidate(
    candidate: dict[str, Any],
    *,
    final_score: object | None = None,
) -> dict[str, Any] | None:
    objectives = objective_payload(candidate, final_score=final_score)
    if not objectives:
        return None
    candidate_id = str(candidate.get("id") or candidate.get("candidate_id") or "")
    return {
        "generation": int_or_zero(candidate.get("generation")),
        "candidate_id": candidate_id,
        "code_quality": float_or_nan(objectives.get("code_quality")),
        "game_performance": float_or_nan(objectives.get("game_performance")),
        "source": "candidate",
    }


def objective_record_from_candidate_result(
    payload: dict[str, Any],
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    objectives = migrate_legacy_objectives(payload.get("final_score"))
    if not isinstance(objectives, dict):
        return None
    return {
        "generation": int_or_zero(payload.get("generation")),
        "candidate_id": str(payload.get("candidate_id") or candidate_id),
        "code_quality": float_or_nan(objectives.get("code_quality")),
        "game_performance": float_or_nan(objectives.get("game_performance")),
        "source": "candidate_result",
    }


def objective_payload(candidate: dict[str, Any], *, final_score: object | None = None) -> dict[str, Any]:
    for value in (
        final_score,
        candidate.get("fitness_objectives"),
        candidate.get("objectives"),
        candidate.get("final_score"),
    ):
        migrated = migrate_legacy_objectives(value)
        if isinstance(migrated, dict):
            return migrated
    return {}


def dedupe_objective_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        candidate_id = record.get("candidate_id") or ""
        if not candidate_id:
            anonymous.append({**record, "candidate_id": f"candidate_{index:04d}"})
            continue
        existing = by_id.get(candidate_id)
        if existing is None or objective_record_completeness(record) > objective_record_completeness(existing):
            by_id[candidate_id] = record
    return [*by_id.values(), *anonymous]


def objective_record_completeness(record: dict[str, Any]) -> int:
    return sum(not math.isnan(record[key]) for key in ("code_quality", "game_performance"))


def sorted_objective_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda record: (record["generation"], record["candidate_id"]))


def generation_from_manifest_path(path: Path) -> int:
    match = re.search(r"generation_(\d+)_population\.json$", path.name)
    return int(match.group(1)) if match else 0


def int_or_zero(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def float_or_nan(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def migrate_legacy_objectives(objectives: object) -> object:
    """Translate legacy objective names only while reading old artifacts."""
    if not isinstance(objectives, dict) or "code_quality" in objectives or "strategy_alignment" not in objectives:
        return objectives
    migrated = dict(objectives)
    migrated["code_quality"] = migrated.pop("strategy_alignment")
    return migrated


def category_from_legacy_record(candidate: dict[str, Any], error: str) -> str:
    stage = "compilation" if candidate.get("compile_status") == "failed" else None
    category = normalize_failure_category(None, error, stage)
    return "Other" if category == "Unknown failure" else category


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validation_error(record: dict[str, Any]) -> str:
    validation = record.get("validation_result") or {}
    return str(validation.get("error") or "")


def compile_root_cause(record: dict[str, Any]) -> str:
    compile_result = record.get("compile_result") or {}
    stderr = str(compile_result.get("stderr") or "")
    if not stderr:
        return ""
    return shared_compile_root_cause(stderr)


def first_javac_error(stderr: str) -> str:
    return shared_first_javac_error(stderr)


def format_report(summary: dict[str, Any]) -> str:
    lines = [
        f"Run: {summary['run_dir']}",
        f"Total candidates found: {summary['total_candidates']}",
        f"Failed candidates: {summary['failed_candidates']}",
    ]
    if summary["success_count"] is None:
        lines.append("Success count: unknown")
    else:
        lines.append(f"Success count: {summary['success_count']}")

    append_counter(lines, "Failure category counts", summary["failure_category_counts"])
    append_counter(lines, "Top failure reasons", summary["top_failure_reasons"], limit=10)
    append_counter(lines, "Compile root cause counts", summary["compile_root_cause_counts"])
    append_counter(lines, "Validation failure counts", summary["validation_failure_counts"])

    lines.append("")
    lines.append("Representative candidate paths:")
    if summary["representatives"]:
        for category, path in sorted(summary["representatives"].items()):
            lines.append(f"- {category}: {path}")
    else:
        lines.append("- none")
    lines.extend(("", "Final tests:"))
    if not summary["final_tests"]:
        lines.append("- none")
    for item in summary["final_tests"]:
        lines.append(f"- {item.final_test_id}: {item.status} {item.completed_matches}/{item.expected_matches} path={item.path}")
    return "\n".join(lines)


def append_counter(lines: list[str], title: str, counter: Counter, *, limit: int | None = None) -> None:
    lines.append("")
    lines.append(f"{title}:")
    items = counter.most_common(limit)
    if not items:
        lines.append("- none")
        return
    for key, count in items:
        display = key if key else "(blank)"
        lines.append(f"- {display}: {count}")


if __name__ == "__main__":
    main()
