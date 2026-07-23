"""Prompt Rewrite stages for the EAGLE mutation pipeline.

This module deliberately stops after producing a revised genotype component.
Final Java generation remains a separate Phase 2C operation.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from .candidate import Candidate
from .config import ExperimentConfig
from .mutation import (
    REFLECTION_SCHEMA_VERSION,
    Mutation,
    MutationContext,
    ReflectionAttempt,
    ReflectionBackend,
    ReflectionResult,
    _timing_payload,
    utc_now,
)
from .offspring import normalize_prompt


REWRITE_SCHEMA_VERSION = "phase2b-v1"


class RewriteBackend(Protocol):
    """Transport abstraction for one prompt-only Rewrite request."""

    def generate(self, prompt: str) -> str:
        """Return the raw response for one Rewrite attempt."""


@dataclass(frozen=True)
class RewriteResult:
    stage: str
    rewrite_type: str
    request: str
    raw_response: str
    rewritten_prompt: str
    status: str
    attempts: tuple[ReflectionAttempt, ...] = ()
    error: str | None = None
    model: str | None = None
    backend: str | None = None
    llm_profile: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REWRITE_SCHEMA_VERSION,
            "stage": self.stage,
            "rewrite_type": self.rewrite_type,
            "request": self.request,
            "raw_response": self.raw_response,
            "rewritten_prompt": self.rewritten_prompt,
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "error": self.error,
            "model": self.model,
            "backend": self.backend,
            "llm_profile": self.llm_profile,
        }


class PromptRewriteStage:
    """Execute, validate, retry, and persist one Rewrite stage."""

    def __init__(
        self,
        backend: RewriteBackend,
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
        self.llm_profile = getattr(backend, "llm_profile", None)
        self.backend_name = backend_name or type(backend).__name__

    def run(
        self,
        *,
        stage: str,
        rewrite_type: str,
        candidate: Candidate,
        request: str,
        artifact_dir: Path | None = None,
    ) -> RewriteResult:
        if artifact_dir is not None:
            _write_text(artifact_dir / "mutation" / f"{stage}_request.txt", request)
            _write_text(artifact_dir / "mutation" / "rewrite_request.txt", request)
        attempts: list[ReflectionAttempt] = []
        last_response = ""
        last_error: str | None = None
        for attempt_number in range(1, self.max_attempts + 1):
            started_at = utc_now()
            monotonic_started = time.monotonic()
            response = ""
            error: str | None = None
            status = "success"
            try:
                response = self.backend.generate(request)
                last_response = response
                _validate_rewritten_prompt(response)
            except Exception as exc:  # noqa: BLE001 - retained in stage evidence
                status = "error"
                error = str(exc) or type(exc).__name__
                last_error = error
            finished_at = utc_now()
            attempts.append(
                ReflectionAttempt(
                    attempt=attempt_number,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=max(0.0, time.monotonic() - monotonic_started),
                    status=status,
                    error=error
                )
            )
            if artifact_dir is not None:
                _write_text(artifact_dir / "mutation" / f"{stage}_attempt_{attempt_number:03d}_response_raw.txt", response)
                if response:
                    _write_text(artifact_dir / "mutation" / f"{stage}_response_raw.txt", response)
                    _write_text(artifact_dir / "mutation" / "rewrite_response_raw.txt", response)
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
                    module_name=rewrite_type,
                    attempt=attempt_number,
                    error=error,
                    metadata={"llm_profile": self.llm_profile},
                )
            if status == "success":
                return RewriteResult(
                    stage=stage,
                    rewrite_type=rewrite_type,
                    request=request,
                    raw_response=response,
                    rewritten_prompt=response.strip(),
                    status="success",
                    attempts=tuple(attempts),
                    model=self.model,
                    backend=self.backend_name,
                    llm_profile=self.llm_profile,
                )
            time.sleep(0)
        if artifact_dir is not None:
            _write_text(artifact_dir / "mutation" / f"{stage}_response_raw.txt", last_response)
            _write_text(artifact_dir / "mutation" / "rewrite_response_raw.txt", last_response)
        return RewriteResult(
            stage=stage,
            rewrite_type=rewrite_type,
            request=request,
            raw_response=last_response,
            rewritten_prompt="",
            status="failed",
            attempts=tuple(attempts),
            error=last_error or "Rewrite stage failed.",
            model=self.model,
            backend=self.backend_name,
            llm_profile=self.llm_profile,
        )


class PromptRewriteMutation:
    """Reflection followed by one component-owned prompt Rewrite."""

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        mutation_type: str,
        reflection_backend: ReflectionBackend,
        rewrite_backend: RewriteBackend,
        artifact_root: Path | None = None,
        logger: Any | None = None,
        reflection_model: str | None = None,
        rewrite_model: str | None = None,
        backend_name: str | None = None,
    ) -> None:
        if mutation_type not in {"strategy", "code"}:
            raise ValueError(f"Unknown mutation type: {mutation_type}")
        self.config = config
        self.mutation_type = mutation_type
        self.artifact_root = artifact_root
        self.reflection = Mutation(
            config,
            method="strategy_reflection" if mutation_type == "strategy" else "code_generation_reflection",
            backend=reflection_backend,
            artifact_root=artifact_root,
            logger=logger,
            model=reflection_model,
            backend_name=backend_name,
        )
        self.rewrite = PromptRewriteStage(
            rewrite_backend,
            max_attempts=config.mutation_max_attempts,
            logger=logger,
            model=rewrite_model if rewrite_model is not None else (None if config.generation_backend == "mock" else config.llm_model),
            backend_name=backend_name or config.generation_backend,
        )

    def mutate(
        self,
        candidate: Candidate,
        context: MutationContext,
        *,
        artifact_dir: Path | None = None,
    ) -> Candidate:
        target_dir = artifact_dir or (self.artifact_root / candidate.id if self.artifact_root else None)
        original_strategy = candidate.strategy_prompt
        original_generation = candidate.generation_prompt
        reflection = self.reflection.reflect(candidate, context, artifact_dir=target_dir)
        if not reflection.succeeded:
            return self._result_candidate(
                candidate,
                reflection=reflection,
                rewrite=None,
                strategy_prompt=original_strategy,
                generation_prompt=original_generation,
                applied=False,
                target_dir=target_dir,
                original_strategy=original_strategy,
                original_generation=original_generation,
            )

        request = (
            build_strategy_rewrite_prompt(candidate, reflection, context)
            if self.mutation_type == "strategy"
            else build_code_rewrite_prompt(candidate, reflection, context)
        )
        rewrite_stage = "strategy_rewrite" if self.mutation_type == "strategy" else "generation_prompt_rewrite"
        rewrite_type = "strategy_prompt_rewrite" if self.mutation_type == "strategy" else "generation_prompt_rewrite"
        rewrite = self.rewrite.run(
            stage=rewrite_stage,
            rewrite_type=rewrite_type,
            candidate=candidate,
            request=request,
            artifact_dir=target_dir,
        )
        if not rewrite.succeeded:
            return self._result_candidate(
                candidate,
                reflection=reflection,
                rewrite=rewrite,
                strategy_prompt=original_strategy,
                generation_prompt=original_generation,
                applied=False,
                target_dir=target_dir,
                original_strategy=original_strategy,
                original_generation=original_generation,
            )
        rewritten = normalize_prompt(
            rewrite.rewritten_prompt,
            max_chars=self.config.max_prompt_chars,
            max_lines=self.config.max_prompt_lines,
        )
        return self._result_candidate(
            candidate,
            reflection=reflection,
            rewrite=rewrite,
            strategy_prompt=rewritten if self.mutation_type == "strategy" else original_strategy,
            generation_prompt=rewritten if self.mutation_type == "code" else original_generation,
            applied=True,
            target_dir=target_dir,
            original_strategy=original_strategy,
            original_generation=original_generation,
        )

    def _result_candidate(
        self,
        candidate: Candidate,
        *,
        reflection: ReflectionResult,
        rewrite: RewriteResult | None,
        strategy_prompt: str,
        generation_prompt: str,
        applied: bool,
        target_dir: Path | None,
        original_strategy: str,
        original_generation: str,
    ) -> Candidate:
        operator = "crossover+mutation" if candidate.operator == "crossover" else "mutation"
        mutation_record = {
            "schema_version": REWRITE_SCHEMA_VERSION,
            "reflection_schema_version": REFLECTION_SCHEMA_VERSION,
            "applied": applied,
            "type": self.mutation_type,
            "reflection_model": reflection.model,
            "reflection_profile": reflection.llm_profile,
            "rewrite_model": None if rewrite is None else rewrite.model,
            "rewrite_profile": None if rewrite is None else rewrite.llm_profile,
            "reflection_attempts": len(reflection.attempts),
            "rewrite_attempts": 0 if rewrite is None else len(rewrite.attempts),
            "reflection_status": reflection.status,
            "rewrite_status": None if rewrite is None else rewrite.status,
            "reflection_error": reflection.error,
            "rewrite_error": None if rewrite is None else rewrite.error,
            "original_strategy_prompt": original_strategy,
            "original_generation_prompt": original_generation,
            "reflection": reflection.to_dict(),
            "rewrite": None if rewrite is None else rewrite.to_dict(),
        }
        timing = dict(candidate.timing)
        timing["reflection_llm"] = _timing_payload(reflection.attempts)
        timing["rewrite_llm"] = (
            {"started_at": None, "finished_at": None, "duration_seconds": None, "attempts": []}
            if rewrite is None
            else _timing_payload(rewrite.attempts)
        )
        metadata = dict(candidate.metadata)
        metadata["mutation"] = mutation_record
        if target_dir is not None:
            _write_text(target_dir / "mutation" / "original_strategy_prompt.txt", original_strategy)
            _write_text(target_dir / "mutation" / "original_generation_prompt.txt", original_generation)
            _write_json(target_dir / "mutation" / "metadata.json", mutation_record)
            _write_json(target_dir / "timing.json", timing)
        return replace(
            candidate,
            strategy_prompt=strategy_prompt,
            generation_prompt=generation_prompt,
            operator=operator if applied else candidate.operator,
            mutation_type=self.mutation_type,
            timing=timing,
            metadata=metadata,
        )


def build_strategy_rewrite_prompt(candidate: Candidate, reflection: ReflectionResult, context: MutationContext) -> str:
    from .prompts import render_prompt

    return render_prompt("strategy_rewrite", {
        "strategy_prompt": candidate.strategy_prompt,
        "reflection": reflection.reflection,
        "parent_java": candidate.generated_java or candidate.previous_code,
        "game_summary": context.match_summary or context.performance_breakdown or {},
    })


def build_code_rewrite_prompt(candidate: Candidate, reflection: ReflectionResult, context: MutationContext) -> str:
    from .prompts import render_prompt

    return render_prompt("code_rewrite", {
        "generation_prompt": candidate.generation_prompt,
        "reflection": reflection.reflection,
        "strategy_prompt": candidate.strategy_prompt,
        "parent_java": candidate.generated_java or candidate.previous_code,
        "code_quality_summary": context.compilation_result or context.static_metrics or {},
    })


def _validate_rewritten_prompt(response: str) -> None:
    if not isinstance(response, str) or not response.strip():
        raise ValueError("Rewrite response must contain a non-empty prompt.")
    lowered = response.lower().strip()
    if (
        "```" in lowered
        or "package ai.generated" in lowered
        or "public class candidateagent" in lowered
        or lowered.startswith("{")
        or lowered.startswith("new_strategy_prompt:")
        or lowered.startswith("new_generation_prompt:")
    ):
        raise ValueError("Rewrite response must contain only the rewritten prompt.")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
