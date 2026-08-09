"""Independent Match Commentator role for one completed MicroRTS match."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from evaluation.match_trace import iter_match_trace


MATCH_COMMENTATOR_SYSTEM_PROMPT = """You are an expert MicroRTS match commentator and strategy analyst.

Analyze the match from the candidate agent's perspective. Use only the supplied
match state records and metadata. Cite a tick or tick range for every important
claim, distinguish observation from inference, explain state changes, and explain
why an event affected the outcome. Focus on opening development, economy,
production, army composition, positioning, defensive reactions, attack timing,
target selection, expansion, tactical exchanges, turning points, missed
opportunities, and decisive causes.

Do not rewrite Java or the strategy prompt. Do not calculate fitness. Do not give
vague advice without tick evidence. Do not claim unavailable information as fact.
Return only the required structured JSON output.
"""


class CommentaryBackend(Protocol):
    def generate(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class CommentaryConfig:
    enabled: bool = True
    temperature: float = 0.2
    chunk_ticks: int = 200
    max_attempts: int = 3


@dataclass(frozen=True)
class CommentaryResult:
    status: str
    match_id: str
    commentary: dict[str, Any] | None
    status_payload: dict[str, Any]


def commentate_match(
    match_result: Any,
    *,
    backend: CommentaryBackend,
    config: CommentaryConfig,
) -> CommentaryResult:
    """Commentate one match and persist all request/response evidence."""

    match_dir = Path(str(getattr(match_result, "match_dir", "")))
    match_id = match_dir.name or f"match_{getattr(match_result, 'match_index', -1):02d}"
    commentary_dir = match_dir / "commentary"
    commentary_dir.mkdir(parents=True, exist_ok=True)
    trace_path = Path(str(getattr(match_result, "trace_path", "")))
    integrity_path = Path(str(getattr(match_result, "trace_integrity_path", "")))
    metadata_path = Path(str(getattr(match_result, "match_metadata_path", "")))
    if not config.enabled:
        return _unavailable(commentary_dir, match_id, "disabled", "match_commentator is disabled")
    if not bool(getattr(match_result, "ok", False)):
        return _unavailable(commentary_dir, match_id, "match_failed", "completed match result is not successful")
    if not trace_path.is_file() or not integrity_path.is_file() or not metadata_path.is_file():
        return _unavailable(commentary_dir, match_id, "trace_unavailable", "required trace artifact is missing")

    coverage: list[dict[str, Any]] = []
    try:
        metadata = _read_json(metadata_path)
        integrity = _read_json(integrity_path)
        rows = list(iter_match_trace(trace_path))
        if not rows:
            raise ValueError("match trace contains no tick rows")
        if not bool(integrity.get("complete")):
            raise ValueError("match trace integrity is incomplete")
        chunks = _contiguous_chunks(rows, config.chunk_ticks)
        chunk_outputs: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            request = _chunk_prompt(metadata, match_result, chunk, index, len(chunks))
            output, attempts = _request_valid(backend, request, lambda value: validate_chunk(value, chunk), config.max_attempts)
            if output is None:
                raise ValueError(f"chunk {index} commentary failed after {attempts} attempts")
            coverage_item = _coverage_item(chunk, request, json.dumps(output, ensure_ascii=False), attempts)
            coverage.append(coverage_item)
            _write_json(commentary_dir / f"chunk_{index:03d}.json", {
                "coverage": coverage_item,
                "request": request,
                "response": output,
            })
            chunk_outputs.append(output)
        final_request = _final_prompt(metadata, match_result, integrity, coverage, chunk_outputs)
        final, attempts = _request_valid(
            backend,
            final_request,
            lambda value: validate_final(value, metadata, integrity),
            config.max_attempts,
        )
        _write_json(commentary_dir / "final_request.json", {
            "prompt": final_request,
            "coverage": coverage,
            "prompt_metadata": _prompt_metadata(final_request, coverage),
        })
        if final is None:
            _write_json(commentary_dir / "final_response.json", {"status": "invalid", "attempts": attempts})
            return _unavailable(commentary_dir, match_id, "invalid_response", "final commentary failed validation", covered=coverage)
        _write_json(commentary_dir / "final_response.json", {"status": "success", "attempts": attempts, "response": final})
        _write_json(commentary_dir / "match_commentary.json", final)
        status_payload = {
            "status": "success",
            "failure_category": None,
            "error": None,
            "attempt_count": sum(item["attempt_count"] for item in coverage) + attempts,
            "covered_tick_ranges": coverage,
            "coverage_complete": True,
        }
        _write_json(commentary_dir / "commentary_status.json", status_payload)
        return CommentaryResult("success", match_id, final, status_payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _unavailable(commentary_dir, match_id, "commentary_error", str(exc), covered=coverage)


def validate_chunk(value: object, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("chunk commentary must be an object")
    start, end = _range(value.get("tick_range"))
    expected = (int(rows[0]["tick"]), int(rows[-1]["tick"]))
    if (start, end) != expected:
        raise ValueError(f"chunk range {(start, end)} does not match supplied range {expected}")
    for tick in _referenced_ticks(value):
        if tick < start or tick > end:
            raise ValueError(f"chunk cites tick {tick} outside {start}-{end}")
    if not isinstance(value.get("events"), list) or not isinstance(value.get("turning_points"), list):
        raise ValueError("chunk commentary requires events and turning_points arrays")
    return value


def validate_final(value: object, metadata: dict[str, Any], integrity: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("final commentary must be an object")
    if value.get("match_id") != metadata.get("match_id"):
        raise ValueError("final commentary match_id does not match metadata")
    expected_side = metadata.get("candidate_side")
    if value.get("candidate_side") != expected_side:
        raise ValueError("final commentary candidate_side does not match metadata")
    coverage = value.get("coverage")
    if not isinstance(coverage, dict) or not coverage.get("all_ticks_processed"):
        raise ValueError("final commentary must assert complete tick coverage")
    if coverage.get("first_tick") != integrity.get("first_tick") or coverage.get("last_tick") != integrity.get("last_tick"):
        raise ValueError("final commentary coverage bounds do not match trace")
    first = integrity.get("first_tick")
    last = integrity.get("last_tick")
    if isinstance(first, int) and isinstance(last, int):
        for tick in _referenced_ticks(value):
            if tick < first or tick > last:
                raise ValueError(f"final commentary cites tick {tick} outside trace")
    for item in value.get("turning_points", []):
        if not isinstance(item, dict) or not item.get("evidence") and not item.get("evidence_ticks"):
            raise ValueError("turning points require tick evidence")
    for item in value.get("strategy_recommendations", []):
        if not isinstance(item, dict) or not item.get("supported_by_ticks"):
            raise ValueError("strategy recommendations require supporting ticks")
    return value


def _contiguous_chunks(rows: list[dict[str, Any]], chunk_ticks: int) -> list[list[dict[str, Any]]]:
    if chunk_ticks < 1:
        raise ValueError("chunk_ticks must be positive")
    ordered = sorted(rows, key=lambda row: int(row["tick"]))
    expected = list(range(int(ordered[0]["tick"]), int(ordered[-1]["tick"]) + 1))
    actual = [int(row["tick"]) for row in ordered]
    if actual != expected:
        raise ValueError("commentator requires a complete, duplicate-free trace")
    return [ordered[index:index + chunk_ticks] for index in range(0, len(ordered), chunk_ticks)]


def _chunk_prompt(metadata: dict[str, Any], match_result: Any, rows: list[dict[str, Any]], index: int, count: int) -> str:
    return MATCH_COMMENTATOR_SYSTEM_PROMPT + "\n\nMATCH_COMMENTATOR_OUTPUT=chunk\n" + json.dumps({
        "role": "match_commentator",
        "chunk_index": index,
        "chunk_count": count,
        "match_metadata": metadata,
        "candidate_side": metadata.get("candidate_side"),
        "opponent": metadata.get("opponent_name"),
        "tick_range": {"start": rows[0]["tick"], "end": rows[-1]["tick"]},
        "tick_records": rows,
        "required_output": _chunk_schema(),
    }, ensure_ascii=False, sort_keys=True)


def _final_prompt(metadata: dict[str, Any], match_result: Any, integrity: dict[str, Any], coverage: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> str:
    result = {
        "winner": getattr(match_result, "winner", None),
        "candidate_result": "win" if getattr(match_result, "winner", None) == getattr(match_result, "candidate_player", None) else "loss",
        "game_length": getattr(match_result, "final_cycle", None),
    }
    return MATCH_COMMENTATOR_SYSTEM_PROMPT + "\n\nMATCH_COMMENTATOR_OUTPUT=final\n" + json.dumps({
        "role": "match_commentator",
        "match_metadata": metadata,
        "candidate_side": metadata.get("candidate_side"),
        "opponent": metadata.get("opponent_name"),
        "map": metadata.get("map_name"),
        "final_result": result,
        "trace_coverage": integrity,
        "ordered_chunk_coverage": coverage,
        "ordered_chunk_analyses": chunks,
        "required_output": _final_schema(),
    }, ensure_ascii=False, sort_keys=True)


def _request_valid(backend: CommentaryBackend, request: str, validator: Any, max_attempts: int) -> tuple[dict[str, Any] | None, int]:
    last_error: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            value = json.loads(backend.generate(request))
            return validator(value), attempt
        except (OSError, RuntimeError, TimeoutError, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
    return None, max(1, max_attempts)


def _coverage_item(rows: list[dict[str, Any]], request: str, response: str, attempts: int) -> dict[str, Any]:
    return {
        "first_tick": rows[0]["tick"],
        "last_tick": rows[-1]["tick"],
        "tick_count": len(rows),
        "prompt_size": len(request),
        "response_size": len(response),
        "coverage_complete": True,
        "attempt_count": attempts,
    }


def _prompt_metadata(prompt: str, coverage: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "estimated_prompt_size": len(prompt),
        "section_sizes": {"system_prompt": len(MATCH_COMMENTATOR_SYSTEM_PROMPT), "chunk_coverage": len(json.dumps(coverage))},
        "included_tick_ranges": [{"first_tick": item["first_tick"], "last_tick": item["last_tick"]} for item in coverage],
        "omitted_sections": [],
        "truncated_sections": [],
        "coverage_status": "complete",
    }


def _range(value: object) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ValueError("tick_range must be an object")
    try:
        return int(value["start"]), int(value["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("tick_range requires start and end") from exc


def _referenced_ticks(value: object) -> list[int]:
    ticks: list[int] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"tick", "evidence_ticks", "supported_by_ticks"}:
                if isinstance(item, list):
                    ticks.extend(int(v) for v in item if isinstance(v, (int, float)))
                elif isinstance(item, (int, float)):
                    ticks.append(int(item))
            else:
                ticks.extend(_referenced_ticks(item))
    elif isinstance(value, list):
        for item in value:
            ticks.extend(_referenced_ticks(item))
    return ticks


def _unavailable(directory: Path, match_id: str, category: str, error: str, *, covered: list[dict[str, Any]] | None = None) -> CommentaryResult:
    payload = {
        "status": "unavailable",
        "failure_category": category,
        "error": error,
        "attempt_count": 0,
        "covered_tick_ranges": covered or [],
        "coverage_complete": False,
    }
    _write_json(directory / "commentary_status.json", payload)
    _write_json(directory / "match_commentary.json", {"status": "unavailable", "match_id": match_id, "error": error})
    return CommentaryResult("unavailable", match_id, None, payload)


def _chunk_schema() -> dict[str, Any]:
    return {"tick_range": {"start": 0, "end": 0}, "events": [], "turning_points": [], "candidate_strengths": [], "candidate_weaknesses": [], "possible_missed_opportunities": [], "state_at_chunk_end": ""}


def _final_schema() -> dict[str, Any]:
    return {"match_id": "", "candidate_side": "p0", "match_summary": "", "timeline": [], "turning_points": [], "candidate_strengths": [], "candidate_weaknesses": [], "opponent_behavior": [], "candidate_decision_errors": [], "missed_opportunities": [], "decisive_causes": [], "behaviors_to_preserve": [], "strategy_recommendations": [], "coverage": {"first_tick": 0, "last_tick": 0, "all_ticks_processed": True}}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
