"""Per-call logging for LLM inputs, responses, failures, and timing."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class LLMCallLogger:
    """Write one durable JSON artifact and optional run-level timing event per request."""

    def __init__(self, log_dir: Path, *, run_id: str | None = None, timing_path: Path | None = None) -> None:
        self.log_dir = log_dir
        self.run_id = run_id
        self.timing_path = timing_path
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
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_seconds: float | None = None,
    ) -> Path:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        correlation_id = f"{self.run_id or 'run'}:{sequence}"
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
            "run_id": self.run_id,
            "request_started_at": started_at,
            "request_finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "request_correlation_id": correlation_id,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.timing_path is not None:
            event = {
                "event": "llm_request",
                "run_id": self.run_id,
                "request_correlation_id": correlation_id,
                "generation": generation,
                "candidate_id": candidate_id,
                "operation_type": (metadata or {}).get("operation_type"),
                "operation_stage": stage,
                "server_or_endpoint": (metadata or {}).get("endpoint"),
                "model_id": model,
                "request_started_at": started_at,
                "request_finished_at": finished_at,
                "duration_seconds": duration_seconds,
                "status": status,
                "failure_category": (metadata or {}).get("failure_category") if status != "success" else None,
                "token_counts": (metadata or {}).get("token_counts"),
            }
            with self.timing_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False))
                handle.write("\n")
        return path


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "unknown"