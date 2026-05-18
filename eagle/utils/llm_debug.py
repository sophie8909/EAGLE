"""Best-effort JSONL logging for raw LLM requests and responses."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
PROMPT_TAIL_CHARS = 3000


def append_llm_debug_record(
    log_dir: Path | str | None,
    *,
    generation: Any = "",
    individual_id: Any = "",
    mode: Any = "",
    opponent: Any = "",
    model: Any = "",
    prompt: Any = "",
    request_payload: Any = None,
    raw_response_body: Any = "",
    parsed_response: Any = "",
    parser_result: Any = "",
    fallback_response: Any = "",
    error: Any = None,
) -> Path | None:
    """Append one LLM debug record to ``llm_debug.jsonl`` without affecting evaluation."""
    if log_dir is None:
        return None
    prompt_text = "" if prompt is None else str(prompt)
    path = Path(log_dir) / "llm_debug.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "log_dir": str(Path(log_dir)),
        "generation": "" if generation is None else str(generation),
        "individual_id": "" if individual_id is None else str(individual_id),
        "evaluation_mode": "" if mode is None else str(mode),
        "opponent": "" if opponent is None else str(opponent),
        "model": "" if model is None else str(model),
        "prompt_char_length": len(prompt_text),
        "prompt": prompt_text,
        "prompt_tail": prompt_text[-PROMPT_TAIL_CHARS:],
        "request_payload": request_payload or {},
        "raw_response_body": "" if raw_response_body is None else str(raw_response_body),
        "parsed_response": "" if parsed_response is None else parsed_response,
        "parser_result": "" if parser_result is None else parser_result,
        "fallback_response": "" if fallback_response is None else fallback_response,
        "error": "" if error is None else str(error),
    }
    line = json.dumps(record, ensure_ascii=False, default=str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        LOGGER.warning("llm debug write failed path=%s error=%s", path, exc)
        return None
    LOGGER.info("llm debug record written path=%s", path)
    return path
