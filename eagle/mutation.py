"""Canonical reflector stage for EAGLE mutation.

Prompt rewriting is intentionally owned by the next migration stage. This
module currently provides typed evidence, a transport abstraction, retry
handling, timing, and durable Reflection results for all prompt mutation types.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .candidate import Candidate
from .config import ExperimentConfig
from .llm import (
    LLMServerError,
    llm_request_progress,
    parse_json_object_response,
    read_chat_completion_content,
    truncate_prompt,
)
from .reflection_context import (
    CandidateReflectionSummary,
    CodeDiagnostics,
    EvolutionContext,
    GameplayDiagnostics,
    MapReflectionResult,
    ObjectiveSummary,
    OpponentReflectionSummary,
    ReflectionContext,
)
# Compatibility re-exports used by the reflection/rewrite API and tests.
from .reflection_prompts import (
    build_prompt_reflection_prompt,
    build_prompt_reflection_prompt_bundle,
    build_strategy_reflection_prompt,
    build_strategy_reflection_prompt_bundle,
)


# Typed request/result records and response parsing are shared by Prompt
# Reflection and Strategy Reflection. The concrete strategy role sequence is
# intentionally kept in eagle.strategy_reflection.
REFLECTION_SCHEMA_VERSION = "reflection-v2"
DEFAULT_STRUCTURED_OUTPUT_TOKENS = 4096


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Public compatibility name used by the existing mutation/rewrite API.
MutationContext = ReflectionContext


@dataclass(frozen=True)
class ReflectionAttempt:
    attempt: int
    started_at: str
    finished_at: str
    duration_seconds: float
    status: str
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReflectionResult:
    """Structured, lossless result of one Reflection stage."""

    stage: str
    reflection_type: str
    request: str
    raw_response: str
    reflection: str
    status: str
    attempts: tuple[ReflectionAttempt, ...] = ()
    error: str | None = None
    model: str | None = None
    backend: str | None = None
    operation: str | None = None
    token_counts: dict[str, int] | None = None
    parsed_response: dict[str, object] | None = None
    analysis_summary: str = ""
    revised_prompt: str = ""
    prompt_metadata: dict[str, object] | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REFLECTION_SCHEMA_VERSION,
            "stage": self.stage,
            "reflection_type": self.reflection_type,
            "request": self.request,
            "raw_response": self.raw_response,
            "reflection": self.reflection,
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "error": self.error,
            "model": self.model,
            "backend": self.backend,
            "operation": self.operation,
            "token_counts": self.token_counts,
            "parsed_response": self.parsed_response,
            "analysis_summary": self.analysis_summary,
            "revised_prompt": self.revised_prompt,
            "prompt_metadata": self.prompt_metadata,
        }


def parse_reflection_response(response: str, reflection_type: str) -> tuple[dict[str, object], str, str]:
    """Parse the JSON contracts used by Strategy and Prompt Reflection."""
    lowered = str(response).lower()
    if "```java" in lowered or "package ai.generated" in lowered or "public class candidateagent" in lowered:
        raise ValueError("Reflection response must not contain generated Java.")
    reflection_type = reflection_type.removesuffix("_reflection")
    payload = parse_json_object_response(response)
    if reflection_type == "strategy":
        diagnosis = payload.get("diagnosis")
        if isinstance(diagnosis, dict) and isinstance(payload.get("mutation_plan"), dict):
            revised = payload.get("revised_strategy_prompt")
            if not isinstance(revised, str) or not revised.strip():
                raise ValueError("Reflection response must contain non-empty revised_strategy_prompt.")
            summary = json.dumps({"diagnosis": diagnosis, "mutation_plan": payload["mutation_plan"]}, ensure_ascii=False, sort_keys=True)
            return payload, summary, revised.strip()
        required = ("strengths", "weaknesses", "priority_changes")
        revised_key = "revised_strategy_prompt"
        analysis = payload.get("analysis")
        if not isinstance(analysis, dict):
            raise ValueError("Reflection response must contain an analysis object.")
    elif reflection_type == "prompt":
        assessment = payload.get("assessment")
        if assessment not in {
            "policy_clear_but_java_violates",
            "policy_ambiguous",
            "java_faithfully_implements_policy",
        }:
            raise ValueError("Prompt Reviewer response must classify policy-code alignment.")
        review = payload.get("alignment_review")
        if not isinstance(review, list):
            raise ValueError("Prompt Reviewer response must contain alignment_review array.")
        normalized_review: list[dict[str, object]] = []
        for item in review:
            if not isinstance(item, dict):
                raise ValueError("Each alignment_review item must contain the four alignment fields.")
            normalized_item = dict(item)
            try:
                for key in (
                    "policy_requirement",
                    "observed_java_behavior",
                    "mismatch",
                    "required_generation_behavior",
                ):
                    if key not in item:
                        raise ValueError(key)
                    normalized_item[key] = _alignment_review_text(item[key], field=key)
            except ValueError as exc:
                raise ValueError("Each alignment_review item must contain the four alignment fields.") from exc
            normalized_review.append(normalized_item)
        corrections = payload.get("required_generation_behaviors")
        if not isinstance(corrections, list):
            raise ValueError("Prompt Reviewer response must contain required_generation_behaviors array.")
        normalized_payload = dict(payload)
        normalized_payload["alignment_review"] = normalized_review
        try:
            normalized_payload["required_generation_behaviors"] = [
                _alignment_review_text(item, field="required_generation_behaviors")
                for item in corrections
            ]
        except ValueError as exc:
            raise ValueError("Prompt Reviewer required_generation_behaviors items must be text corrections.") from exc
        return normalized_payload, json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True), ""
    else:
        raise ValueError(f"Unknown reflection type: {reflection_type}")
    for key in required:
        if not isinstance(analysis.get(key), list):
            raise ValueError(f"Reflection analysis.{key} must be an array.")
    revised = payload.get(revised_key)
    if not isinstance(revised, str) or not revised.strip():
        raise ValueError(f"Reflection response must contain non-empty {revised_key}.")
    summary = json.dumps({"analysis": analysis}, ensure_ascii=False, sort_keys=True)
    return payload, summary, revised.strip()


def _alignment_review_text(value: object, *, field: str) -> str:
    """Collapse bounded text/list/object variants into the canonical string field."""

    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(
            text
            for item in value
            if (text := _alignment_review_text(item, field=field))
        )
    if isinstance(value, dict):
        detail = next(
            (
                value.get(key)
                for key in (
                    "required_generation_behavior",
                    "requirement",
                    "behavior",
                    "correction",
                    "detail",
                    "summary",
                    "text",
                )
                if isinstance(value.get(key), str) and str(value.get(key)).strip()
            ),
            None,
        )
        if detail is None:
            raise ValueError(f"{field} object does not contain a supported text field")
        area = value.get("area")
        prefix = f"{str(area).strip()}: " if isinstance(area, str) and area.strip() else ""
        return prefix + str(detail).strip()
    raise ValueError(f"{field} must be a string, string array, or supported text object")


class ReflectionBackend(Protocol):
    """Transport abstraction for one non-generation LLM request."""

    def generate(self, prompt: str) -> str:
        """Return the raw backend response for a single attempt."""



class MockReflectionBackend:
    """Deterministic Reflection backend used by tests and mock searches."""

    def __init__(self, response: str | None = None) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.response is not None:
            return self.response
        if "Strategy Reflection stage" in prompt:
            return json.dumps({
                "diagnosis": {"primary_failure": "mock evaluation", "secondary_failures": [], "supporting_matches": [], "behaviors_to_preserve": ["deterministic behavior"]},
                "mutation_plan": {"remove_or_reduce": [], "add_or_strengthen": ["preserve the tested strategy"], "conditional_behaviors": ["When evidence is unavailable, preserve validated behavior."]},
                "revised_strategy_prompt": "Preserve deterministic behavior and address the observed strategic weakness with conditional rules.",
            })
        if "Prompt Reflection generation-prompt rewrite stage" in prompt:
            return json.dumps({
                "remove_rule_ids": [],
                "add_rules": [{
                    "category": "requirement_coverage",
                    "instruction": (
                        "Make every stated prerequisite reachable before its dependent behavior."
                    ),
                }],
            })
        if "Policy-Code Alignment Reviewer for Prompt Reflection" in prompt:
            return json.dumps({
                "assessment": "java_faithfully_implements_policy",
                "alignment_review": [],
                "required_generation_behaviors": [],
            })
        if "Policy-Code Alignment Reviewer" in prompt:
            return json.dumps({
                "assessment": "java_faithfully_implements_policy",
                "alignment_review": [],
                "required_generation_behaviors": [],
            })
        if "Code Generation Prompt Rewrite stage" in prompt:
            return json.dumps({
                "remove_rule_ids": [],
                "add_rules": [{
                    "category": "requirement_coverage",
                    "instruction": (
                        "Make every stated prerequisite reachable before its dependent behavior."
                    ),
                }],
            })
        if "MATCH_COMMENTATOR_OUTPUT=chunk" in prompt:
            source = prompt.split("MATCH_COMMENTATOR_OUTPUT=chunk", 1)[1]
            request = json.loads(source)
            tick_range = request.get("tick_range") or {"start": 0, "end": 0}
            return json.dumps({
                "tick_range": tick_range,
                "candidate_state": {"economy": "observed from supplied records", "production": "unknown", "army": "observed from supplied records", "positioning": "observed from supplied records"},
                "opponent_state": {"economy": "observed from supplied records", "production": "unknown", "army": "observed from supplied records", "pressure": "unknown"},
                "events": [], "turning_points": [], "candidate_strengths": [], "candidate_weaknesses": [], "possible_missed_opportunities": [], "state_at_chunk_end": "State recorded at the end of the supplied range.",
            })
        if "MATCH_COMMENTATOR_OUTPUT=final" in prompt:
            source = prompt.split("MATCH_COMMENTATOR_OUTPUT=final", 1)[1]
            request = json.loads(source)
            metadata = request.get("match_metadata") or {}
            coverage = request.get("trace_coverage") or {}
            candidate_side = metadata.get("candidate_side", "p0")
            return json.dumps({
                "match_id": metadata.get("match_id", ""), "candidate_side": candidate_side,
                "opponent": metadata.get("opponent_name", ""), "map": metadata.get("map_name", ""),
                "result": {"winner": request.get("final_result", {}).get("winner"), "candidate_result": request.get("final_result", {}).get("candidate_result", "draw"), "game_length": request.get("final_result", {}).get("game_length")},
                "match_summary": "Commentary unavailable beyond the observed structured state records.", "timeline": [], "turning_points": [], "candidate_strengths": [], "candidate_weaknesses": [], "opponent_behavior": [], "candidate_decision_errors": [], "missed_opportunities": [], "decisive_causes": [], "behaviors_to_preserve": [], "strategy_recommendations": [],
                "coverage": {"first_tick": coverage.get("first_tick"), "last_tick": coverage.get("last_tick"), "all_ticks_processed": True},
            })
        return "Preserve the validated constraints and apply only the evidence-backed revision."


class OpenAICompatibleReflectionBackend:
    """Single-attempt OpenAI-compatible transport.

    Retries belong to :class:`ReflectionStage` so each attempt has one timing
    and artifact record.
    """

    def __init__(self, base_url: str, model: str, *, timeout_sec: float = 120, operation: str | None = None, temperature: float = 0.2, max_output_tokens: int | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.operation = operation
        self.timeout_sec = timeout_sec
        self.temperature = temperature
        self.max_output_tokens = (
            DEFAULT_STRUCTURED_OUTPUT_TOKENS
            if max_output_tokens is None
            else max_output_tokens
        )

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate(self, prompt: str) -> str:
        prompt = truncate_prompt(prompt)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "stream": True,
        }
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        request = urllib.request.Request(
            self.chat_completions_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with llm_request_progress(
                stage=self.operation or "reflection",
                endpoint=self.chat_completions_url,
                model=self.model,
            ):
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    return read_chat_completion_content(response)
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")[:300]
            raise LLMServerError(
                f"llm server error: Reflection backend HTTP {exc.code}: {exc.reason}; "
                f"response_body_start={response_body!r}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMServerError(f"llm server error: Reflection backend request failed: {exc}") from exc
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Reflection backend returned invalid JSON: {exc}") from exc


def build_reflection_backend(
    name: str,
    *,
    base_url: str = "http://localhost:8080",
    model: str | None = None,
    operation: str | None = None,
    timeout_sec: float = 120,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> ReflectionBackend:
    if name == "mock":
        return MockReflectionBackend()
    if name in {"openai", "openai"}:
        if not model:
            raise ValueError("An explicit model path is required for the OpenAI-compatible backend.")
        return OpenAICompatibleReflectionBackend(base_url, model, operation=operation, timeout_sec=timeout_sec, temperature=temperature, max_output_tokens=max_output_tokens)
    raise ValueError(f"Unknown mutation backend: {name}")


class ReflectionStage:
    """Execute, validate, retry, and persist one Reflection stage."""

    def __init__(
        self,
        backend: ReflectionBackend,
        *,
        max_attempts: int = 3,
        logger: Any | None = None,
        model: str | None = None,
        backend_name: str | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.backend = backend
        self.max_attempts = max_attempts
        self.logger = logger
        self.model = model
        self.operation = getattr(backend, "operation", None)
        self.backend_name = backend_name or type(backend).__name__

    def run(
        self,
        *,
        reflection_type: str,
        candidate: Candidate,
        request: str,
        artifact_dir: Path | None = None,
        prompt_metadata: dict[str, object] | None = None,
    ) -> ReflectionResult:
        stage = "reflector"
        stage_dir = None if artifact_dir is None else _reflection_artifact_dir(artifact_dir, reflection_type)
        if artifact_dir is not None:
            assert stage_dir is not None
            _write_text(stage_dir / f"{stage}_request.txt", request)
            if prompt_metadata is not None:
                _write_json(stage_dir / f"{stage}_prompt_metadata.json", prompt_metadata)

        attempts: list[ReflectionAttempt] = []
        last_response = ""
        last_error: str | None = None
        for attempt_number in range(1, self.max_attempts + 1):
            started_at = utc_now()
            monotonic_started = time.monotonic()
            status = "success"
            error: str | None = None
            response = ""
            attempt_request = (
                request
                if last_error is None
                else _build_role_validation_retry_prompt(
                    request, last_response, last_error
                )
            )
            if artifact_dir is not None:
                assert stage_dir is not None
                _write_text(
                    stage_dir / f"{stage}_attempt_{attempt_number:03d}_request.txt",
                    attempt_request,
                )
            try:
                response = self.backend.generate(attempt_request)
                last_response = response
                parsed, analysis_summary, revised_prompt = parse_reflection_response(response, reflection_type)
                _validate_reflection_candidate_preconditions(
                    candidate,
                    reflection_type,
                    parsed,
                )
            except LLMServerError:
                raise
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                status = "error"
                error = str(exc) or type(exc).__name__
                last_error = error
            finished_at = utc_now()
            duration = max(0.0, time.monotonic() - monotonic_started)
            attempts.append(
                ReflectionAttempt(
                    attempt=attempt_number,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=duration,
                    status=status,
                    error=error
                )
            )
            if artifact_dir is not None:
                assert stage_dir is not None
                _write_text(
                    stage_dir / f"{stage}_attempt_{attempt_number:03d}_response_raw.txt",
                    response,
                )
                if response:
                    _write_text(stage_dir / f"{stage}_response_raw.txt", response)
            if self.logger is not None:
                self.logger.write(
                    stage=stage,
                    input_text=attempt_request,
                    response_text=response,
                    status=status,
                    backend=self.backend_name,
                    model=self.model or "",
                    candidate_id=candidate.id,
                    generation=candidate.generation,
                    module_name=reflection_type,
                    attempt=attempt_number,
                    error=error,
                    metadata={
                        "operation": self.operation,
                        "operation_type": "mutation",
                        "token_counts": None,
                        "prompt_metadata": prompt_metadata,
                    },
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=max(0.0, time.monotonic() - monotonic_started),
                )
            if status == "success":
                return ReflectionResult(
                    stage=stage,
                    reflection_type=reflection_type,
                    request=request,
                    raw_response=response,
                    reflection=response.strip(),
                    status="success",
                    attempts=tuple(attempts),
                    model=self.model,
                    backend=self.backend_name,
                    operation=self.operation,
                    parsed_response=parsed,
                    analysis_summary=analysis_summary,
                    revised_prompt=revised_prompt,
                    prompt_metadata=prompt_metadata,
                )
            time.sleep(0)

        if artifact_dir is not None:
            assert stage_dir is not None
            _write_text(stage_dir / f"{stage}_response_raw.txt", last_response)
        return ReflectionResult(
            stage=stage,
            reflection_type=reflection_type,
            request=request,
            raw_response=last_response,
            reflection="",
            status="failed",
            attempts=tuple(attempts),
            error=last_error or "Reflection stage failed.",
            model=self.model,
            backend=self.backend_name,
            operation=self.operation,
            prompt_metadata=prompt_metadata,
        )


def _build_role_validation_retry_prompt(
    original_request: str,
    previous_response: str,
    error: str,
) -> str:
    from .prompts import render_prompt

    return render_prompt("role_validation_retry", {
        "validation_error": error,
        "previous_response": previous_response,
        "original_request": original_request,
    })


def _validate_reflection_candidate_preconditions(
    candidate: Candidate,
    reflection_type: str,
    parsed: dict[str, object],
) -> None:
    """Reject role output that invents requirements for an absent policy gene."""

    normalized_type = reflection_type.removesuffix("_reflection")
    if normalized_type != "prompt":
        return
    if candidate.strategy_prompt.strip():
        return
    if (
        parsed.get("assessment") != "policy_ambiguous"
        or parsed.get("alignment_review")
        or parsed.get("required_generation_behaviors")
    ):
        raise ValueError(
            "Prompt Reflection requires a non-blank policy before it can propose "
            "generation-prompt corrections."
        )




def _timing_payload(attempts: tuple[ReflectionAttempt, ...]) -> dict[str, object]:
    if not attempts:
        return {"started_at": None, "finished_at": None, "duration_seconds": None, "attempts": []}
    return {
        "started_at": attempts[0].started_at,
        "finished_at": attempts[-1].finished_at,
        "duration_seconds": sum(attempt.duration_seconds for attempt in attempts),
        "attempts": [attempt.to_dict() for attempt in attempts],
    }


def _reflection_artifact_dir(root: Path | None, reflection_type: str) -> Path:
    assert root is not None
    mutation_type = reflection_type.removesuffix("_reflection")
    return root / "mutation" / f"{mutation_type}_reflection"


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
