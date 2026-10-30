"""LLM Coach contracts for framework-slot initialization and mutation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from eagle.candidate import Candidate
from eagle.generation.framework_slots import (
    FrameworkBundle,
    slot_value_at,
    slot_value_count,
    validate_genome,
)
from eagle.llm import LLMCallLogger
from eagle.llm import json_schema_response_format, llm_request_progress
from eagle.prompts import render_prompt
from eagle.generation.groq_framework import (
    DEFAULT_GPT_API_ROOT,
    GPT_API_KEY_PATH,
)


FRAMEWORK_SELECTION_SCHEMA_VERSION = "eagle-framework-selection-v1"
FRAMEWORK_SELECTION_SCHEMA_NAME = "eagle_framework_selection"
DIRECT_GPT_SELECTION_MAX_COMPLETION_TOKENS = 4_096


class DirectGPTFrameworkSelectionBackend:
    """Authenticated direct GPT transport for a bounded gen-zero selection prefix.

    This deliberately bypasses the experiment's managed local model.  The
    normal ``StrategyReflectionPipeline`` remains the owner of retries,
    validation, timing, and candidate-owned artifacts.
    """

    def __init__(
        self,
        *,
        model: str,
        response_schema: dict[str, object],
        timeout_seconds: float = 300.0,
    ) -> None:
        try:
            api_key = GPT_API_KEY_PATH.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError("GPT API key is required in api_key/gpt.") from exc
        if not api_key:
            raise ValueError("GPT API key is required in api_key/gpt.")
        self._api_key = api_key
        self.model = model
        self.response_schema = response_schema
        self.timeout_seconds = timeout_seconds
        self.base_url = DEFAULT_GPT_API_ROOT
        self.operation = "framework_initial_gpt_selection"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": json_schema_response_format(
                self.response_schema,
                name=FRAMEWORK_SELECTION_SCHEMA_NAME,
                strict=True,
            ),
            "max_completion_tokens": DIRECT_GPT_SELECTION_MAX_COMPLETION_TOKENS,
            "reasoning_effort": "low",
        }
        request = urllib.request.Request(
            self.chat_completions_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with llm_request_progress(
                stage=self.operation,
                endpoint=self.chat_completions_url,
                model=self.model,
            ):
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(
                f"direct GPT framework selection HTTP {exc.code}: {exc.reason}; "
                f"response_body_start={response_body!r}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"direct GPT framework selection request failed: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"direct GPT framework selection returned invalid JSON: {exc}") from exc

        if not isinstance(envelope, dict):
            raise RuntimeError("direct GPT framework selection response must be an object")
        choices = envelope.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise RuntimeError("direct GPT framework selection response must contain one choice")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise RuntimeError("direct GPT framework selection must finish with stop")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("refusal"):
            raise RuntimeError("direct GPT framework selection was refused")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("direct GPT framework selection response has no JSON content")
        return content


def framework_selection_response_schema(
    bundle: FrameworkBundle,
    framework_bundle_sha256: str,
) -> dict[str, object]:
    """Build the exact finite-domain schema for one frozen framework bundle."""

    genome_properties: dict[str, object] = {}
    for slot in bundle.slots:
        values = [
            slot_value_at(slot, index)
            for index in range(slot_value_count(slot))
        ]
        genome_properties[slot.slot_id] = {
            "type": "string" if slot.kind == "expression_choice" else slot.kind,
            "enum": values,
        }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": [FRAMEWORK_SELECTION_SCHEMA_VERSION],
            },
            "framework_bundle_sha256": {
                "type": "string",
                "enum": [framework_bundle_sha256],
            },
            "control_genome": {
                "type": "object",
                "additionalProperties": False,
                "properties": genome_properties,
                "required": list(bundle.slot_ids),
            },
        },
        "required": [
            "schema_version",
            "framework_bundle_sha256",
            "control_genome",
        ],
    }


def framework_bundle_evidence(bundle: FrameworkBundle) -> dict[str, Any]:
    """Return strategy-facing bundle evidence without Java implementation text."""

    return {
        "schema_version": bundle.schema_version,
        "framework_id": bundle.framework_id,
        "slot_generation_prompt": bundle.slot_generation_prompt,
        "report": bundle.report.to_json_dict(),
        "slots": [
            {
                "slot_id": slot.slot_id,
                "kind": slot.kind,
                "default": slot.default,
                "minimum": slot.minimum,
                "maximum": slot.maximum,
                "step": slot.step,
                "choices": [
                    {
                        "choice_id": choice.choice_id,
                        "description": choice.description,
                    }
                    for choice in slot.choices
                ],
                "purpose": slot.purpose,
            }
            for slot in bundle.slots
        ],
    }


def framework_initial_selection_prompt(
    bundle: FrameworkBundle,
    *,
    framework_bundle_sha256: str,
    current_control_genome: dict[str, Any],
) -> str:
    return render_prompt(
        "framework_initial_selection",
        {
            "framework_bundle": json.dumps(
                framework_bundle_evidence(bundle), ensure_ascii=False, sort_keys=True
            ),
            "framework_bundle_sha256": framework_bundle_sha256,
            "current_control_genome": json.dumps(
                current_control_genome, ensure_ascii=False, sort_keys=True
            ),
        },
    )


def framework_coach_selection_prompt(
    bundle: FrameworkBundle,
    *,
    framework_bundle_sha256: str,
    evaluated_parent_control_genome: dict[str, Any],
    current_child_control_genome: dict[str, Any],
    coach_evidence: dict[str, Any],
) -> str:
    return render_prompt(
        "framework_coach_selection",
        {
            "framework_bundle": json.dumps(
                framework_bundle_evidence(bundle), ensure_ascii=False, sort_keys=True
            ),
            "framework_bundle_sha256": framework_bundle_sha256,
            "evaluated_parent_control_genome": json.dumps(
                evaluated_parent_control_genome, ensure_ascii=False, sort_keys=True
            ),
            "current_child_control_genome": json.dumps(
                current_child_control_genome, ensure_ascii=False, sort_keys=True
            ),
            "commentator_diagnoses_and_evaluation_metadata": json.dumps(
                coach_evidence, ensure_ascii=False, sort_keys=True
            ),
        },
    )


def validate_framework_selection_response(
    raw: str,
    *,
    bundle: FrameworkBundle,
    framework_bundle_sha256: str,
) -> tuple[dict[str, object], dict[str, Any]]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"framework Coach JSON contains duplicate key: {key}")
            result[key] = value
        return result

    payload = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(payload, dict):
        raise ValueError("framework Coach response must be one JSON object")
    expected_keys = {
        "schema_version",
        "framework_bundle_sha256",
        "control_genome",
    }
    if set(payload) != expected_keys:
        raise ValueError(
            "framework Coach JSON must contain exactly schema_version, "
            "framework_bundle_sha256, and control_genome"
        )
    if payload["schema_version"] != FRAMEWORK_SELECTION_SCHEMA_VERSION:
        raise ValueError(
            "framework Coach schema_version must be "
            f"{FRAMEWORK_SELECTION_SCHEMA_VERSION!r}"
        )
    if payload["framework_bundle_sha256"] != framework_bundle_sha256:
        raise ValueError("framework Coach response bundle hash does not match the run bundle")
    genome = validate_genome(bundle, payload["control_genome"])
    return payload, genome


def select_initial_framework_genome(
    candidate: Candidate,
    bundle: FrameworkBundle,
    backend: object,
    *,
    artifact_dir: Path | None,
    timing_logger: LLMCallLogger | None = None,
    max_attempts: int = 3,
    model_identity: str | None = None,
    selection_seed: int = 0,
) -> Candidate:
    """Select one complete validated generation-zero framework genome."""

    from eagle.operators.strategy import StrategyReflectionPipeline

    pipeline = StrategyReflectionPipeline(
        backend,  # type: ignore[arg-type]
        max_attempts=max_attempts,
        model_identity=model_identity,
        selection_seed=selection_seed,
        timing_logger=timing_logger,
        framework_bundle=bundle,
        framework_bundle_sha256=candidate.framework_bundle_sha256,
    )
    return pipeline.select_initial_framework_genome(candidate, artifact_dir=artifact_dir)


class MockFrameworkRoleBackend:
    """Deterministic valid framework Coach backend for mock runs and tests."""

    def __init__(self, bundle: FrameworkBundle, framework_bundle_sha256: str) -> None:
        from eagle.operators.strategy import MockRoleBackend

        self.bundle = bundle
        self.framework_bundle_sha256 = framework_bundle_sha256
        self.prompts: list[str] = []
        self._commentator = MockRoleBackend()

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "ROLE: match_commentator" in prompt:
            return self._commentator.generate(prompt)
        return json.dumps(
            {
                "schema_version": FRAMEWORK_SELECTION_SCHEMA_VERSION,
                "framework_bundle_sha256": self.framework_bundle_sha256,
                "control_genome": validate_genome(
                    self.bundle,
                    {slot.slot_id: slot.default for slot in self.bundle.slots},
                ),
            }
        )


__all__ = [
    "DirectGPTFrameworkSelectionBackend",
    "FRAMEWORK_SELECTION_SCHEMA_NAME",
    "FRAMEWORK_SELECTION_SCHEMA_VERSION",
    "MockFrameworkRoleBackend",
    "framework_bundle_evidence",
    "framework_selection_response_schema",
    "select_initial_framework_genome",
    "validate_framework_selection_response",
]
