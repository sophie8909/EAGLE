"""LLM-backed Reflection stages for EAGLE mutation.

Prompt rewriting is intentionally owned by the next migration stage. This
module currently provides typed evidence, a transport abstraction, retry
handling, timing, and durable Reflection results for both mutation types.
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


REFLECTION_SCHEMA_VERSION = "phase2a-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MutationContext:
    """Evidence available to a component-owned mutation stage."""

    generation: int
    index: int
    game_performance: float | None = None
    player_resource: float | None = None
    enemy_resource: float | None = None
    resource_breakdown: dict[str, object] | None = None
    performance_breakdown: dict[str, object] | None = None
    temporal_summary: dict[str, object] | None = None
    match_summary: dict[str, object] | None = None
    per_match_results: tuple[dict[str, object], ...] = ()
    wins: int | None = None
    draws: int | None = None
    losses: int | None = None
    final_player_resources: dict[str, object] | None = None
    final_enemy_resources: dict[str, object] | None = None
    final_resource_difference: object | None = None
    unit_material_statistics: dict[str, object] | None = None
    survival_statistics: dict[str, object] | None = None
    round_state_summary: dict[str, object] | None = None
    behavior_summary: dict[str, object] | None = None
    opponent: str = "ai.abstraction.LightRush"
    latest_child_java: str = ""
    raw_generation_response: str = ""
    validation_result: dict[str, object] | None = None
    compilation_result: dict[str, object] | None = None
    integration_result: dict[str, object] | None = None
    runtime_result: dict[str, object] | None = None
    completed_match_count: int | None = None
    function_capability_score: float | None = None
    strategy_alignment_score: float | None = None
    compilation_score: float | None = None
    compiler_errors: tuple[str, ...] = ()
    compiler_warnings: tuple[str, ...] = ()
    strategy_region_score: float | None = None
    strategy_region_validation: dict[str, object] | None = None
    static_quality_score: float | None = None
    static_metrics: dict[str, object] | None = None
    compile_success: bool | None = None
    validation_success: bool | None = None
    runtime_success: bool | None = None
    error_category: str = ""
    error_message: str = ""
    target_module: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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
        }


class ReflectionBackend(Protocol):
    """Transport abstraction for one non-generation LLM request."""

    def generate(self, prompt: str) -> str:
        """Return the raw backend response for a single attempt."""


# Compatibility for callers that supplied a simple ``generate(prompt)`` fake.
MutationBackend = ReflectionBackend


class MockReflectionBackend:
    """Deterministic Reflection backend used by tests and mock searches."""

    def __init__(self, response: str | None = None) -> None:
        self.response = response or (
            "Reflection: identify the strongest observed behavior, the most "
            "important failure, and one concrete requirement for the next prompt."
        )
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class OpenAICompatibleReflectionBackend:
    """Single-attempt OpenAI-compatible transport.

    Retries belong to :class:`ReflectionStage` so each attempt has one timing
    and artifact record.
    """

    def __init__(self, base_url: str, model: str, *, timeout_sec: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            self.chat_completions_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                body = json.loads(response.read().decode("utf-8"))
            return str(body["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(
                f"Reflection backend HTTP {exc.code}: {exc.reason}; "
                f"response_body_start={response_body!r}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Reflection backend request failed: {exc}") from exc
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Reflection backend returned invalid JSON: {exc}") from exc


def build_reflection_backend(
    name: str,
    *,
    base_url: str = "http://localhost:8080",
    model: str = "local-model",
) -> ReflectionBackend:
    if name == "mock":
        return MockReflectionBackend()
    if name in {"openai", "llama_cpp"}:
        return OpenAICompatibleReflectionBackend(base_url, model)
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
        self.backend_name = backend_name or type(backend).__name__

    def run(
        self,
        *,
        stage: str,
        reflection_type: str,
        candidate: Candidate,
        request: str,
        artifact_dir: Path | None = None,
    ) -> ReflectionResult:
        if artifact_dir is not None:
            _write_text(artifact_dir / "mutation" / f"{stage}_request.txt", request)

        attempts: list[ReflectionAttempt] = []
        last_response = ""
        last_error: str | None = None
        for attempt_number in range(1, self.max_attempts + 1):
            started_at = utc_now()
            monotonic_started = time.monotonic()
            status = "success"
            error: str | None = None
            response = ""
            try:
                response = self.backend.generate(request)
                last_response = response
                _validate_reflection(response)
            except Exception as exc:  # noqa: BLE001 - persisted as stage failure
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
                    error=error,
                )
            )
            if artifact_dir is not None:
                _write_text(
                    artifact_dir / "mutation" / f"{stage}_attempt_{attempt_number:03d}_response_raw.txt",
                    response,
                )
                if response:
                    _write_text(artifact_dir / "mutation" / f"{stage}_response_raw.txt", response)
            if self.logger is not None:
                self.logger.write(
                    stage=stage,
                    input_text=request,
                    response_text=response,
                    status=status,
                    backend=self.backend_name,
                    model=self.model or "",
                    candidate_id=candidate.id,
                    generation=candidate.generation,
                    module_name=reflection_type,
                    attempt=attempt_number,
                    error=error,
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
                )
            time.sleep(0)

        if artifact_dir is not None:
            _write_text(artifact_dir / "mutation" / f"{stage}_response_raw.txt", last_response)
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
        )


class Mutation:
    """Reflection-only mutation facade used during Phase 2A."""

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        method: str = "strategy_reflection",
        backend: ReflectionBackend | None = None,
        artifact_root: Path | None = None,
        logger: Any | None = None,
    ) -> None:
        if method not in {"strategy_reflection", "code_generation_reflection"}:
            raise ValueError(f"Unknown mutation method: {method}")
        self.config = config
        self.method = method
        self.backend = backend or build_reflection_backend(
            config.generation_backend,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
        self.artifact_root = artifact_root
        self.stage = ReflectionStage(
            self.backend,
            max_attempts=config.mutation_max_attempts,
            logger=logger,
            model=None if config.generation_backend == "mock" else config.llm_model,
            backend_name=config.generation_backend,
        )

    @property
    def mutation_type(self) -> str:
        return "strategy" if self.method == "strategy_reflection" else "code"

    def reflect(
        self,
        candidate: Candidate,
        context: MutationContext,
        *,
        artifact_dir: Path | None = None,
    ) -> ReflectionResult:
        stage = self.method
        reflection_type = "strategy_reflection" if self.mutation_type == "strategy" else "code_reflection"
        request = (
            build_strategy_reflection_prompt(candidate, context)
            if self.mutation_type == "strategy"
            else build_code_reflection_prompt(candidate, context)
        )
        target_dir = artifact_dir or (self.artifact_root / candidate.id if self.artifact_root else None)
        return self.stage.run(
            stage=stage,
            reflection_type=reflection_type,
            candidate=candidate,
            request=request,
            artifact_dir=target_dir,
        )

    def mutate(
        self,
        candidate: Candidate,
        context: MutationContext,
        *,
        artifact_dir: Path | None = None,
    ) -> Candidate:
        """Run Reflection while deliberately preserving the candidate genotype."""

        result = self.reflect(candidate, context, artifact_dir=artifact_dir)
        record = {
            "schema_version": REFLECTION_SCHEMA_VERSION,
            "applied": False,
            "type": self.mutation_type,
            "stage": "reflection",
            "reflection_model": result.model,
            "reflection_attempts": len(result.attempts),
            "reflection_status": result.status,
            "reflection_error": result.error,
            "reflection": result.to_dict(),
        }
        timing = dict(candidate.timing)
        timing["reflection_llm"] = _timing_payload(result.attempts)
        metadata = dict(candidate.metadata)
        metadata["mutation"] = record
        # The existing child identity already belongs to this offspring. A
        # Reflection-only stage must not create a second lineage node.
        return replace(candidate, mutation_type=self.mutation_type, timing=timing, metadata=metadata)


def build_strategy_reflection_prompt(candidate: Candidate, context: MutationContext) -> str:
    parent_java = candidate.generated_java or candidate.previous_code
    return f"""EAGLE Strategy Reflection stage.

