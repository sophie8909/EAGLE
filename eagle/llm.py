"""Shared LLM configuration, transport, progress, errors, and durable logging.

All EAGLE LLM roles use one endpoint/model. This module contains the shared
infrastructure; role-specific prompts and mutation stages remain in their
respective EA-step modules.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, BinaryIO
from urllib.parse import urlparse


__all__ = [
    "DEFAULT_MAX_PROMPT_CHARS",
    "EndpointConfigError",
    "LLMCallLogger",
    "LLMClient",
    "LLMServerError",
    "llm_request_progress",
    "read_chat_completion_content",
    "safe_name",
    "truncate_prompt",
]


# Errors
class LLMServerError(RuntimeError):
    """A request could not be completed by the configured LLM server."""


# Shared endpoint and client configuration
class EndpointConfigError(ValueError):
    """The shared LLM endpoint or model configuration is invalid."""


@dataclass(frozen=True)
class LLMClient:
    """One immutable OpenAI-compatible client configuration for the whole EA."""

    base_url: str
    model: str
    timeout_seconds: float = 120.0
    temperature: float = 0.2
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise EndpointConfigError("LLM endpoint must be a valid HTTP(S) URL.")

    def generation_backend(self, *, logger=None):
        """Build the shared final Java-generation backend lazily."""

        from generation.backend import build_generation_backend

        return build_generation_backend(
            "openai",
            base_url=self.base_url,
            model=self.model,
            logger=logger,
            operation="generation",
            timeout_sec=self.timeout_seconds,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )

    def prompt_backend(self, *, operation: str, temperature: float | None = None):
        """Build a shared Reflection/role backend lazily."""

        from eagle.mutation import build_reflection_backend

        return build_reflection_backend(
            "openai",
            base_url=self.base_url,
            model=self.model,
            operation=operation,
            timeout_sec=self.timeout_seconds,
            temperature=self.temperature if temperature is None else temperature,
            max_output_tokens=self.max_output_tokens,
        )


# OpenAI-compatible response decoding and prompt bounds
# llama.cpp context includes both prompt and generated output.  Keeping the
# request below this bound leaves room for the configured response budget on a
# 32K context server while still retaining substantially more than the normal
# EAGLE prompts.  Large raw telemetry remains persisted in run artifacts.
DEFAULT_MAX_PROMPT_CHARS = 60_000


def truncate_prompt(prompt: str, *, max_chars: int = DEFAULT_MAX_PROMPT_CHARS) -> str:
    """Hard-limit an LLM prompt while preserving instructions and latest evidence."""
    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    if len(prompt) <= max_chars:
        return prompt
    marker = (
        "\n\n[ EAGLE: prompt truncated to fit the server context; "
        "raw evidence remains in artifacts ]\n\n"
    )
    available = max_chars - len(marker)
    head = available * 2 // 3
    tail = available - head
    return prompt[:head] + marker + prompt[-tail:]


def read_chat_completion_content(response: BinaryIO) -> str:
    """Read either an SSE streaming response or one JSON completion response."""

    try:
        lines = iter(response)
    except TypeError:
        return _content_from_payload(json.loads(response.read().decode("utf-8")))

    content: list[str] = []
    buffered: list[bytes] = []
    saw_sse = False
    for raw_line in lines:
        buffered.append(raw_line)
        line = raw_line.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        saw_sse = True
        data = line[5:].strip()
        if data == "[DONE]":
            break
        payload = json.loads(data)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            continue
        message = choice.get("delta") or choice.get("message") or {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content.append(message["content"])
    if saw_sse:
        return "".join(content)
    return _content_from_payload(json.loads(b"".join(buffered).decode("utf-8")))


def _content_from_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        raise TypeError("chat completion response must be an object")
    choices = payload["choices"]
    if not isinstance(choices, list) or not choices:
        raise KeyError("choices")
    message = choices[0]["message"]
    return str(message["content"])

# Blocking-request progress reporting
@contextmanager
def llm_request_progress(
    *,
    stage: str,
    endpoint: str,
    model: str,
    candidate_id: str | None = None,
    heartbeat_seconds: float = 30.0,
) -> Iterator[None]:
    """Report only abnormal requests unless verbose LLM progress is enabled."""

    started = time.monotonic()
    stopped = threading.Event()
    verbose = os.environ.get("EAGLE_LLM_PROGRESS", "").lower() in {"1", "true", "yes", "on"}
    candidate_text = f" candidate={candidate_id}" if candidate_id else ""
    prefix = f"[llm {stage}]{candidate_text} endpoint={endpoint} model={model}"
    if verbose:
        print(f"{prefix} status=started", flush=True)

    def heartbeat() -> None:
        while not stopped.wait(heartbeat_seconds):
            elapsed = time.monotonic() - started
            print(f"{prefix} status=waiting elapsed_seconds={elapsed:.1f}", flush=True)

    thread = None
    if verbose:
        thread = threading.Thread(target=heartbeat, name=f"llm-{stage}-heartbeat", daemon=True)
        thread.start()
    try:
        yield
    except BaseException as exc:
        elapsed = time.monotonic() - started
        detail = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:300]
        print(f"{prefix} status=failed elapsed_seconds={elapsed:.1f} error={detail}", flush=True)
        raise
    else:
        if verbose:
            elapsed = time.monotonic() - started
            print(f"{prefix} status=completed elapsed_seconds={elapsed:.1f}", flush=True)
    finally:
        stopped.set()
        if thread is not None:
            thread.join(timeout=1)

# Durable request/response and timing logging
class LLMCallLogger:
    """Write one durable JSON artifact and optional run-level timing event per request."""

    def __init__(self, log_dir: Path, *, run_id: str | None = None, timing_path: Path | None = None) -> None:
        self.log_dir = log_dir
        self.run_id = run_id
        self.timing_path = timing_path
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._sequence = max(
            (
                int(path.name.split("_", 1)[0])
                for path in self.log_dir.glob("[0-9][0-9][0-9][0-9][0-9][0-9]_*.json")
                if path.name.split("_", 1)[0].isdigit()
            ),
            default=0,
        )

    def write(
        self,
        *,
        stage: str,
        input_text: str,
        response_text: str = "",
        status: str,
        backend: str,
        model: str,
        operation: str | None = None,
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
        details = metadata or {}
        payload = {
            "call_id": sequence,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "backend": backend,
            "model": model,
            "operation": operation,
            "candidate_id": candidate_id,
            "generation": generation,
            "module_name": module_name,
            "attempt": attempt,
            "generation_attempt": details.get("generation_attempt"),
            "generation_attempt_id": details.get("generation_attempt_id"),
            "transport_attempt": details.get("transport_attempt"),
            "generation_request_kind": details.get("generation_request_kind"),
            "input": input_text,
            "response": response_text,
            "error": error,
            "metadata": details,
            "run_id": self.run_id,
            "request_started_at": started_at,
            "request_finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "request_correlation_id": correlation_id,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.write_timing_event(
            request_correlation_id=correlation_id,
            stage=stage,
            status=status,
            model=model,
            candidate_id=candidate_id,
            generation=generation,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            metadata=metadata,
        )
        return path

    def write_timing_event(
        self,
        *,
        request_correlation_id: str,
        stage: str,
        status: str,
        model: str | None,
        candidate_id: str | None,
        generation: int | None,
        started_at: str | None,
        finished_at: str | None,
        duration_seconds: float | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append timing for a request whose full evidence has another owner.

        Strategy Reflection already persists exact request/response artifacts
        below the candidate.  This method adds only the canonical run timing
        event so ``llm_logs`` does not duplicate those large payloads.
        """

        if self.timing_path is None:
            return
        details = metadata or {}
        event = {
            "event": "llm_request",
            "run_id": self.run_id,
            "request_correlation_id": request_correlation_id,
            "generation": generation,
            "candidate_id": candidate_id,
            "operation_type": details.get("operation_type"),
            "operation_stage": stage,
            "server_or_endpoint": details.get("endpoint"),
            "model_id": model,
            "request_started_at": started_at,
            "request_finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "status": status,
            "failure_category": details.get("failure_category") if status != "success" else None,
            "token_counts": details.get("token_counts"),
            "generation_attempt": details.get("generation_attempt"),
            "generation_attempt_id": details.get("generation_attempt_id"),
            "transport_attempt": details.get("transport_attempt"),
            "generation_request_kind": details.get("generation_request_kind"),
        }
        self.timing_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.timing_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False))
                handle.write("\n")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "unknown"
