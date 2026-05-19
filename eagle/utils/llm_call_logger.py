"""Best-effort per-generation JSON logging for LLM backend calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    error: str | None = None,
) -> None:
    """Append one LLM call to the generation JSON file without affecting evaluation."""
    if log_dir is None:
        return
    generation_value = "unknown" if generation is None or str(generation).strip() == "" else generation
    path = Path(log_dir) / "llm_calls" / f"generation_{_safe_generation_name(generation_value)}.json"
    input_value = "" if input_text is None else str(input_text)
    try:
        records: list[dict[str, Any]] = []
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            records = list(existing.get("records") or [])
        resolved_call_index = len(records) + 1 if call_index is None else int(call_index)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            "error": None if error is None else str(error),
        }
        records.append(record)
        payload = {"generation": generation_value, "records": records}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return
