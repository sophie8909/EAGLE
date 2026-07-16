"""Independent Strategy Alignment evaluator and structured response validation."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class StrategyAlignmentResult:
    request: str
    raw_response: str
    parsed_response: dict[str, Any] | None
    score: float
    reason: str
    status: str
    error: str | None
    started_at: str
    finished_at: str
    duration_seconds: float
    attempts: tuple[dict[str, Any], ...]

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attempts"] = [dict(item) for item in self.attempts]
        return payload


class StrategyAlignmentBackend(ABC):
    @abstractmethod
    def evaluate(self, request: str) -> str:
        """Return one raw structured alignment response."""


class MockStrategyAlignmentBackend(StrategyAlignmentBackend):
    def evaluate(self, request: str) -> str:
        return json.dumps(
            {
                "score": 10,
                "reason": "Mock evaluator confirms the generated behavior matches the supplied strategy.",
            }
        )


class OpenAICompatibleStrategyAlignmentBackend(StrategyAlignmentBackend):
    def __init__(self, base_url: str, model: str, *, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def url(self) -> str:
        prefix = self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"
        return f"{prefix}/chat/completions"

    def evaluate(self, request_text: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": request_text}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Strategy Alignment backend failed: {exc}") from exc
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Strategy Alignment backend returned invalid JSON: {exc}") from exc


def build_strategy_alignment_backend(
    name: str,
    *,
    base_url: str = "http://localhost:8080",
    model: str = "local-model",
) -> StrategyAlignmentBackend:
    if name == "mock":
        return MockStrategyAlignmentBackend()
    if name in {"openai", "llama_cpp"}:
        return OpenAICompatibleStrategyAlignmentBackend(base_url, model)
    raise ValueError(f"Unknown Strategy Alignment backend: {name}")


def evaluate_strategy_alignment(
    *,
    strategy_prompt: str,
    generated_java: str,
    behavior_summary: dict[str, Any] | None,
    backend: StrategyAlignmentBackend,
) -> StrategyAlignmentResult:
    request = build_alignment_request(strategy_prompt, generated_java, behavior_summary)
    started_at = _utc_now()
    started = time.monotonic()
    raw_response = ""
    status = "success"
    error: str | None = None
    parsed: dict[str, Any] | None = None
    score = 0.0
    reason = ""
    try:
        raw_response = backend.evaluate(request)
        parsed = parse_strategy_alignment_response(raw_response)
        score = float(parsed["score"])
        reason = str(parsed["reason"])
    except (RuntimeError, ValueError, TypeError) as exc:
        status = "failed"
        error = str(exc)
        reason = error
    finished_at = _utc_now()
    duration = max(0.0, time.monotonic() - started)
    attempt = {
        "attempt": 1,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration,
        "status": status,
        "error": error,
    }
    return StrategyAlignmentResult(
        request=request,
        raw_response=raw_response,
        parsed_response=parsed,
        score=score,
        reason=reason,
        status=status,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        attempts=(attempt,),
    )


def build_alignment_request(
    strategy_prompt: str,
    generated_java: str,
    behavior_summary: dict[str, Any] | None,
) -> str:
    behavior = json.dumps(behavior_summary or {}, ensure_ascii=False, sort_keys=True)
    return f"""Evaluate how well the generated MicroRTS Java implements the intended strategy.
Return only one JSON object with exactly:
{{"score": <number from 0 to 10>, "reason": "<concise evidence-based reason>"}}

Strategy prompt:
{strategy_prompt}

Generated CandidateAgent.java:
{generated_java}

Optional behavior summary:
{behavior}
"""


def parse_strategy_alignment_response(raw_response: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Strategy Alignment response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Strategy Alignment response must be a JSON object.")
    if set(payload) != {"score", "reason"}:
        raise ValueError("Strategy Alignment response must contain exactly score and reason.")
    score = payload["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("Strategy Alignment score must be numeric.")
    if not 0 <= float(score) <= 10:
        raise ValueError("Strategy Alignment score must be in [0, 10].")
    reason = payload["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Strategy Alignment reason must be a non-empty string.")
    return {"score": float(score), "reason": reason.strip()}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
