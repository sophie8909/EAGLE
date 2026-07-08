"""Summarize EAGLE run failures from saved artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


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
    }


def read_candidate_results(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "candidates").glob("*/candidate_result.json")):
        payload = read_json(path)
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
                    "final_score": candidate.get("fitness_objectives"),
                    "failure_category": failure_category,
                    "failure_reason": failure_reason,
                    "candidate_path": str(run_dir / "candidates" / str(candidate.get("id", ""))),
                }
            )
    return records


def category_from_legacy_record(candidate: dict[str, Any], error: str) -> str:
    lowered = error.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "Timeout"
    if candidate.get("compile_status") == "failed":
        return "Java compile failure"
    if candidate.get("compile_status") == "not_run":
        if "backend" in lowered or "http error" in lowered:
            return "Backend request failure"
        if "generated java" in lowered or "java source" in lowered or "must not" in lowered:
            return "Java validation failure"
        return "Other"
    return "Other"


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
    message = first_javac_error(stderr)
    lowered = message.lower()
    if "cannot find symbol" in lowered:
        return "cannot find symbol"
    if "incompatible types" in lowered or "cannot be converted" in lowered:
        return "incompatible types"
    if " is already defined" in lowered:
        if "method " in lowered:
            return "duplicate method"
        if "variable " in lowered:
            return "duplicate variable"
        return "duplicate definition"
    if "missing return" in lowered:
        return "missing return"
    if "illegal character" in lowered:
        return "illegal character"
    if any(token in lowered for token in ("; expected", ") expected", "illegal start of", "not a statement")):
        return "syntax error"
    return "other compile error"


def first_javac_error(stderr: str) -> str:
    for line in stderr.splitlines():
        if ": error:" in line:
            return line.split(": error:", 1)[1].strip()
    return stderr.splitlines()[0] if stderr.splitlines() else ""


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
