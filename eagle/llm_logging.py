"""Per-call logging for LLM inputs, responses, and failures."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class LLMCallLogger:
    """Write one durable JSON artifact for every actual LLM request attempt."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._sequence = 0

    def write(
        self,
        *,
        stage: str,
        input_text: str,
        response_text: str = "",
        status: str,
        backend: str,
        model: str,
        llm_profile: str | None = None,
        candidate_id: str | None = None,
        generation: int | None = None,
        module_name: str | None = None,
        attempt: int = 1,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        parts = [f"{sequence:06d}", safe_name(stage)]
        if candidate_id:
            parts.append(safe_name(candidate_id))
        if module_name:
            parts.append(safe_name(module_name))
        path = self.log_dir / ("_".join(parts) + ".json")
        payload = {
            "call_id": sequence,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "backend": backend,
            "model": model,
            "llm_profile": llm_profile,
            "candidate_id": candidate_id,
            "generation": generation,
            "module_name": module_name,
            "attempt": attempt,
            "input": input_text,
            "response": response_text,
            "error": error,
            "metadata": metadata or {},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "unknown"