Analyze the complete strategy using the evidence below. Return reflection text only.
Do not rewrite either prompt. Do not generate Java, a patch, a diff, or a code block.

Current strategy_prompt:
{candidate.strategy_prompt}

Parent generated_java:
{parent_java}

Opponent identity: {context.opponent}
Complete 10-match summary: {context.match_summary or {}}
Per-match results: {list(context.per_match_results)}
Wins: {context.wins}; draws: {context.draws}; losses: {context.losses}
Game performance: {context.game_performance}
Final player resources: {context.final_player_resources or {}}
Final enemy resources: {context.final_enemy_resources or {}}
Final resource difference: {context.final_resource_difference}
Resource evidence: {context.resource_breakdown or {}}
Unit material statistics: {context.unit_material_statistics or {}}
Survival statistics: {context.survival_statistics or {}}
Round-state summary: {context.round_state_summary or {}}
Temporal summary: {context.temporal_summary or {}}
Behavior summary: {context.behavior_summary or {}}

Discuss effective and failed strategic behavior, implementation alignment, and concrete
requirements for a later Strategy Prompt Rewrite. The output must remain reflection only."""


def build_code_reflection_prompt(candidate: Candidate, context: MutationContext) -> str:
    parent_java = candidate.generated_java or candidate.previous_code
    latest_java = context.latest_child_java or candidate.generated_java
    return f"""EAGLE Code Reflection stage.

