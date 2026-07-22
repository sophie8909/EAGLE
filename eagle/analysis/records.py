"""Canonical readers for EAGLE run and candidate artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


CANDIDATE_ARTIFACT_PATHS = {
    "individual": "individual.json",
    "lineage": "lineage.json",
    "prompt": "prompt.json",
    "raw_llm_response": "generation/response_raw.txt",
    "extracted_code": "generation/extracted_candidate.java",
    "assembled_code": "generation/normalized_candidate.java",
    "generation_result": "generation/result.json",
    "validation": "validation/validation_result.json",
    "compilation": "compilation/compilation_result.json",
    "compiler_stdout": "compilation/stdout.txt",
    "compiler_stderr": "compilation/stderr.txt",
    "integration": "integration/integration_result.json",
    "matches": "raw_microrts_result.json",
    "game_metrics": "game_metrics.json",
    "code_quality": "code_quality.json",
    "objectives": "objectives.json",
    "failure": "result.json",
    "timing": "timing.json",
    "mutation": "mutation/metadata.json",
}


class ArtifactReadError(ValueError):
    """An existing canonical artifact could not be decoded."""


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    path: Path
    start_time: str
    status: str
    generation_count: int
    candidate_count: int
    success_count: int
    failure_count: int
    config_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    generation: int
    parent_ids: tuple[str, ...]
    operator: str
    mutation_type: str | None
    status: str
    objectives: dict[str, float]
    failure_category: str | None
    failure_stage: str | None
    failure_reason: str | None
    strategy_prompt: str
    generation_prompt: str
    generated_java: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateArtifacts:
    record: CandidateRecord
    rewritten_prompt: str
    raw_llm_response: str
    extracted_code: str
    assembled_code: str
    compilation: dict[str, Any] | None
    validation: dict[str, Any] | None
    integration: dict[str, Any] | None
    match_results: list[dict[str, Any]]
    failure: dict[str, Any] | None
    timing: dict[str, Any] | None
    mutation: dict[str, Any] | None
    artifact_paths: dict[str, Path]


def discover_runs(runs_dir: Path) -> list[RunSummary]:
    """Discover run directories without modifying them."""
    if not runs_dir.exists():
        return []
    summaries = [_summarize_run(path) for path in runs_dir.iterdir() if path.is_dir()]
    return sorted(summaries, key=lambda item: (item.start_time, item.run_id), reverse=True)


def load_candidate_records(run_dir: Path) -> list[CandidateRecord]:
    """Stream canonical `results.jsonl`, tolerating only a partial final line."""
    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        return _records_from_candidate_dirs(run_dir)
    records: list[CandidateRecord] = []
    with results_path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                if not line.endswith("\n") and handle.read(1) == "":
                    break
                raise ArtifactReadError(f"Cannot parse {results_path} line {index}: {exc}") from exc
            records.append(_record_from_result(payload, results_path))
    return records


def load_candidate(run_dir: Path, candidate_id: str) -> CandidateArtifacts:
    candidate_dir = run_dir / "candidates" / candidate_id
    if not candidate_dir.is_dir():
        raise FileNotFoundError(f"Candidate directory does not exist: {candidate_dir}")
    paths = {name: candidate_dir / relative for name, relative in CANDIDATE_ARTIFACT_PATHS.items()}
    individual = _read_json(paths["individual"], required=True)
    assert isinstance(individual, dict)
    record = _record_from_candidate(individual, paths["individual"])
    mutation = _read_json(paths["mutation"])
    rewritten = record.generation_prompt
    if isinstance(mutation, dict):
        rewrite = mutation.get("rewrite")
        if isinstance(rewrite, dict) and rewrite.get("rewritten_prompt"):
            rewritten = str(rewrite["rewritten_prompt"])
    return CandidateArtifacts(
        record=record,
        rewritten_prompt=rewritten,
        raw_llm_response=_read_text(paths["raw_llm_response"]),
        extracted_code=_read_text(paths["extracted_code"]),
        assembled_code=_read_text(paths["assembled_code"]),
        compilation=_as_dict(_read_json(paths["compilation"])),
        validation=_as_dict(_read_json(paths["validation"])),
        integration=_as_dict(_read_json(paths["integration"])),
        match_results=_as_dict_list(_read_json(paths["matches"])),
        failure=_as_dict(_read_json(paths["failure"])),
        timing=_as_dict(_read_json(paths["timing"])),
        mutation=_as_dict(mutation),
        artifact_paths={name: path for name, path in paths.items() if path.exists()},
    )


def _summarize_run(run_dir: Path) -> RunSummary:
    records = load_candidate_records(run_dir)
    resolved = _as_dict(_read_json(run_dir / "resolved_config.json")) or {}
    summary = _as_dict(_read_json(run_dir / "summary.json"))
    generations = {record.generation for record in records}
    failed = sum(record.status == "failed" or bool(record.failure_reason) for record in records)
    status = "complete" if summary is not None else "running" if records else "incomplete"
    return RunSummary(
        run_id=run_dir.name,
        path=run_dir,
        start_time=_run_start_time(run_dir),
        status=status,
        generation_count=len(generations),
        candidate_count=len(records),
        success_count=len(records) - failed,
        failure_count=failed,
        config_summary={
            key: resolved.get(key)
            for key in ("population_size", "generation_count", "opponent", "map", "llm_backend", "llm_topology")
            if key in resolved
        },
    )


def _record_from_result(payload: dict[str, Any], source: Path) -> CandidateRecord:
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise ArtifactReadError(f"Result has no candidate object: {source}")
    result = payload.get("candidate_result")
    if isinstance(result, dict):
        merged = dict(candidate)
        for key in ("failure_category", "failure_stage", "failure_reason"):
            if result.get(key) is not None:
                merged[key] = result[key]
        candidate = merged
    return _record_from_candidate(candidate, source)


def _record_from_candidate(candidate: dict[str, Any], source: Path) -> CandidateRecord:
    candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "").strip()
    if not candidate_id:
        raise ArtifactReadError(f"Candidate has no ID: {source}")
    objectives = candidate.get("fitness_objectives") or candidate.get("objectives") or {}
    if not isinstance(objectives, dict):
        objectives = {}
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    return CandidateRecord(
        candidate_id=candidate_id,
        generation=int(candidate.get("generation", 0)),
        parent_ids=tuple(str(value) for value in candidate.get("parent_ids", ())),
        operator=str(candidate.get("operator", "unknown")),
        mutation_type=str(candidate["mutation_type"]) if candidate.get("mutation_type") is not None else None,
        status=str(candidate.get("status", "unknown")),
        objectives={str(key): float(value) for key, value in objectives.items() if isinstance(value, (int, float)) and not isinstance(value, bool)},
        failure_category=_optional_text(candidate.get("failure_category") or metadata.get("failure_category")),
        failure_stage=_optional_text(candidate.get("failure_stage") or metadata.get("failure_stage")),
        failure_reason=_optional_text(candidate.get("failure_reason") or metadata.get("failure_reason")),
        strategy_prompt=str(candidate.get("strategy_prompt", "")),
        generation_prompt=str(candidate.get("generation_prompt", "")),
        generated_java=str(candidate.get("generated_java", "")),
        raw=candidate,
    )


def _records_from_candidate_dirs(run_dir: Path) -> list[CandidateRecord]:
    candidates_dir = run_dir / "candidates"
    if not candidates_dir.exists():
        return []
    records: list[CandidateRecord] = []
    for path in sorted(candidates_dir.glob("*/individual.json")):
        payload = _read_json(path, required=True)
        assert isinstance(payload, dict)
        records.append(_record_from_candidate(payload, path))
    return records


def _read_json(path: Path, *, required: bool = False) -> Any:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required artifact does not exist: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactReadError(f"Cannot parse JSON artifact {path}: {exc}") from exc


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _run_start_time(run_dir: Path) -> str:
    try:
        return datetime.strptime(run_dir.name[:15], "%Y%m%d_%H%M%S").isoformat()
    except ValueError:
        return datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat()
