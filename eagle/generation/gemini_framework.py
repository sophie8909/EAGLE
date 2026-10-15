"""One-shot Gemini bootstrap for an immutable, slot-controlled Java framework.

This module intentionally stops at framework-bundle creation.  Evolutionary
configuration, candidate state, and Java materialization consume the bundle in
separate layers.  Authentication is read only from ``GEMINI_API_KEY`` and is
never included in persisted request or result artifacts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from eagle.generation.framework_slots import (
    FRAMEWORK_BUNDLE_SCHEMA_VERSION,
    SLOT_KINDS,
    FrameworkBundle,
    validate_framework_bundle,
)
from eagle.prompts import load_prompt, render_prompt


FRAMEWORK_SCHEMA_VERSION = FRAMEWORK_BUNDLE_SCHEMA_VERSION
BOOTSTRAP_SCHEMA_VERSION = "eagle-gemini-framework-bootstrap-v1"
ATTEMPT_SCHEMA_VERSION = "eagle-gemini-framework-attempt-v1"
DEFAULT_GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_OUTPUT_TOKENS = 32_768

FRAMEWORK_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {
            "type": "string",
            "enum": [FRAMEWORK_SCHEMA_VERSION],
        },
        "framework_id": {"type": "string"},
        "java_template": {"type": "string"},
        "slots": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "slot_id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": list(SLOT_KINDS),
                    },
                    "marker": {"type": "string"},
                    "default": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "number"},
                            {"type": "string"},
                        ]
                    },
                    "minimum": {"type": ["number", "null"]},
                    "maximum": {"type": ["number", "null"]},
                    "step": {"type": ["number", "null"]},
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "choice_id": {"type": "string"},
                                "java_expression": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": [
                                "choice_id",
                                "java_expression",
                                "description",
                            ],
                        },
                    },
                    "purpose": {"type": "string"},
                },
                "required": [
                    "slot_id",
                    "kind",
                    "marker",
                    "default",
                    "minimum",
                    "maximum",
                    "step",
                    "choices",
                    "purpose",
                ],
            },
        },
        "slot_generation_prompt": {"type": "string"},
        "report": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "architecture_summary": {"type": "string"},
                "decision_flow": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "invariants": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "slot_rationale": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "risks": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "architecture_summary",
                "decision_flow",
                "invariants",
                "slot_rationale",
                "assumptions",
                "risks",
            ],
        },
    },
    "required": [
        "schema_version",
        "framework_id",
        "java_template",
        "slots",
        "slot_generation_prompt",
        "report",
    ],
}


class GeminiFrameworkError(RuntimeError):
    """The bounded framework bootstrap did not produce a valid bundle."""


@dataclass(frozen=True)
class GeminiFrameworkResult:
    """Published framework bundle and its compact bootstrap record."""

    output_dir: Path
    bundle_path: Path
    bootstrap_path: Path
    bundle: dict[str, object]


def generate_framework_bundle(
    output_dir: str | Path,
    *,
    model: str,
    design_brief: str,
    temperature: float = 0.2,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    api_root: str = DEFAULT_GEMINI_API_ROOT,
) -> GeminiFrameworkResult:
    """Call Gemini with a fixed JSON schema and publish one validated bundle.

    Every attempt owns its exact credential-free request body, raw HTTP body,
    timing, hashes, and result.  The raw body is flushed to disk before any
    provider-envelope or generated-content parsing occurs.
    """

    target = Path(output_dir).expanduser().resolve()
    _validate_settings(
        model=model,
        design_brief=design_brief,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        api_root=api_root,
    )
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key.strip():
        raise GeminiFrameworkError("GEMINI_API_KEY is required for framework generation.")
    _prepare_output_directory(target)

    prompt = render_prompt(
        "gemini_framework_design",
        {
            "design_brief": design_brief.strip(),
            "gameplay_contract": load_prompt("microrts_gameplay_contract"),
            "action_api_guide": load_prompt("action_api_guide"),
        },
    )
    model_name = model.removeprefix("models/")
    endpoint = (
        api_root.rstrip("/")
        + "/models/"
        + urllib.parse.quote(model_name, safe="._-")
        + ":generateContent"
    )
    request_payload = _request_payload(
        prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    request_bytes = json.dumps(
        request_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request_sha256 = _sha256(request_bytes)
    (target / "prompt.txt").write_text(prompt, encoding="utf-8")
    attempts_root = target / "attempts"
    attempts_root.mkdir()

    overall_started_at = _utc_now()
    overall_started = time.monotonic()
    selected_attempt: int | None = None
    selected_bundle: dict[str, object] | None = None
    selected_response_sha256: str | None = None
    last_error = "Gemini returned no response."
    attempt_summaries: list[dict[str, object]] = []

    for attempt in range(1, max_attempts + 1):
        attempt_dir = attempts_root / f"attempt_{attempt:03d}"
        attempt_dir.mkdir()
        (attempt_dir / "request.json").write_bytes(request_bytes)
        raw_path = attempt_dir / "response_raw.json"
        raw_path.write_bytes(b"")
        started_at = _utc_now()
        started = time.monotonic()
        status = "failed"
        error: str | None = None
        http_status: int | None = None
        raw_response = b""
        retryable = True
        bundle: dict[str, object] | None = None
        try:
            request = urllib.request.Request(
                endpoint,
                data=request_bytes,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                http_status = int(getattr(response, "status", 200))
                raw_response = response.read()
            raw_path.write_bytes(raw_response)
            bundle = parse_gemini_framework_response(raw_response)
            status = "success"
            retryable = False
        except urllib.error.HTTPError as exc:
            http_status = int(exc.code)
            raw_response = exc.read()
            raw_path.write_bytes(raw_response)
            error = f"Gemini API HTTP {exc.code}: {exc.reason}"
            retryable = exc.code in {408, 409, 429} or 500 <= exc.code <= 599
        except (urllib.error.URLError, TimeoutError) as exc:
            error = f"Gemini API request failed: {exc}"
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            error = f"Gemini response validation failed: {exc}"
        except OSError as exc:
            error = f"Gemini framework artifact failure: {exc}"
            retryable = False

        finished_at = _utc_now()
        duration_seconds = max(0.0, time.monotonic() - started)
        response_sha256 = _sha256(raw_response)
        safe_error = _redact(error, api_key)
        attempt_record = {
            "schema_version": ATTEMPT_SCHEMA_VERSION,
            "attempt": attempt,
            "status": status,
            "retryable": retryable,
            "error": safe_error,
            "provider": "gemini",
            "model": model_name,
            "endpoint": endpoint,
            "http_status": http_status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
        }
        _write_json(attempt_dir / "result.json", attempt_record)
        attempt_summaries.append(
            {
                "attempt": attempt,
                "status": status,
                "retryable": retryable,
                "error": safe_error,
                "duration_seconds": duration_seconds,
                "request_sha256": request_sha256,
                "response_sha256": response_sha256,
                "artifact": f"attempts/attempt_{attempt:03d}",
            }
        )
        if bundle is not None:
            selected_attempt = attempt
            selected_bundle = bundle
            selected_response_sha256 = response_sha256
            break
        last_error = safe_error or last_error
        if not retryable:
            break

    finished_at = _utc_now()
    duration_seconds = max(0.0, time.monotonic() - overall_started)
    if selected_bundle is None or selected_attempt is None:
        failure_record = {
            "schema_version": BOOTSTRAP_SCHEMA_VERSION,
            "status": "failed",
            "provider": "gemini",
            "model": model_name,
            "endpoint": endpoint,
            "max_attempts": max_attempts,
            "selected_attempt": None,
            "started_at": overall_started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "request_sha256": request_sha256,
            "response_sha256": None,
            "bundle_sha256": None,
            "attempts": attempt_summaries,
            "error": last_error,
        }
        _write_json(target / "bootstrap.json", failure_record)
        raise GeminiFrameworkError(
            f"Gemini framework generation failed after {len(attempt_summaries)} attempt(s): "
            f"{last_error}"
        )

    # Publish and identify the same exact bytes that experiment config freezes.
    # A single byte-level digest avoids ambiguous semantic and file hashes.
    bundle_bytes = _pretty_json_bytes(selected_bundle)
    bundle_sha256 = _sha256(bundle_bytes)
    _atomic_write_bytes(target / "bundle.json", bundle_bytes)
    (target / "CandidateAgent.template.java").write_text(
        str(selected_bundle["java_template"]),
        encoding="utf-8",
    )
    (target / "slot_generation_prompt.txt").write_text(
        str(selected_bundle["slot_generation_prompt"]).rstrip() + "\n",
        encoding="utf-8",
    )
    _write_json(target / "report.json", selected_bundle["report"])
    bootstrap_record = {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "status": "success",
        "provider": "gemini",
        "model": model_name,
        "endpoint": endpoint,
        "max_attempts": max_attempts,
        "selected_attempt": selected_attempt,
        "selected_attempt_artifact": f"attempts/attempt_{selected_attempt:03d}",
        "started_at": overall_started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "request_sha256": request_sha256,
        "response_sha256": selected_response_sha256,
        "bundle_sha256": bundle_sha256,
        "framework_id": selected_bundle["framework_id"],
        "attempts": attempt_summaries,
        "error": None,
    }
    _write_json(target / "bootstrap.json", bootstrap_record)
    return GeminiFrameworkResult(
        output_dir=target,
        bundle_path=target / "bundle.json",
        bootstrap_path=target / "bootstrap.json",
        bundle=selected_bundle,
    )


def parse_gemini_framework_response(raw_response: bytes | str) -> dict[str, object]:
    """Parse a Gemini provider envelope and validate its framework JSON text."""

    source = (
        raw_response.decode("utf-8")
        if isinstance(raw_response, bytes)
        else str(raw_response)
    )
    envelope = json.loads(source)
    if not isinstance(envelope, dict):
        raise ValueError("Gemini response envelope must be an object.")
    candidates = envelope.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("Gemini response must contain exactly one candidate.")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ValueError("Gemini candidate must be an object.")
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ValueError("Gemini candidate content must be an object.")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("Gemini candidate content must contain text parts.")
    text_parts: list[str] = []
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("text"), str):
            raise ValueError("Gemini structured response parts must contain text.")
        text_parts.append(part["text"])
    generated = json.loads("".join(text_parts))
    if not isinstance(generated, dict):
        raise ValueError("Gemini framework content must be one JSON object.")
    bundle = validate_framework_bundle(generated)
    _validate_generated_java_template(bundle)
    return bundle.to_json_dict()


def _validate_generated_java_template(bundle: FrameworkBundle) -> None:
    """Apply Gemini-bootstrap source-envelope checks beyond the generic bundle schema."""

    source = bundle.java_template
    if source.count("package ai.generated;") != 1:
        raise ValueError("java_template must declare package ai.generated exactly once.")
    if not re.search(
        r"\bpublic\s+final\s+class\s+CandidateAgent\s+extends\s+AbstractionLayerAI\b",
        source,
    ):
        raise ValueError(
            "java_template must define public final CandidateAgent extending "
            "AbstractionLayerAI."
        )
    strategy_start = "// EAGLE_AGENT_STRATEGY_START"
    strategy_end = "// EAGLE_AGENT_STRATEGY_END"
    if source.count(strategy_start) != 1 or source.count(strategy_end) != 1:
        raise ValueError("java_template requires exactly one strategy marker pair.")
    start_index = source.index(strategy_start)
    end_index = source.index(strategy_end)
    if start_index >= end_index:
        raise ValueError("java_template strategy markers are out of order.")
    for slot in bundle.slots:
        marker_index = source.index(slot.marker)
        if not start_index < marker_index < end_index:
            raise ValueError(f"Slot marker must be inside the strategy region: {slot.marker}")


def _request_payload(
    prompt: str,
    *,
    temperature: float,
    max_output_tokens: int,
) -> dict[str, object]:
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "candidateCount": 1,
            "maxOutputTokens": max_output_tokens,
            "responseFormat": {
                "text": {
                    "mimeType": "application/json",
                    "schema": FRAMEWORK_RESPONSE_SCHEMA,
                }
            },
        },
    }


def _validate_settings(
    *,
    model: str,
    design_brief: str,
    temperature: float,
    max_output_tokens: int,
    max_attempts: int,
    timeout_seconds: float,
    api_root: str,
) -> None:
    model_name = model.removeprefix("models/")
    if not model_name or not re.fullmatch(r"[A-Za-z0-9._-]+", model_name):
        raise ValueError("Gemini model must be a non-empty model identifier.")
    if not design_brief.strip():
        raise ValueError("Framework design brief must not be empty.")
    if not math.isfinite(temperature) or temperature < 0:
        raise ValueError("temperature must be finite and non-negative.")
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive.")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive.")
    parsed = urllib.parse.urlparse(api_root)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Gemini api_root must be a valid HTTPS URL.")


def _prepare_output_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Framework output is not a directory: {path}")
        if any(path.iterdir()):
            raise ValueError(f"Framework output directory is not empty: {path}")
    else:
        path.mkdir(parents=True)


def _redact(value: str | None, secret: str) -> str | None:
    if value is None:
        return None
    return value.replace(secret, "[REDACTED]") if secret else value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(path, _pretty_json_bytes(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