Analyze the complete-file generation outcome using the evidence below. Return reflection
text only. Do not rewrite either prompt and do not generate replacement Java, a patch, a
diff, JSON, or a code block.

strategy_prompt:
{candidate.strategy_prompt}

current generation_prompt:
{candidate.generation_prompt}

parent generated_java:
{parent_java}

latest generated child Java, if available:
{latest_java}

raw generation response:
{context.raw_generation_response}

source validation result: {context.validation_result or {}}
compilation result: {context.compilation_result or {}}
compiler errors: {list(context.compiler_errors)}
compiler warnings: {list(context.compiler_warnings)}
MicroRTS integration result: {context.integration_result or {}}
runtime result: {context.runtime_result or {}}
completed-match count: {context.completed_match_count}
function capability score: {context.function_capability_score}
strategy alignment score: {context.strategy_alignment_score}
failure stage: {context.error_category or context.error_message}
failure category: {context.error_category}
failure reason: {context.error_message}

Analyze complete-file validity, API/constructor compatibility, diagnostics, runtime or
match behavior, missing capabilities, strategy alignment, and constraints for a later
Generation Prompt Rewrite. Keep the output as reflection only."""


def _validate_reflection(response: str) -> None:
    if not isinstance(response, str) or not response.strip():
        raise ValueError("Reflection response must contain non-empty reflection text.")
    lowered = response.lower()
    if "```java" in lowered or "package ai.generated" in lowered or "public class candidateagent" in lowered:
        raise ValueError("Reflection response must not contain generated Java.")


def _timing_payload(attempts: tuple[ReflectionAttempt, ...]) -> dict[str, object]:
    if not attempts:
        return {"started_at": None, "finished_at": None, "duration_seconds": None, "attempts": []}
    return {
        "started_at": attempts[0].started_at,
        "finished_at": attempts[-1].finished_at,
        "duration_seconds": sum(attempt.duration_seconds for attempt in attempts),
        "attempts": [attempt.to_dict() for attempt in attempts],
    }


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
