"""Best-effort per-generation JSONL logging for LLM backend calls."""

from __future__ import annotations

from pathlib import Path

from eagle.logging import trace


INPUT_TAIL_CHARS = 3000


def _safe_generation_name(generation: int | str) -> str:
    """Return a filesystem-safe generation suffix."""
    text = str(generation).strip()
    if not text:
        return "unknown"
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text)


def record_llm_call(
    log_dir: Path | str | None,
    *,
    generation: int | str = "",
    individual_id: str = "",
    call_index: int | None = None,
    mode: str = "",
    opponent: str = "",
    turn: str | int = "",
    model: str = "",
    input_text: str = "",
    request_payload: dict | None = None,
    raw_response_body: str = "",
    parsed_response: str = "",
    final_response: str = "",
    fallback_response: str = "",
    error: str | None = None,
) -> None:
    """Append one LLM call to the generation JSONL file without affecting evaluation."""
    if log_dir is None:
        return
    generation_value = "unknown" if generation is None or str(generation).strip() == "" else generation
    path = Path(log_dir) / "llm_calls" / f"generation_{_safe_generation_name(generation_value)}.jsonl"
    input_value = "" if input_text is None else str(input_text)
    try:
        call_index_value = call_index
        if path.exists():
            existing_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if call_index_value is None:
                call_index_value = sum(1 for line in existing_lines if line.strip()) + 1
        resolved_call_index = _resolve_call_index(call_index_value)
        record = {
            "generation": generation_value,
            "individual_id": "" if individual_id is None else str(individual_id),
            "call_index": resolved_call_index,
            "mode": "" if mode is None else str(mode),
            "opponent": "" if opponent is None else str(opponent),
            "turn": "" if turn is None else str(turn),
            "model": "" if model is None else str(model),
            "prompt_chars": len(input_value),
            "input": input_value,
            "input_tail": input_value[-INPUT_TAIL_CHARS:],
            "request_payload": request_payload or {},
            "raw_response_body": "" if raw_response_body is None else str(raw_response_body),
            "parsed_response": "" if parsed_response is None else str(parsed_response),
            "final_response": "" if final_response is None else str(final_response),
            "fallback_response": "" if fallback_response is None else str(fallback_response),
            "error": None if error is None else str(error),
        }
        trace.record("llm_call", record, {"log_dir": log_dir, "generation": generation_value})
    except (OSError, TypeError, ValueError):
        return


def _resolve_call_index(call_index: int | str | None) -> int:
    """Return a stable integer call index for one trace record."""
    if call_index is None or str(call_index).strip() == "":
        return 1
    try:
        return int(call_index)
    except (TypeError, ValueError):
        return 1
