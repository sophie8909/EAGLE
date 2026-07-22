"""Shared EAGLE failure normalization, grouping, filtering, and export."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .records import CandidateRecord, load_candidate, load_candidate_records


def load_error_frame(run_dir: Path) -> pd.DataFrame:
    records = load_candidate_records(run_dir)
    rows: list[dict[str, object]] = []
    for record in records:
        if not (record.failure_reason or record.failure_category or record.status == "failed"):
            continue
        artifacts = None
        try:
            artifacts = load_candidate(run_dir, record.candidate_id)
        except FileNotFoundError:
            pass
        compilation = artifacts.compilation if artifacts is not None else None
        compiler_output = ""
        if isinstance(compilation, dict):
            compiler_output = str(compilation.get("stderr") or compilation.get("stdout") or "")
        category = normalize_failure_category(
            record.failure_category,
            record.failure_reason,
            record.failure_stage,
        )
        root_cause = normalize_root_cause(category, record.failure_reason or "", compiler_output)
        rows.append({
            "generation": record.generation,
            "candidate_id": record.candidate_id,
            "operator": record.operator,
            "status": record.status,
            "category": category,
            "pipeline_stage": record.failure_stage or "unknown",
            "root_cause": root_cause,
            "full_error": record.failure_reason or "",
            "raw_response": artifacts.raw_llm_response if artifacts is not None else "",
            "extracted_code": artifacts.extracted_code if artifacts is not None else "",
            "compiler_output": compiler_output,
            "validation_output": json.dumps(artifacts.validation, ensure_ascii=False, indent=2) if artifacts and artifacts.validation else "",
            "artifact_paths": json.dumps({name: str(path) for name, path in (artifacts.artifact_paths.items() if artifacts else ())}, ensure_ascii=False),
        })
    return pd.DataFrame(rows)


def normalize_failure_category(category: str | None, reason: str | None, stage: str | None = None) -> str:
    raw = (category or "").strip()
    lowered = f"{raw} {reason or ''}".lower()
    if "context size" in lowered or "context-size" in lowered or "exceeds the available context" in lowered:
        return "Context-size overflow"
    if "timeout" in lowered or "timed out" in lowered:
        return "Timeout"
    if "parse" in lowered or "invalid json" in lowered or "response is not valid" in lowered:
        return "Response parsing failure"
    if "artifact" in lowered or "persist" in lowered:
        return "Artifact failure"
    if raw:
        return raw
    if stage == "compilation" or "javac" in lowered or "compile" in lowered:
        return "Java compile failure"
    if stage == "validation" or "generated java" in lowered or "java source" in lowered:
        return "Java validation failure"
    if stage == "runtime" or "match" in lowered:
        return "Runtime match failure"
    if "backend" in lowered or "http" in lowered or "connection" in lowered:
        return "Backend request failure"
    return "Unknown failure"


def normalize_root_cause(category: str, reason: str, compiler_output: str = "") -> str:
    if compiler_output:
        compile_cause = compile_root_cause(compiler_output)
        if compile_cause:
            return compile_cause
    text = reason.strip()
    if not text:
        return category
    text = re.sub(r"(?:[A-Za-z]:)?[/\\][^\s:]+", "<path>", text)
    text = re.sub(r"\b[0-9a-f]{12,40}\b", "<id>", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:request_body_size|completed|attempted|port)=\d+\b", lambda match: match.group(0).split("=", 1)[0] + "=<n>", text)
    text = re.sub(r"https?://[^\s]+", "<url>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def compile_root_cause(stderr: str) -> str:
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
    return "other compile error" if message else ""


def first_javac_error(stderr: str) -> str:
    for line in stderr.splitlines():
        if ": error:" in line:
            return line.split(": error:", 1)[1].strip()
    return stderr.splitlines()[0] if stderr.splitlines() else ""


def filter_error_frame(
    frame: pd.DataFrame,
    *,
    generation_min: int | None = None,
    generation_max: int | None = None,
    categories: tuple[str, ...] = (),
    candidate_id: str = "",
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    mask = pd.Series(True, index=frame.index)
    if generation_min is not None:
        mask &= frame["generation"] >= generation_min
    if generation_max is not None:
        mask &= frame["generation"] <= generation_max
    if categories:
        mask &= frame["category"].isin(categories)
    if candidate_id:
        mask &= frame["candidate_id"].astype(str).str.contains(candidate_id, case=False, regex=False)
    return frame.loc[mask].copy()


def error_summary(frame: pd.DataFrame, *, total_candidates: int, total_failed: int | None = None) -> pd.DataFrame:
    columns = ["category", "count", "percent_all", "percent_failed"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    failed_count = len(frame) if total_failed is None else total_failed
    rows = []
    for category, count in frame["category"].value_counts().items():
        rows.append({
            "category": str(category),
            "count": int(count),
            "percent_all": 100 * int(count) / total_candidates if total_candidates else 0.0,
            "percent_failed": 100 * int(count) / failed_count if failed_count else 0.0,
        })
    return pd.DataFrame(rows, columns=columns)


def error_trend(frame: pd.DataFrame, *, candidates_per_generation: dict[int, int]) -> pd.DataFrame:
    columns = ["generation", "category", "failure_count", "failure_rate"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    grouped = frame.groupby(["generation", "category"]).size().reset_index(name="failure_count")
    grouped["failure_rate"] = grouped.apply(
        lambda row: float(row["failure_count"]) / candidates_per_generation.get(int(row["generation"]), 1),
        axis=1,
    )
    return grouped[columns]


def root_cause_groups(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["category", "root_cause", "count", "representative_message", "candidate_ids"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (category, cause), group in frame.groupby(["category", "root_cause"], dropna=False):
        rows.append({
            "category": str(category),
            "root_cause": str(cause),
            "count": len(group),
            "representative_message": str(group.iloc[0]["full_error"]),
            "candidate_ids": ", ".join(group["candidate_id"].astype(str)),
        })
    return pd.DataFrame(rows, columns=columns).sort_values("count", ascending=False, kind="stable")


def export_error_frame(frame: pd.DataFrame, path: Path, format_name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "csv":
        frame.to_csv(path, index=False)
    elif format_name == "json":
        path.write_text(frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    else:
        raise ValueError(f"Unsupported error export format: {format_name}")
    return path
