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

from .candidate import Candidate, compact_mutation_record
from .config import ExperimentConfig
from .llm import LLMServerError
from .mutation import (
    REFLECTION_SCHEMA_VERSION,
    ReflectionContext,
    ReflectionAttempt,
    ReflectionBackend,
    ReflectionResult,
    ReflectionStage,
    build_code_reflection_prompt_bundle,
    build_balance_reflection_prompt_bundle,
    build_strategy_reflection_prompt_bundle,
    parse_json_object_response,
    _timing_payload,
    utc_now,
)
from .prompts import normalize_prompt


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
    operation: str | None = None
    token_counts: dict[str, int] | None = None

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
            "operation": self.operation,
            "token_counts": self.token_counts,
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
        self.operation = getattr(backend, "operation", None)
        self.backend_name = backend_name or type(backend).__name__

    def run(
        self,
        *,
        rewrite_type: str,
        candidate: Candidate,
        request: str,
        artifact_dir: Path | None = None,
        artifact_mutation_type: str | None = None,
        artifact_prefix: str = "",
    ) -> RewriteResult:
        stage = "rewriter"
        stage_dir = (
            None
            if artifact_dir is None
            else _rewrite_artifact_dir(
                artifact_dir,
                rewrite_type,
                mutation_type=artifact_mutation_type,
            )
        )
        if artifact_dir is not None:
            assert stage_dir is not None
            _write_text(stage_dir / f"{artifact_prefix}{stage}_request.txt", request)
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
                rewritten_prompt = _parse_rewritten_prompt(response, rewrite_type)
            except LLMServerError:
                raise
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
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
                assert stage_dir is not None
                _write_text(stage_dir / f"{artifact_prefix}{stage}_attempt_{attempt_number:03d}_response_raw.txt", response)
                if response:
                    _write_text(stage_dir / f"{artifact_prefix}{stage}_response_raw.txt", response)
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
                    metadata={"operation": self.operation, "operation_type": "mutation", "token_counts": None},
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=max(0.0, time.monotonic() - monotonic_started),
                )
            if status == "success":
                return RewriteResult(
                    stage=stage,
                    rewrite_type=rewrite_type,
                    request=request,
                    raw_response=response,
                    rewritten_prompt=rewritten_prompt,
                    status="success",
                    attempts=tuple(attempts),
                    model=self.model,
                    backend=self.backend_name,
                    operation=self.operation,
                )
            time.sleep(0)
        if artifact_dir is not None:
            assert stage_dir is not None
            _write_text(stage_dir / f"{artifact_prefix}{stage}_response_raw.txt", last_response)
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
            operation=self.operation,
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
        backend_name: str | None = None,
    ) -> None:
        if mutation_type not in {"strategy", "code"}:
            raise ValueError(f"Unknown mutation type: {mutation_type}")
        self.config = config
        self.mutation_type = mutation_type
        self.artifact_root = artifact_root
        self.reflection = ReflectionStage(
            reflection_backend,
            max_attempts=config.mutation_max_attempts,
            logger=logger,
            model=None if config.execution_mode == "mock" else config.llm_model,
            backend_name=backend_name or config.execution_mode,
        )
        self.rewrite = PromptRewriteStage(
            rewrite_backend,
            max_attempts=config.mutation_max_attempts,
            logger=logger,
            model=None if config.execution_mode == "mock" else config.llm_model,
            backend_name=backend_name or config.execution_mode,
        )

    def mutate(
        self,
        candidate: Candidate,
        context: ReflectionContext,
        *,
        artifact_dir: Path | None = None,
    ) -> Candidate:
        target_dir = artifact_dir or (self.artifact_root / candidate.id if self.artifact_root else None)
        original_strategy = candidate.strategy_prompt
        original_generation = candidate.generation_prompt
        from .reflection_context import coerce_structured_context

        context = coerce_structured_context(context, candidate)
        reflection_bundle = (
            build_strategy_reflection_prompt_bundle(candidate, context)
            if self.mutation_type == "strategy"
            else build_code_reflection_prompt_bundle(candidate, context)
        )
        reflection = self.reflection.run(
            reflection_type=self.mutation_type,
            candidate=candidate,
            request=reflection_bundle.text,
            artifact_dir=target_dir,
            prompt_metadata=reflection_bundle.metadata,
        )
        if not reflection.succeeded:
            return self._result_candidate(
                candidate,
                context=context,
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
        rewrite_type = "strategy_prompt_rewrite" if self.mutation_type == "strategy" else "generation_prompt_rewrite"
        rewrite = self.rewrite.run(
            rewrite_type=rewrite_type,
            candidate=candidate,
            request=request,
            artifact_dir=target_dir,
        )
        if not rewrite.succeeded:
            return self._result_candidate(
                candidate,
                context=context,
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
        result = self._result_candidate(
            candidate,
            context=context,
            reflection=reflection,
            rewrite=rewrite,
            strategy_prompt=rewritten if self.mutation_type == "strategy" else original_strategy,
            generation_prompt=rewritten if self.mutation_type == "code" else original_generation,
            applied=True,
            target_dir=target_dir,
            original_strategy=original_strategy,
            original_generation=original_generation,
        )
        if self.mutation_type == "strategy":
            assert result.generation_prompt == original_generation
        else:
            assert result.strategy_prompt == original_strategy
        return result

    def _result_candidate(self, *args: Any, **kwargs: Any) -> Candidate:
        """Share the established single-gene mutation artifact writer."""

        return BalanceReflectionMutation._result_candidate(self, *args, **kwargs)


class BalanceReflectionMutation:
    """Use aggregate outcome balance evidence to atomically revise both prompt genes."""

    mutation_type = "balance"

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        reflection_backend: ReflectionBackend,
        rewrite_backend: RewriteBackend,
        artifact_root: Path | None = None,
        logger: Any | None = None,
        backend_name: str | None = None,
    ) -> None:
        self.config = config
        self.artifact_root = artifact_root
        model = None if config.execution_mode == "mock" else config.llm_model
        name = backend_name or config.execution_mode
        self.reflection = ReflectionStage(
            reflection_backend,
            max_attempts=config.mutation_max_attempts,
            logger=logger,
            model=model,
            backend_name=name,
        )
        self.rewrite = PromptRewriteStage(
            rewrite_backend,
            max_attempts=config.mutation_max_attempts,
            logger=logger,
            model=model,
            backend_name=name,
        )

    def mutate(
        self,
        candidate: Candidate,
        context: ReflectionContext,
        *,
        artifact_dir: Path | None = None,
    ) -> Candidate:
        from .reflection_context import coerce_structured_context

        target_dir = artifact_dir or (self.artifact_root / candidate.id if self.artifact_root else None)
        context = coerce_structured_context(context, candidate)
        original_strategy = candidate.strategy_prompt
        original_generation = candidate.generation_prompt
        bundle = build_balance_reflection_prompt_bundle(candidate, context)
        reflection = self.reflection.run(
            reflection_type="balance",
            candidate=candidate,
            request=bundle.text,
            artifact_dir=target_dir,
            prompt_metadata=bundle.metadata,
        )
        if not reflection.succeeded:
            return self._result(
                candidate, context, reflection, None, None,
                original_strategy, original_generation, applied=False, target_dir=target_dir,
            )

        strategy_rewrite = self.rewrite.run(
            rewrite_type="balance_strategy_prompt_rewrite",
            candidate=candidate,
            request=build_balance_strategy_rewrite_prompt(candidate, reflection),
            artifact_dir=target_dir,
            artifact_mutation_type="balance",
            artifact_prefix="strategy_",
        )
        if not strategy_rewrite.succeeded:
            return self._result(
                candidate, context, reflection, strategy_rewrite, None,
                original_strategy, original_generation, applied=False, target_dir=target_dir,
            )

        code_rewrite = self.rewrite.run(
            rewrite_type="balance_generation_prompt_rewrite",
            candidate=candidate,
            request=build_balance_code_rewrite_prompt(candidate, reflection),
            artifact_dir=target_dir,
            artifact_mutation_type="balance",
            artifact_prefix="code_",
        )
        if not code_rewrite.succeeded:
            return self._result(
                candidate, context, reflection, strategy_rewrite, code_rewrite,
                original_strategy, original_generation, applied=False, target_dir=target_dir,
            )
        strategy_prompt = normalize_prompt(
            strategy_rewrite.rewritten_prompt,
            max_chars=self.config.max_prompt_chars,
            max_lines=self.config.max_prompt_lines,
        )
        generation_prompt = normalize_prompt(
            code_rewrite.rewritten_prompt,
            max_chars=self.config.max_prompt_chars,
            max_lines=self.config.max_prompt_lines,
        )
        return self._result(
            candidate, context, reflection, strategy_rewrite, code_rewrite,
            strategy_prompt, generation_prompt, applied=True, target_dir=target_dir,
            original_strategy=original_strategy, original_generation=original_generation,
        )

    def _result(
        self,
        candidate: Candidate,
        context: ReflectionContext,
        reflection: ReflectionResult,
        strategy_rewrite: RewriteResult | None,
        code_rewrite: RewriteResult | None,
        strategy_prompt: str,
        generation_prompt: str,
        *,
        applied: bool,
        target_dir: Path | None,
        original_strategy: str | None = None,
        original_generation: str | None = None,
    ) -> Candidate:
        original_strategy = candidate.strategy_prompt if original_strategy is None else original_strategy
        original_generation = candidate.generation_prompt if original_generation is None else original_generation
        rewrite_attempts = tuple(
            attempt
            for rewrite in (strategy_rewrite, code_rewrite)
            if rewrite is not None
            for attempt in rewrite.attempts
        )
        rewrite_error = next(
            (rewrite.error for rewrite in (strategy_rewrite, code_rewrite) if rewrite is not None and rewrite.error),
            None,
        )
        mutation_record = {
            "schema_version": "balance-reflection-v1",
            "reflection_schema_version": REFLECTION_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "feedback_candidate_id": context.candidate.candidate_id or candidate.id,
            "operation": "balance_mutation",
            "applied": applied,
            "type": "balance",
            "objectives": context.objectives.to_dict(),
            "evaluation_status": context.candidate.status,
            "evidence": {"outcome_table": _balance_outcome_table(context)},
            "prompt_metadata": reflection.prompt_metadata,
            "model": reflection.model,
            "reflection_operation": reflection.operation,
            "rewrite_operation": None if strategy_rewrite is None else strategy_rewrite.operation,
            "reflection_attempts": len(reflection.attempts),
            "rewrite_attempts": len(rewrite_attempts),
            "reflection_status": reflection.status,
            "rewrite_status": None if code_rewrite is None else code_rewrite.status,
            "reflection_error": reflection.error,
            "rewrite_error": rewrite_error,
            "original_strategy_prompt": original_strategy,
            "original_generation_prompt": original_generation,
            "reflection": reflection.to_dict(),
            "strategy_rewrite": None if strategy_rewrite is None else strategy_rewrite.to_dict(),
            "generation_rewrite": None if code_rewrite is None else code_rewrite.to_dict(),
        }
        timing = dict(candidate.timing)
        timing["reflector_llm"] = _timing_payload(reflection.attempts)
        timing["rewriter_llm"] = _timing_payload(rewrite_attempts)
        metadata = dict(candidate.metadata)
        history = [
            item for item in list(metadata.get("reflection_history") or ())
            if isinstance(item, dict) and item.get("reflection_type") == "balance"
        ][-1:]
        history.append({
            "reflection_type": "balance",
            "parent_candidate_id": mutation_record["feedback_candidate_id"],
            "analysis_summary": reflection.analysis_summary,
            "generation_index": candidate.generation,
        })
        mutation_record["reflection_history"] = history
        if target_dir is not None:
            mutation_dir = target_dir / "mutation" / "balance_reflection"
            _write_text(mutation_dir / "original_policy_prompt.txt", original_strategy)
            _write_text(mutation_dir / "original_code_generation_prompt.txt", original_generation)
            _write_json(mutation_dir / "reflection_context.json", mutation_record["evidence"])
            _write_json(mutation_dir / "metadata.json", _mutation_metadata_record(mutation_record))
            _write_json(target_dir / "timing.json", timing)
        metadata["mutation"] = (
            compact_mutation_record(mutation_record)
            if target_dir is not None and self.artifact_root is not None
            else mutation_record
        )
        metadata["reflection_history"] = history
        return replace(
            candidate,
            strategy_prompt=strategy_prompt,
            generation_prompt=generation_prompt,
            operator=("crossover+mutation" if candidate.operator == "crossover" else "mutation") if applied else candidate.operator,
            mutation_type="balance",
            timing=timing,
            metadata=metadata,
        )

    def _result_candidate(
        self,
        candidate: Candidate,
        *,
        context: ReflectionContext,
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
        feedback_candidate_id = context.candidate.candidate_id or candidate.id
        mutation_record = {
            "schema_version": REWRITE_SCHEMA_VERSION,
            "reflection_schema_version": REFLECTION_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "feedback_candidate_id": feedback_candidate_id,
            "operation": f"{self.mutation_type}_mutation",
            "applied": applied,
            "type": self.mutation_type,
            "objectives": context.objectives.to_dict(),
            "evaluation_status": context.candidate.status,
            "evidence": (
                (
                    {
                        "candidate_id": candidate.id,
                        "policy_prompt": candidate.strategy_prompt,
                        "java_parent_id": candidate.java_parent_id,
                        "reviewed_java_input": "inherited_java",
                        "reviewed_inherited_java_artifact": (
                            f"candidates/{candidate.id}/genotype/inherited_java.java"
                        ),
                        "structural_evidence": _structural_code_evidence(context),
                    }
                    if candidate.inherited_java
                    else {
                        "candidate_id": feedback_candidate_id,
                        "policy_prompt": context.candidate.strategy_prompt,
                        "reviewed_phenotype_artifact": (
                            f"candidates/{feedback_candidate_id}/phenotype/CandidateAgent.java"
                        ),
                        "structural_evidence": _structural_code_evidence(context),
                    }
                )
                if self.mutation_type == "code"
                else {
                    "candidate_id": feedback_candidate_id,
                    "policy_prompt": context.candidate.strategy_prompt,
                    "objectives": context.objectives.to_dict(),
                }
            ),
            "token_counts": {"reflection": None, "rewrite": None},
            "prompt_metadata": reflection.prompt_metadata,
            "model": reflection.model or (None if rewrite is None else rewrite.model),
            "reflection_operation": reflection.operation,
            "rewrite_operation": None if rewrite is None else rewrite.operation,
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
        history = list(candidate.metadata.get("reflection_history") or ())
        history = [item for item in history if isinstance(item, dict) and item.get("reflection_type") == self.mutation_type][-1:]
        history.append({
            "reflection_type": self.mutation_type,
            "parent_candidate_id": feedback_candidate_id,
            "analysis_summary": reflection.analysis_summary,
            "revised_prompt": reflection.revised_prompt,
            "generation_index": candidate.generation,
        })
        mutation_record["reflection_history"] = history[-1:]
        timing = dict(candidate.timing)
        timing["reflector_llm"] = _timing_payload(reflection.attempts)
        timing["rewriter_llm"] = (
            {"started_at": None, "finished_at": None, "duration_seconds": None, "attempts": []}
            if rewrite is None
            else _timing_payload(rewrite.attempts)
        )
        metadata = dict(candidate.metadata)
        if target_dir is not None:
            mutation_dir = target_dir / "mutation" / f"{self.mutation_type}_reflection"
            _write_text(mutation_dir / "original_policy_prompt.txt", original_strategy)
            _write_text(mutation_dir / "original_code_generation_prompt.txt", original_generation)
            _write_json(mutation_dir / "metadata.json", _mutation_metadata_record(mutation_record))
            _write_json(target_dir / "timing.json", timing)
        if target_dir is not None and self.artifact_root is not None:
            metadata["mutation"] = compact_mutation_record(mutation_record)
        else:
            # Tests/embedded callers without an artifact root still need the
            # complete record so a later artifact writer can persist it.
            metadata["mutation"] = mutation_record
        metadata["reflection_history"] = history[-1:]
        result = replace(
            candidate,
            strategy_prompt=strategy_prompt,
            generation_prompt=generation_prompt,
            operator=operator if applied else candidate.operator,
            mutation_type=self.mutation_type,
            timing=timing,
            metadata=metadata,
        )
        if self.mutation_type == "strategy":
            assert result.generation_prompt == original_generation
        else:
            assert result.strategy_prompt == original_strategy
        return result


def build_strategy_rewrite_prompt(candidate: Candidate, reflection: ReflectionResult, context: ReflectionContext) -> str:
    from .prompts import render_prompt

    return render_prompt("strategy_rewrite", {
        "strategy_prompt": candidate.strategy_prompt,
        "reflection": json.dumps({"analysis": reflection.parsed_response.get("analysis", {}) if reflection.parsed_response else {}, "proposed_revised_strategy_prompt": reflection.revised_prompt}, ensure_ascii=False),
        "game_summary": context.objectives.to_dict(),
    })


def build_code_rewrite_prompt(candidate: Candidate, reflection: ReflectionResult, context: ReflectionContext) -> str:
    from .prompts import load_prompt, render_prompt

    return render_prompt("code_rewrite", {
        "code_generation_prompt": candidate.generation_prompt,
        "alignment_review": json.dumps(reflection.parsed_response or {}, ensure_ascii=False),
        "action_api_guide": load_prompt("action_api_guide"),
    })


def build_balance_strategy_rewrite_prompt(candidate: Candidate, reflection: ReflectionResult) -> str:
    from .prompts import render_prompt

    return render_prompt("balance_strategy_rewrite", {
        "strategy_prompt": candidate.strategy_prompt,
        "balance_analysis": json.dumps(reflection.parsed_response or {}, ensure_ascii=False),
    })


def build_balance_code_rewrite_prompt(candidate: Candidate, reflection: ReflectionResult) -> str:
    from .prompts import load_prompt, render_prompt

    return render_prompt("balance_code_rewrite", {
        "code_generation_prompt": candidate.generation_prompt,
        "balance_analysis": json.dumps(reflection.parsed_response or {}, ensure_ascii=False),
        "action_api_guide": load_prompt("action_api_guide"),
    })


def _parse_rewritten_prompt(response: str, rewrite_type: str) -> str:
    if not isinstance(response, str) or not response.strip():
        raise ValueError("Rewrite response must contain a non-empty prompt.")
    if rewrite_type in {"generation_prompt_rewrite", "balance_generation_prompt_rewrite"}:
        payload = parse_json_object_response(response)
        if set(payload) != {"rewritten_prompt"}:
            raise ValueError(
                "Code Rewrite response must contain exactly the rewritten_prompt key."
            )
        rewritten = payload["rewritten_prompt"]
        if not isinstance(rewritten, str) or not rewritten.strip():
            raise ValueError("Code Rewrite rewritten_prompt must be a non-empty string.")
        response = rewritten
    lowered = response.lower().strip()
    if (
        "```" in lowered
        or "package ai.generated" in lowered
        or "public class candidateagent" in lowered
        or lowered.startswith("new_strategy_prompt:")
        or lowered.startswith("new_generation_prompt:")
    ):
        raise ValueError("Rewrite response must contain only the rewritten prompt.")
    return response.strip()


def _mutation_metadata_record(record: dict[str, Any]) -> dict[str, Any]:
    """Keep request/response bodies in their text artifacts, not metadata JSON."""

    payload = dict(record)
    for key in ("reflection", "rewrite", "strategy_rewrite", "generation_rewrite"):
        stage = payload.get(key)
        if isinstance(stage, dict):
            payload[key] = {
                name: value
                for name, value in stage.items()
                if name not in {"request", "raw_response"}
            }
    return payload


def _structural_code_evidence(context: ReflectionContext) -> dict[str, Any]:
    diagnostics = context.code_diagnostics.to_dict()
    return {
        key: diagnostics.get(key)
        for key in (
            "generation_failure",
            "validation_failure",
            "compile_success",
            "compile_errors",
            "compile_warnings",
            "missing_functions",
            "invalid_functions",
        )
        if diagnostics.get(key) not in (None, (), [], {}, "")
    }


def _rewrite_artifact_dir(root: Path | None, rewrite_type: str, *, mutation_type: str | None = None) -> Path:
    assert root is not None
    mutation_type = mutation_type or ("code" if rewrite_type == "generation_prompt_rewrite" else "strategy")
    return root / "mutation" / f"{mutation_type}_reflection"


def _balance_outcome_table(context: ReflectionContext) -> list[dict[str, object]]:
    table: list[dict[str, object]] = []
    for opponent in context.opponents:
        for map_result in opponent.map_results:
            table.append({
                "opponent": opponent.opponent_id,
                "map": map_result.map_name,
                "p0": {key: int(map_result.p0_result.get(key) or 0) for key in ("wins", "losses", "draws", "games")},
                "p1": {key: int(map_result.p1_result.get(key) or 0) for key in ("wins", "losses", "draws", "games")},
            })
    return table


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
