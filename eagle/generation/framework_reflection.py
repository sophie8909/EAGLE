"""Bounded whole-framework reflection, independent of genetic variation."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.generation.framework_slots import FrameworkBundle, validate_framework_bundle
from eagle.generation.groq_framework import (
    DEFAULT_LOCAL_FRAMEWORK_MAX_OUTPUT_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    FRAMEWORK_RESPONSE_SCHEMA,
)
from eagle.llm import LLMCallLogger, LLMClient, parse_json_object_response
from eagle.operators.framework_coach import (
    FRAMEWORK_SELECTION_SCHEMA_VERSION,
    framework_bundle_evidence,
    framework_selection_response_schema,
    validate_framework_selection_response,
)
from eagle.prompts import load_prompt, render_prompt
from eagle.timing import utc_now


FRAMEWORK_REFLECTION_SCHEMA_VERSION = "eagle-framework-reflection-v1"
FRAMEWORK_COACH_MIGRATION_SCHEMA_VERSION = "eagle-framework-coach-migration-v1"
FRAMEWORK_STRATEGY_REVISION_SCHEMA_VERSION = "eagle-framework-strategy-revision-v1"
MAX_REPAIR_RETRIES = 3


def reflect_framework(
    *,
    previous_bundle: FrameworkBundle,
    population_evidence: list[dict],
    client: LLMClient,
    config: ExperimentConfig,
    artifact_dir: Path,
    validate_bundle: Callable[[FrameworkBundle], None],
    timing_logger: LLMCallLogger | None = None,
    generation: int | None = None,
) -> FrameworkBundle | None:
    """Return a validated replacement, or retain the previous bundle on failure.

    The callback must raise with exact compiler/validation diagnostics on failure.
    Nothing is published into the active run configuration by this provider.
    """

    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_json(artifact_dir / "previous_bundle.json", previous_bundle.to_json_dict())
    _write_json(artifact_dir / "population_evidence.json", population_evidence)
    prompt = render_prompt(
        "framework_reflection",
        {
            "gameplay_contract": load_prompt("microrts_gameplay_contract"),
            "action_api_guide": load_prompt("action_api_guide"),
            "response_schema": json.dumps(FRAMEWORK_RESPONSE_SCHEMA, ensure_ascii=False),
            "previous_framework_bundle": json.dumps(previous_bundle.to_json_dict(), ensure_ascii=False),
            "population_evidence": json.dumps(population_evidence, ensure_ascii=False, allow_nan=False),
        },
    )
    client = replace(
        client,
        max_output_tokens=client.max_output_tokens or DEFAULT_LOCAL_FRAMEWORK_MAX_OUTPUT_TOKENS,
        timeout_seconds=max(client.timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
    )
    backend = client.prompt_backend(
        operation="framework_reflection",
        response_schema=FRAMEWORK_RESPONSE_SCHEMA,
        response_schema_name="eagle_framework_bundle",
        max_prompt_chars=None,
    )
    attempts: list[dict] = []
    previous_output = ""
    last_error: str | None = None
    selected_bundle: FrameworkBundle | None = None
    for attempt in range(1, MAX_REPAIR_RETRIES + 2):
        attempt_prompt = prompt
        if last_error is not None:
            attempt_prompt += (
                "\n\nRepair the immediately previous output using the exact error below. "
                "Return the complete corrected bundle, preserving slot representation."
                "\nPrevious output:\n" + previous_output
                + "\nExact validation/compiler error:\n" + last_error
            )
        attempt_dir = artifact_dir / "attempts" / f"attempt_{attempt:03d}"
        attempt_dir.mkdir(parents=True)
        (attempt_dir / "request.txt").write_text(attempt_prompt, encoding="utf-8")
        response_path = attempt_dir / "response_raw.txt"
        response_path.write_text("", encoding="utf-8")
        started_at = utc_now()
        started = time.monotonic()
        error = None
        previous_output = ""
        try:
            previous_output = backend.generate(attempt_prompt)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            error = str(exc)
        request_finished_at = utc_now()
        request_duration = max(0.0, time.monotonic() - started)
        if error is None:
            response_path.write_text(previous_output, encoding="utf-8")
        if timing_logger is not None:
            timing_logger.write_timing_event(
                request_correlation_id=(
                    f"{timing_logger.run_id}:framework_reflection:{generation}:"
                    f"{artifact_dir.name}:{attempt}"
                ),
                stage="framework_reflection",
                status="success" if error is None else "failed",
                model=backend.model,
                candidate_id=None,
                generation=generation,
                started_at=started_at,
                finished_at=request_finished_at,
                duration_seconds=request_duration,
                metadata={
                    "operation_type": "framework_reflection",
                    "endpoint": client.selected_endpoint.base_url,
                    "failure_category": "llm_transport_error" if error is not None else None,
                    "transport_attempt": 1,
                    "reflection_attempt": attempt,
                },
            )
        if error is None:
            try:
                proposed_bundle = validate_framework_bundle(parse_json_object_response(previous_output))
                validate_bundle(proposed_bundle)
                selected_bundle = proposed_bundle
            except (ValueError, TypeError, RuntimeError, OSError) as exc:
                error = str(exc)
        attempt_record = {
            "schema_version": FRAMEWORK_REFLECTION_SCHEMA_VERSION,
            "attempt": attempt,
            "status": "success" if selected_bundle is not None else "failed",
            "error": error,
            "model": backend.model,
            "backend": config.execution_mode,
            "operation": "framework_reflection",
            "started_at": started_at,
            "finished_at": utc_now(),
            "duration_seconds": max(0.0, time.monotonic() - started),
        }
        _write_json(attempt_dir / "result.json", attempt_record)
        attempts.append(attempt_record)
        if selected_bundle is not None:
            _write_json(artifact_dir / "bundle.json", selected_bundle.to_json_dict())
            break
        last_error = error
    _write_json(artifact_dir / "result.json", {
        "schema_version": FRAMEWORK_REFLECTION_SCHEMA_VERSION,
        "status": "success" if selected_bundle is not None else "rollback",
        "previous_bundle_sha256": previous_bundle.bundle_sha256,
        "selected_bundle_sha256": (
            selected_bundle.bundle_sha256 if selected_bundle is not None
            else previous_bundle.bundle_sha256
        ),
        "selected_attempt": len(attempts) if selected_bundle is not None else None,
        "attempts": attempts,
        "error": last_error if selected_bundle is None else None,
    })
    return selected_bundle


def select_reflected_genomes(
    *,
    bundle: FrameworkBundle,
    framework_bundle_sha256: str,
    previous_bundle: FrameworkBundle,
    population_evidence: list[dict],
    client: LLMClient,
    config: ExperimentConfig,
    artifact_dir: Path,
    timing_logger: LLMCallLogger | None = None,
    generation: int | None = None,
) -> dict[str, dict]:
    """Ask Coach once to fill every new genome; outer framework repair owns retries."""

    candidate_ids = [item.get("candidate_id") for item in population_evidence]
    if (
        not candidate_ids
        or any(not isinstance(identity, str) or not identity for identity in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
    ):
        raise ValueError("Framework Coach migration requires distinct nonempty candidate IDs.")
    selection_schema = framework_selection_response_schema(bundle, framework_bundle_sha256)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "enum": [FRAMEWORK_COACH_MIGRATION_SCHEMA_VERSION]},
            "framework_bundle_sha256": {"type": "string", "enum": [framework_bundle_sha256]},
            "selections": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    identity: selection_schema["properties"]["control_genome"]
                    for identity in candidate_ids
                },
                "required": candidate_ids,
            },
        },
        "required": ["schema_version", "framework_bundle_sha256", "selections"],
    }
    prompt = render_prompt(
        "framework_coach_migration",
        {
            "framework_bundle_sha256": framework_bundle_sha256,
            "previous_framework_bundle": json.dumps(framework_bundle_evidence(previous_bundle), ensure_ascii=False),
            "framework_bundle": json.dumps(framework_bundle_evidence(bundle), ensure_ascii=False),
            "population_evidence": json.dumps(population_evidence, ensure_ascii=False, allow_nan=False),
            "response_schema": json.dumps(schema, ensure_ascii=False),
        },
    )
    backend = client.prompt_backend(
        operation="framework_coach_migration",
        response_schema=schema,
        response_schema_name="eagle_framework_coach_migration",
        max_prompt_chars=None,
    )
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "request.txt").write_text(prompt, encoding="utf-8")
    response_path = artifact_dir / "response_raw.txt"
    response_path.write_text("", encoding="utf-8")
    started_at, started = utc_now(), time.monotonic()
    error = None
    raw_response = ""
    try:
        raw_response = backend.generate(prompt)
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        error = str(exc)
    request_finished_at = utc_now()
    request_duration = max(0.0, time.monotonic() - started)
    if error is None:
        response_path.write_text(raw_response, encoding="utf-8")
    if timing_logger is not None:
        timing_logger.write_timing_event(
            request_correlation_id=(
                f"{timing_logger.run_id}:framework_coach_migration:{generation}:"
                f"{artifact_dir.as_posix()}"
            ),
            stage="framework_coach_migration",
            status="success" if error is None else "failed",
            model=backend.model,
            candidate_id=None,
            generation=generation,
            started_at=started_at,
            finished_at=request_finished_at,
            duration_seconds=request_duration,
            metadata={
                "operation_type": "framework_coach_migration",
                "endpoint": client.selected_endpoint.base_url,
                "failure_category": "llm_transport_error" if error is not None else None,
                "transport_attempt": 1,
            },
        )
    selections = None
    if error is None:
        try:
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"Framework Coach migration JSON contains duplicate key: {key}")
                    result[key] = value
                return result

            payload = json.loads(raw_response, object_pairs_hook=unique_object)
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version", "framework_bundle_sha256", "selections",
            }:
                raise ValueError("Framework Coach migration response must contain exactly schema_version, framework_bundle_sha256, and selections.")
            if payload["schema_version"] != FRAMEWORK_COACH_MIGRATION_SCHEMA_VERSION:
                raise ValueError("Framework Coach migration schema_version mismatch.")
            if payload["framework_bundle_sha256"] != framework_bundle_sha256:
                raise ValueError("Framework Coach migration bundle hash mismatch.")
            if not isinstance(payload["selections"], dict) or set(payload["selections"]) != set(candidate_ids):
                raise ValueError("Framework Coach migration selections must cover exactly every source candidate ID.")
            selections = {}
            for identity in candidate_ids:
                _, selections[identity] = validate_framework_selection_response(
                    json.dumps({
                        "schema_version": FRAMEWORK_SELECTION_SCHEMA_VERSION,
                        "framework_bundle_sha256": framework_bundle_sha256,
                        "control_genome": payload["selections"][identity],
                    }, ensure_ascii=False),
                    bundle=bundle,
                    framework_bundle_sha256=framework_bundle_sha256,
                )
        except (ValueError, TypeError) as exc:
            error = str(exc)
    _write_json(artifact_dir / "result.json", {
        "schema_version": FRAMEWORK_COACH_MIGRATION_SCHEMA_VERSION,
        "status": "success" if error is None else "failed",
        "framework_bundle_sha256": framework_bundle_sha256,
        "operation": "framework_coach_migration",
        "model": backend.model,
        "backend": config.execution_mode,
        "candidate_ids": candidate_ids,
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": max(0.0, time.monotonic() - started),
        "error": error,
    })
    if error is not None:
        raise ValueError(f"Framework Coach migration failed: {error}; raw response:\n{raw_response}")
    assert selections is not None
    return selections


def revise_strategy_descriptions(
    *,
    previous_bundle: FrameworkBundle,
    bundle: FrameworkBundle,
    population_evidence: list[dict],
    client: LLMClient,
    config: ExperimentConfig,
    artifact_dir: Path,
    timing_logger: LLMCallLogger | None = None,
    generation: int | None = None,
) -> dict[str, str]:
    """Revise every strategy before slot filling; outer framework repair owns retries."""

    candidate_ids = [item.get("candidate_id") for item in population_evidence]
    if (
        not candidate_ids
        or any(not isinstance(identity, str) or not identity for identity in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
    ):
        raise ValueError("Strategy revision requires distinct nonempty candidate IDs.")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "enum": [FRAMEWORK_STRATEGY_REVISION_SCHEMA_VERSION]},
            "strategy_descriptions": {
                "type": "object",
                "additionalProperties": False,
                "properties": {identity: {"type": "string", "minLength": 1} for identity in candidate_ids},
                "required": candidate_ids,
            },
        },
        "required": ["schema_version", "strategy_descriptions"],
    }
    prompt = render_prompt(
        "framework_strategy_revision",
        {
            "previous_framework_bundle": json.dumps(framework_bundle_evidence(previous_bundle), ensure_ascii=False),
            "framework_bundle": json.dumps(framework_bundle_evidence(bundle), ensure_ascii=False),
            "population_evidence": json.dumps(population_evidence, ensure_ascii=False, allow_nan=False),
            "response_schema": json.dumps(schema, ensure_ascii=False),
        },
    )
    backend = client.prompt_backend(
        operation="framework_strategy_revision",
        response_schema=schema,
        response_schema_name="eagle_framework_strategy_revision",
        max_prompt_chars=None,
    )
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "request.txt").write_text(prompt, encoding="utf-8")
    response_path = artifact_dir / "response_raw.txt"
    response_path.write_text("", encoding="utf-8")
    started_at, started = utc_now(), time.monotonic()
    error = None
    raw_response = ""
    try:
        raw_response = backend.generate(prompt)
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        error = str(exc)
    request_finished_at = utc_now()
    request_duration = max(0.0, time.monotonic() - started)
    if error is None:
        response_path.write_text(raw_response, encoding="utf-8")
    if timing_logger is not None:
        timing_logger.write_timing_event(
            request_correlation_id=(
                f"{timing_logger.run_id}:framework_strategy_revision:{generation}:"
                f"{artifact_dir.as_posix()}"
            ),
            stage="framework_strategy_revision",
            status="success" if error is None else "failed",
            model=backend.model,
            candidate_id=None,
            generation=generation,
            started_at=started_at,
            finished_at=request_finished_at,
            duration_seconds=request_duration,
            metadata={
                "operation_type": "framework_strategy_revision",
                "endpoint": client.selected_endpoint.base_url,
                "failure_category": "llm_transport_error" if error is not None else None,
                "transport_attempt": 1,
            },
        )
    descriptions = None
    if error is None:
        try:
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"Strategy revision JSON contains duplicate key: {key}")
                    result[key] = value
                return result

            payload = json.loads(raw_response, object_pairs_hook=unique_object)
            if not isinstance(payload, dict) or set(payload) != {"schema_version", "strategy_descriptions"}:
                raise ValueError("Strategy revision response must contain exactly schema_version and strategy_descriptions.")
            if payload["schema_version"] != FRAMEWORK_STRATEGY_REVISION_SCHEMA_VERSION:
                raise ValueError("Strategy revision schema_version mismatch.")
            values = payload["strategy_descriptions"]
            if not isinstance(values, dict) or set(values) != set(candidate_ids):
                raise ValueError("Strategy revision descriptions must cover exactly every source candidate ID.")
            if any(not isinstance(value, str) or not value.strip() for value in values.values()):
                raise ValueError("Strategy descriptions must be nonempty strings.")
            descriptions = {identity: " ".join(values[identity].split()) for identity in candidate_ids}
        except (ValueError, TypeError) as exc:
            error = str(exc)
    _write_json(artifact_dir / "result.json", {
        "schema_version": FRAMEWORK_STRATEGY_REVISION_SCHEMA_VERSION,
        "status": "success" if error is None else "failed",
        "operation": "framework_strategy_revision",
        "model": backend.model,
        "backend": config.execution_mode,
        "candidate_ids": candidate_ids,
        "strategy_descriptions": descriptions if error is None else None,
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": max(0.0, time.monotonic() - started),
        "error": error,
    })
    if error is not None:
        raise ValueError(f"Framework strategy revision failed: {error}; raw response:\n{raw_response}")
    assert descriptions is not None
    return descriptions


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
