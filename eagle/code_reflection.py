"""Diagnosis-guided direct Java mutation for the Code Reflection operator."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from generation.agent_template import JavaTemplatePaths, load_java_template
from generation.java_agent_generator import extract_code_from_output, normalize_java_agent_source

from .candidate import Candidate, compact_mutation_record
from .config import ExperimentConfig
from .llm import LLMServerError
from .mutation import (
    ReflectionAttempt,
    ReflectionContext,
    ReflectionResult,
    ReflectionStage,
    _timing_payload,
    utc_now,
)
from .prompts import load_prompt, render_prompt
from .reflection_context import coerce_structured_context


CODE_REFLECTION_SCHEMA_VERSION = "eagle-code-reflection-v2"


class CodeReflectionMutation:
    """Diagnose one parent source, then revise it from that conclusion."""

    mutation_type = "code"

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        backend: Any,
        reflection_backend: Any,
        artifact_root: Path | None = None,
        logger: Any | None = None,
        backend_name: str | None = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.artifact_root = artifact_root
        self.reflector = ReflectionStage(
            reflection_backend,
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
        context = coerce_structured_context(context, candidate)
        target_dir = artifact_dir or (
            self.artifact_root / candidate.id if self.artifact_root else None
        )
        parent_java = candidate.inherited_java or context.candidate.generated_code
        feedback_candidate_id = context.candidate.candidate_id or candidate.id
        reflection_request = (
            self._reflection_request(candidate, parent_java)
            if parent_java.strip()
            else ""
        )
        if reflection_request:
            reflection = self.reflector.run(
                reflection_type="code",
                candidate=candidate,
                request=reflection_request,
                artifact_dir=target_dir,
            )
        else:
            reflection = ReflectionResult(
                stage="reflector",
                reflection_type="code",
                request="",
                raw_response="",
                reflection="",
                status="failed",
                error="Code Reflection requires a non-empty selected parent Java source.",
            )

        reflection_conclusion = reflection.parsed_response or {}
        base_request = (
            self._revision_request(candidate, parent_java, reflection_conclusion)
            if reflection.succeeded
            else ""
        )
        revision_attempts: list[ReflectionAttempt] = []
        revision_response = ""
        reflected_java = ""
        last_revision_error: str | None = None

        for attempt_number in range(1, self.config.mutation_max_attempts + 1):
            if not base_request:
                break
            attempt_request = (
                base_request
                if last_revision_error is None
                else render_prompt(
                    "code_revision_retry",
                    {
                        "original_request": base_request,
                        "previous_response": revision_response,
                        "validation_error": last_revision_error,
                    },
                )
            )
            if hasattr(self.backend, "prepare_request"):
                attempt_request = self.backend.prepare_request(attempt_request)
            if hasattr(self.backend, "set_generation_attempt_context"):
                self.backend.set_generation_attempt_context(
                    attempt_number,
                    f"{candidate.id}:code_revision:{attempt_number:03d}",
                )
            if hasattr(self.backend, "set_generation_request_kind"):
                self.backend.set_generation_request_kind("code_reflection")
            started_at = utc_now()
            started = time.monotonic()
            status = "success"
            error: str | None = None
            try:
                revision_response = self.backend.generate_from_request(
                    candidate,
                    "CandidateAgent",
                    attempt_request,
                )
                reflected_java = normalize_java_agent_source(
                    extract_code_from_output(revision_response)
                )
            except LLMServerError:
                raise
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                status = "error"
                error = str(exc) or type(exc).__name__
                last_revision_error = error
            finished_at = utc_now()
            revision_attempts.append(
                ReflectionAttempt(
                    attempt=attempt_number,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=max(0.0, time.monotonic() - started),
                    status=status,
                    error=error,
                )
            )
            self._write_revision_attempt(
                target_dir,
                attempt_number=attempt_number,
                request=attempt_request,
                response=revision_response,
            )
            if status == "success":
                break
            time.sleep(0)

        succeeded = bool(reflection.succeeded and reflected_java)
        # A failed diagnosis or revision preserves and evaluates the selected parent Java;
        # it never falls through to an unrelated fresh Generator decode.
        direct_java = reflected_java or parent_java
        revision = {
            "stage": "code_revision",
            "request": base_request,
            "raw_response": revision_response,
            "status": (
                "success"
                if succeeded
                else "failed" if reflection.succeeded else "not_run"
            ),
            "attempts": [attempt.to_dict() for attempt in revision_attempts],
            "error": None if succeeded else last_revision_error,
            "model": getattr(self.backend, "model", None),
            "operation": getattr(self.backend, "operation", None),
        }
        mutation_record = {
            "schema_version": CODE_REFLECTION_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "feedback_candidate_id": feedback_candidate_id,
            "operation": "code_reflection_mutation",
            "type": "code",
            "applied": succeeded,
            "reflection_status": reflection.status,
            "reflection_error": reflection.error,
            "reflection_attempts": len(reflection.attempts),
            "revision_status": revision["status"],
            "revision_error": revision["error"],
            "revision_attempts": len(revision_attempts),
            "attempts": [attempt.to_dict() for attempt in revision_attempts],
            "rewrite_attempts": 0,
            "model": reflection.model or getattr(self.backend, "model", None),
            "reflection_operation": reflection.operation,
            "revision_operation": getattr(self.backend, "operation", None),
            "original_strategy_prompt": candidate.strategy_prompt,
            "original_generation_prompt": candidate.generation_prompt,
            "parent_java_sha256": _sha256(parent_java),
            "reflected_java_sha256": _sha256(direct_java),
            "java_changed": bool(succeeded and direct_java != parent_java),
            "evidence": {
                "source_candidate_id": feedback_candidate_id,
                "source_java": (
                    "inherited_java" if candidate.inherited_java else "parent_phenotype"
                ),
                "excluded_evidence": [
                    "match_results",
                    "match_traces",
                    "fitness_objectives",
                    "generation_prompt",
                ],
            },
            "reflection": reflection.to_dict(),
            "reflection_conclusion": reflection_conclusion,
            "revision": revision,
        }
        timing = dict(candidate.timing)
        timing["code_reflector_llm"] = _timing_payload(reflection.attempts)
        timing["code_revision_llm"] = _timing_payload(tuple(revision_attempts))
        history = [{
            "reflection_type": "code",
            "parent_candidate_id": feedback_candidate_id,
            "analysis_summary": reflection.analysis_summary,
            "generation_index": candidate.generation,
        }]
        metadata = dict(candidate.metadata)
        metadata["mutation"] = (
            compact_mutation_record(mutation_record)
            if target_dir is not None and self.artifact_root is not None
            else mutation_record
        )
        metadata["reflection_history"] = history
        self._write_result(
            target_dir,
            request=base_request,
            response=revision_response,
            parent_java=parent_java,
            reflected_java=direct_java,
            reflection=reflection,
            reflection_conclusion=reflection_conclusion,
            revision=revision,
            metadata=mutation_record,
        )
        return replace(
            candidate,
            generated_java=direct_java,
            operator=(
                "crossover+mutation"
                if candidate.operator == "crossover"
                else "mutation"
            ) if succeeded else candidate.operator,
            mutation_type="code",
            timing=timing,
            metadata=metadata,
        )

    def _reflection_request(self, candidate: Candidate, parent_java: str) -> str:
        return render_prompt(
            "code_reflection",
            {
                "strategy_prompt": candidate.strategy_prompt,
                "parent_java": parent_java,
                "gameplay_contract": load_prompt("microrts_gameplay_contract"),
                "action_api_guide": load_prompt("action_api_guide"),
                "java_scaffold": load_java_template(
                    JavaTemplatePaths(self.config.agent_template_path)
                ),
            },
        )

    def _revision_request(
        self,
        candidate: Candidate,
        parent_java: str,
        reflection_conclusion: dict[str, object],
    ) -> str:
        return render_prompt(
            "code_revision",
            {
                "strategy_prompt": candidate.strategy_prompt,
                "parent_java": parent_java,
                "reflection_conclusion": json.dumps(
                    reflection_conclusion,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "gameplay_contract": load_prompt("microrts_gameplay_contract"),
                "action_api_guide": load_prompt("action_api_guide"),
                "java_scaffold": load_java_template(
                    JavaTemplatePaths(self.config.agent_template_path)
                ),
            },
        )

    @staticmethod
    def _write_revision_attempt(
        target_dir: Path | None,
        *,
        attempt_number: int,
        request: str,
        response: str,
    ) -> None:
        if target_dir is None:
            return
        directory = target_dir / "mutation" / "code_reflection"
        _write_text(
            directory / f"revision_attempt_{attempt_number:03d}_request.txt",
            request,
        )
        _write_text(
            directory / f"revision_attempt_{attempt_number:03d}_response_raw.txt",
            response,
        )

    @staticmethod
    def _write_result(
        target_dir: Path | None,
        *,
        request: str,
        response: str,
        parent_java: str,
        reflected_java: str,
        reflection: ReflectionResult,
        reflection_conclusion: dict[str, object],
        revision: dict[str, object],
        metadata: dict[str, object],
    ) -> None:
        if target_dir is None:
            return
        directory = target_dir / "mutation" / "code_reflection"
        _write_text(directory / "reflector_request.txt", reflection.request)
        _write_text(directory / "reflector_response_raw.txt", reflection.raw_response)
        _write_json(directory / "reflection_conclusion.json", reflection_conclusion)
        _write_text(directory / "revision_request.txt", request)
        _write_text(directory / "revision_response_raw.txt", response)
        _write_text(directory / "parent_candidate.java", parent_java)
        _write_text(directory / "reflected_candidate.java", reflected_java)
        _write_json(directory / "metadata.json", _metadata_record(metadata))


def _sha256(value: str) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _metadata_record(record: dict[str, object]) -> dict[str, object]:
    payload = dict(record)
    for key in ("reflection", "revision"):
        stage = payload.get(key)
        if isinstance(stage, dict):
            payload[key] = {
                name: value
                for name, value in stage.items()
                if name not in {"request", "raw_response", "reflection"}
            }
    return payload
