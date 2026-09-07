"""Direct Java mutation for the Code Reflection operator."""

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
from .mutation import ReflectionAttempt, ReflectionContext, _timing_payload, utc_now
from .prompts import load_prompt, render_prompt
from .reflection_context import coerce_structured_context


CODE_REFLECTION_SCHEMA_VERSION = "eagle-code-reflection-v1"


class CodeReflectionMutation:
    """Ask the Java-capable backend to revise one selected parent source directly."""

    mutation_type = "code"

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        backend: Any,
        artifact_root: Path | None = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.artifact_root = artifact_root

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
        base_request = self._request(candidate, parent_java) if parent_java.strip() else ""
        attempts: list[ReflectionAttempt] = []
        response = ""
        reflected_java = ""
        last_error: str | None = None

        for attempt_number in range(1, self.config.mutation_max_attempts + 1):
            if not base_request:
                last_error = "Code Reflection requires a non-empty selected parent Java source."
                break
            attempt_request = (
                base_request
                if last_error is None
                else render_prompt(
                    "code_reflection_retry",
                    {
                        "original_request": base_request,
                        "previous_response": response,
                        "validation_error": last_error,
                    },
                )
            )
            if hasattr(self.backend, "prepare_request"):
                attempt_request = self.backend.prepare_request(attempt_request)
            if hasattr(self.backend, "set_generation_attempt_context"):
                self.backend.set_generation_attempt_context(
                    attempt_number,
                    f"{candidate.id}:code_reflection:{attempt_number:03d}",
                )
            if hasattr(self.backend, "set_generation_request_kind"):
                self.backend.set_generation_request_kind("code_reflection")
            started_at = utc_now()
            started = time.monotonic()
            status = "success"
            error: str | None = None
            try:
                response = self.backend.generate_from_request(
                    candidate,
                    "CandidateAgent",
                    attempt_request,
                )
                reflected_java = normalize_java_agent_source(
                    extract_code_from_output(response)
                )
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
                    duration_seconds=max(0.0, time.monotonic() - started),
                    status=status,
                    error=error,
                )
            )
            self._write_attempt(
                target_dir,
                attempt_number=attempt_number,
                request=attempt_request,
                response=response,
            )
            if status == "success":
                break
            time.sleep(0)

        succeeded = bool(reflected_java)
        # A failed reflection preserves and evaluates the selected parent Java;
        # it never falls through to an unrelated fresh Generator decode.
        direct_java = reflected_java or parent_java
        mutation_record = {
            "schema_version": CODE_REFLECTION_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "feedback_candidate_id": feedback_candidate_id,
            "operation": "code_reflection_mutation",
            "type": "code",
            "applied": succeeded,
            "reflection_status": "success" if succeeded else "failed",
            "reflection_error": None if succeeded else last_error,
            "reflection_attempts": len(attempts),
            "attempts": [attempt.to_dict() for attempt in attempts],
            "rewrite_attempts": 0,
            "model": getattr(self.backend, "model", None),
            "reflection_operation": getattr(self.backend, "operation", None),
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
        }
        timing = dict(candidate.timing)
        timing["code_reflector_llm"] = _timing_payload(tuple(attempts))
        history = [{
            "reflection_type": "code",
            "parent_candidate_id": feedback_candidate_id,
            "analysis_summary": (
                "direct_java_revision" if succeeded else "parent_java_preserved"
            ),
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
            response=response,
            parent_java=parent_java,
            reflected_java=direct_java,
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

    def _request(self, candidate: Candidate, parent_java: str) -> str:
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

    @staticmethod
    def _write_attempt(
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
            directory / f"reflector_attempt_{attempt_number:03d}_request.txt",
            request,
        )
        _write_text(
            directory / f"reflector_attempt_{attempt_number:03d}_response_raw.txt",
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
        metadata: dict[str, object],
    ) -> None:
        if target_dir is None:
            return
        directory = target_dir / "mutation" / "code_reflection"
        _write_text(directory / "reflector_request.txt", request)
        _write_text(directory / "reflector_response_raw.txt", response)
        _write_text(directory / "parent_candidate.java", parent_java)
        _write_text(directory / "reflected_candidate.java", reflected_java)
        _write_json(directory / "metadata.json", metadata)


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
