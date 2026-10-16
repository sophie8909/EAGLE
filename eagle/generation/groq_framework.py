"""One-shot framework bootstrap for an immutable, slot-controlled Java framework.

This module intentionally stops at framework-bundle creation. Evolutionary
configuration, candidate state, and Java materialization consume the bundle in
separate layers. The Groq backend reads authentication only from
``GROQ_API_KEY``; the local backend sends no authorization header. Secrets are
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
BOOTSTRAP_SCHEMA_VERSION = "eagle-groq-framework-bootstrap-v1"
ATTEMPT_SCHEMA_VERSION = "eagle-groq-framework-attempt-v1"
DEFAULT_GROQ_API_ROOT = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LOCAL_FRAMEWORK_MAX_OUTPUT_TOKENS = 12_288
# Conservative defaults for Groq's free-plan limits.  Framework bootstrap is
# intentionally serialized: a complete framework response is large enough
# that a second request inside the same rolling minute can exhaust TPM even
# when the request count is far below RPM.
GROQ_FREE_REQUESTS_PER_MINUTE = 30
GROQ_FREE_REQUESTS_PER_DAY = 1_000
GROQ_FREE_TOKENS_PER_MINUTE = 8_000
GROQ_FREE_TOKENS_PER_DAY = 200_000
GROQ_RATE_WINDOW_SECONDS = 60.0
DEFAULT_GROQ_REQUEST_INTERVAL_SECONDS = GROQ_RATE_WINDOW_SECONDS
# The provider's TPM accounting includes the rendered input prompt.  The
# current bootstrap prompt uses about 1,442 tokens, so reserve 1,600 tokens
# and keep the default request below Groq's 8,000-token entry-tier ceiling.
GROQ_FRAMEWORK_INPUT_TOKEN_RESERVE = 1_600
DEFAULT_MAX_OUTPUT_TOKENS = (
    GROQ_FREE_TOKENS_PER_MINUTE - GROQ_FRAMEWORK_INPUT_TOKEN_RESERVE
)
GROQ_USER_AGENT = "EAGLE/1.0"
GROQ_REASONING_EFFORT = "low"

FRAMEWORK_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {
            "type": "string",
            "enum": [FRAMEWORK_SCHEMA_VERSION],
        },
        "framework_id": {
            "type": "string",
            "pattern": r"^[a-z][a-z0-9_-]{0,127}$",
        },
        "java_template": {"type": "string"},
        "slots": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "slot_id": {
                        "type": "string",
                        "pattern": r"^[a-z][a-z0-9_]{0,63}$",
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(SLOT_KINDS),
                    },
                    "marker": {
                        "type": "string",
                        "pattern": r"^\{\{EAGLE_SLOT:[a-z][a-z0-9_]{0,63}\}\}$",
                    },
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
                                "choice_id": {
                                    "type": "string",
                                    "pattern": r"^[a-z][a-z0-9_]{0,63}$",
                                },
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


class GroqFrameworkError(RuntimeError):
    """The bounded framework bootstrap did not produce a valid bundle."""


@dataclass(frozen=True)
class GroqFrameworkResult:
    """Published framework bundle and its compact bootstrap record."""

    output_dir: Path
    bundle_path: Path
    bootstrap_path: Path
    bundle: dict[str, object]


@dataclass(frozen=True)
class _GroqRateSample:
    started_monotonic: float
    total_tokens: int


def _rate_limit_not_before(
    samples: list[_GroqRateSample],
    *,
    now: float,
    minimum_interval_seconds: float,
) -> float:
    """Return the earliest safe time for the next Groq request."""

    minute_samples = [
        sample
        for sample in samples
        if now - sample.started_monotonic < GROQ_RATE_WINDOW_SECONDS
    ]
    day_samples = [
        sample
        for sample in samples
        if now - sample.started_monotonic < 86_400.0
    ]
    not_before = now + minimum_interval_seconds if samples else now
    if len(minute_samples) >= GROQ_FREE_REQUESTS_PER_MINUTE:
        not_before = max(
            not_before,
            min(sample.started_monotonic for sample in minute_samples)
            + GROQ_RATE_WINDOW_SECONDS,
        )
    minute_tokens = sum(sample.total_tokens for sample in minute_samples)
    if minute_tokens >= GROQ_FREE_TOKENS_PER_MINUTE:
        not_before = max(
            not_before,
            min(sample.started_monotonic for sample in minute_samples)
            + GROQ_RATE_WINDOW_SECONDS,
        )
    day_tokens = sum(sample.total_tokens for sample in day_samples)
    if len(day_samples) >= GROQ_FREE_REQUESTS_PER_DAY:
        not_before = max(
            not_before,
            min(sample.started_monotonic for sample in day_samples) + 86_400.0,
        )
    if day_tokens >= GROQ_FREE_TOKENS_PER_DAY:
        not_before = max(
            not_before,
            min(sample.started_monotonic for sample in day_samples) + 86_400.0,
        )
    return not_before


def _response_total_tokens(raw_response: bytes) -> int | None:
    """Read provider usage for local rate accounting without trusting it for validation."""

    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    usage = payload.get("usage") if isinstance(payload, dict) else None
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    if isinstance(total_tokens, int) and not isinstance(total_tokens, bool) and total_tokens >= 0:
        return total_tokens
    return None


def generate_framework_bundle(
    output_dir: str | Path,
    *,
    model: str = DEFAULT_GROQ_MODEL,
    design_brief: str,
    temperature: float = 0.2,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    request_interval_seconds: float = DEFAULT_GROQ_REQUEST_INTERVAL_SECONDS,
    api_root: str = DEFAULT_GROQ_API_ROOT,
    provider: str = "groq",
    require_api_key: bool = True,
    require_https: bool = True,
    json_object_mode: bool = False,
    reasoning_effort: str | None = GROQ_REASONING_EFFORT,
    chat_template_kwargs: dict[str, object] | None = None,
) -> GroqFrameworkResult:
    """Call a compatible framework provider and publish one validated bundle.

    Every attempt owns its exact credential-free request body, raw HTTP body,
    timing, hashes, and result.  The raw body is flushed to disk before any
    provider-envelope or generated-content parsing occurs.
    """

    target = Path(output_dir).expanduser().resolve()
    provider = provider.strip().lower()
    if provider not in {"groq", "local"}:
        raise ValueError("framework provider must be groq or local.")
    provider_label = "Groq" if provider == "groq" else "local LLM"
    _validate_settings(
        model=model,
        design_brief=design_brief,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        request_interval_seconds=request_interval_seconds,
        api_root=api_root,
        require_https=require_https,
    )
    api_key = os.environ.get("GROQ_API_KEY", "") if require_api_key else ""
    if require_api_key and not api_key.strip():
        raise GroqFrameworkError("GROQ_API_KEY is required for framework generation.")
    _prepare_output_directory(target)

    prompt = render_prompt(
        "groq_framework_design",
        {
            "design_brief": design_brief.strip(),
            "gameplay_contract": load_prompt("microrts_gameplay_contract"),
            "action_api_guide": load_prompt("action_api_guide"),
        },
    )
    endpoint = api_root.rstrip("/") + "/chat/completions"
    (target / "prompt.txt").write_text(prompt, encoding="utf-8")
    attempts_root = target / "attempts"
    attempts_root.mkdir()

    overall_started_at = _utc_now()
    overall_started = time.monotonic()
    selected_attempt: int | None = None
    selected_bundle: dict[str, object] | None = None
    selected_response_sha256: str | None = None
    last_error = f"{provider_label} returned no response."
    last_validation_error: str | None = None
    request_sha256 = ""
    attempt_summaries: list[dict[str, object]] = []
    next_request_not_before: float | None = None
    rate_samples: list[_GroqRateSample] = []
    json_object_fallback = json_object_mode

    for attempt in range(1, max_attempts + 1):
        now = time.monotonic()
        rate_limit_not_before = _rate_limit_not_before(
            rate_samples,
            now=now,
            minimum_interval_seconds=request_interval_seconds,
        )
        if next_request_not_before is not None:
            rate_limit_not_before = max(rate_limit_not_before, next_request_not_before)
        wait_seconds = rate_limit_not_before - now
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        attempt_prompt = _retry_prompt(
            prompt,
            last_validation_error,
            json_object_mode=json_object_fallback,
        )
        request_payload = _request_payload(
            attempt_prompt,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            json_object_mode=json_object_fallback,
            reasoning_effort=reasoning_effort,
            chat_template_kwargs=chat_template_kwargs,
        )
        request_bytes = json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request_sha256 = _sha256(request_bytes)
        attempt_dir = attempts_root / f"attempt_{attempt:03d}"
        attempt_dir.mkdir()
        (attempt_dir / "request.json").write_bytes(request_bytes)
        raw_path = attempt_dir / "response_raw.json"
        raw_path.write_bytes(b"")
        started_at = _utc_now()
        started = time.monotonic()
        next_request_not_before = started + request_interval_seconds
        status = "failed"
        error: str | None = None
        http_status: int | None = None
        raw_response = b""
        retryable = True
        retry_delay_seconds = 0.0
        bundle: dict[str, object] | None = None
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": GROQ_USER_AGENT,
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            request = urllib.request.Request(
                endpoint,
                data=request_bytes,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                http_status = int(getattr(response, "status", 200))
                raw_response = response.read()
            raw_path.write_bytes(raw_response)
            bundle = parse_framework_response(
                raw_response,
                provider_label=provider_label,
                allow_length_finish=provider == "local",
            )
            status = "success"
            retryable = False
        except urllib.error.HTTPError as exc:
            http_status = int(exc.code)
            raw_response = exc.read()
            raw_path.write_bytes(raw_response)
            error = _http_error_summary(exc, raw_response, provider_label=provider_label)
            json_validation_failure = _provider_error_code(raw_response) == "json_validate_failed"
            retryable = (
                json_validation_failure
                or exc.code in {408, 409, 429}
                or 500 <= exc.code <= 599
            )
            if json_validation_failure:
                # The provider's best-effort JSON Schema mode can reject a valid-looking
                # partial generation before the response reaches local parsing.
                # Retry in JSON Object Mode; local bundle validation remains
                # authoritative and the failed constrained request is retained.
                json_object_fallback = True
            if retryable:
                retry_delay_seconds = _retry_delay_seconds(
                    exc,
                    raw_response,
                    attempt=attempt,
                    maximum=timeout_seconds,
                )
        except (urllib.error.URLError, TimeoutError) as exc:
            error = f"{provider_label} API request failed: {exc}"
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            error = f"{provider_label} response validation failed: {exc}"
            last_validation_error = error
        except OSError as exc:
            error = f"{provider_label} framework artifact failure: {exc}"
            retryable = False

        finished_at = _utc_now()
        duration_seconds = max(0.0, time.monotonic() - started)
        total_tokens = _response_total_tokens(raw_response)
        rate_samples.append(_GroqRateSample(started, total_tokens or 0))
        response_sha256 = _sha256(raw_response)
        safe_error = _redact(error, api_key)
        attempt_record = {
            "schema_version": ATTEMPT_SCHEMA_VERSION,
            "attempt": attempt,
            "status": status,
            "retryable": retryable,
            "error": safe_error,
            "provider": provider,
            "model": model,
            "endpoint": endpoint,
            "http_status": http_status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "finish_reason": _response_finish_reason(raw_response),
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
                "finish_reason": _response_finish_reason(raw_response),
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
        if attempt < max_attempts and retry_delay_seconds > 0:
            next_request_not_before = max(
                next_request_not_before,
                time.monotonic() + retry_delay_seconds,
            )

    finished_at = _utc_now()
    duration_seconds = max(0.0, time.monotonic() - overall_started)
    if selected_bundle is None or selected_attempt is None:
        failure_record = {
            "schema_version": BOOTSTRAP_SCHEMA_VERSION,
            "status": "failed",
            "provider": provider,
            "model": model,
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
        raise GroqFrameworkError(
            f"{provider_label} framework generation failed after {len(attempt_summaries)} attempt(s): "
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
        "provider": provider,
        "model": model,
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
    return GroqFrameworkResult(
        output_dir=target,
        bundle_path=target / "bundle.json",
        bootstrap_path=target / "bootstrap.json",
        bundle=selected_bundle,
    )


def parse_groq_framework_response(raw_response: bytes | str) -> dict[str, object]:
    """Parse a Groq provider envelope and validate its framework JSON text."""

    return parse_framework_response(raw_response, provider_label="Groq")


def parse_framework_response(
    raw_response: bytes | str,
    *,
    provider_label: str = "Groq",
    allow_length_finish: bool = False,
) -> dict[str, object]:
    """Parse an OpenAI-compatible provider envelope and validate its framework JSON."""

    source = (
        raw_response.decode("utf-8")
        if isinstance(raw_response, bytes)
        else str(raw_response)
    )
    envelope = json.loads(source)
    if not isinstance(envelope, dict):
        raise ValueError(f"{provider_label} response envelope must be an object.")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError(f"{provider_label} response must contain exactly one choice.")
    choice = choices[0]
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    accepted_finish_reasons = {"stop"}
    if allow_length_finish:
        accepted_finish_reasons.add("length")
    if not isinstance(choice, dict) or finish_reason not in accepted_finish_reasons:
        raise ValueError(f"{provider_label} response must finish with stop; incomplete output is rejected.")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError(f"{provider_label} choice message must be an object.")
    if message.get("refusal"):
        raise ValueError(f"{provider_label} refused framework generation.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"{provider_label} structured response must contain JSON text.")
    generated = json.loads(content)
    if not isinstance(generated, dict):
        raise ValueError(f"{provider_label} framework content must be one JSON object.")
    bundle = validate_framework_bundle(generated)
    _validate_generated_java_template(bundle)
    return bundle.to_json_dict()


def _response_finish_reason(raw_response: bytes) -> str | None:
    """Return the provider finish reason for durable attempt diagnostics."""

    try:
        envelope = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    choices = envelope.get("choices") if isinstance(envelope, dict) else None
    if not isinstance(choices, list) or len(choices) != 1:
        return None
    choice = choices[0]
    reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    return reason if isinstance(reason, str) else None


def _validate_generated_java_template(bundle: FrameworkBundle) -> None:
    """Apply bootstrap source-envelope checks beyond the generic bundle schema."""

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
    model: str,
    temperature: float,
    max_output_tokens: int,
    json_object_mode: bool = False,
    reasoning_effort: str | None = GROQ_REASONING_EFFORT,
    chat_template_kwargs: dict[str, object] | None = None,
) -> dict[str, object]:
    response_format: dict[str, object]
    if json_object_mode:
        response_format = {"type": "json_object"}
    else:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "eagle_framework",
                # Dynamic slot_rationale keys require best-effort schema mode.
                "strict": False,
                "schema": FRAMEWORK_RESPONSE_SCHEMA,
            },
        }
    payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_completion_tokens": max_output_tokens,
        "response_format": response_format,
    }
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    if chat_template_kwargs is not None:
        payload["chat_template_kwargs"] = dict(chat_template_kwargs)
    return payload


def _retry_prompt(
    base_prompt: str,
    validation_error: str | None,
    *,
    json_object_mode: bool = False,
) -> str:
    """Give a bounded retry local validation feedback without weakening checks."""

    if not validation_error and not json_object_mode:
        return base_prompt
    retry_instructions = [
        "Return exactly one syntactically valid JSON object with the complete framework bundle.",
        "Do not use Markdown fences, prose, or partial output.",
    ]
    if validation_error:
        retry_instructions.extend(
            [
                "A previous complete response was rejected by the local validator.",
                f"The exact validation error was: {validation_error}",
            ]
        )
    if json_object_mode:
        retry_instructions.append(
            "This retry uses JSON Object Mode. Local validation will enforce every bundle field and slot constraint."
        )
    retry_instructions.append(
        "Pay special attention to exact lowercase snake_case IDs and literal slot markers with two closing braces: "
        "{{EAGLE_SLOT:example_slot}}."
    )
    return f"{base_prompt}\n\n" + " ".join(retry_instructions)


def _provider_error_code(raw_response: bytes) -> str | None:
    """Return the provider's machine-readable error code, if present."""

    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def _http_error_summary(
    exc: urllib.error.HTTPError,
    raw_response: bytes,
    *,
    provider_label: str = "Groq",
) -> str:
    """Return a bounded provider diagnostic without replacing the raw artifact."""

    prefix = f"{provider_label} API HTTP {exc.code}: {exc.reason}"
    try:
        payload = json.loads(raw_response.decode("utf-8"))
        provider_error = payload.get("error") if isinstance(payload, dict) else None
        message = provider_error.get("message") if isinstance(provider_error, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        message = None
    if not isinstance(message, str) or not message.strip():
        return prefix
    compact_message = " ".join(message.split())[:1000]
    return f"{prefix}: {compact_message}"


def _retry_delay_seconds(
    exc: urllib.error.HTTPError,
    raw_response: bytes,
    *,
    attempt: int,
    maximum: float,
) -> float:
    """Respect Groq rate-limit guidance, with bounded transport backoff."""

    header_value = exc.headers.get("Retry-After") if exc.headers is not None else None
    candidates = [header_value]
    try:
        body = raw_response.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", body, re.IGNORECASE)
    candidates.append(match.group(1) if match is not None else None)
    for candidate in candidates:
        try:
            delay = float(candidate) if candidate is not None else -1.0
        except (TypeError, ValueError):
            continue
        if math.isfinite(delay) and delay >= 0:
            return min(maximum, delay + (0.25 if delay > 0 else 0.0))
    return min(maximum, float(2 ** min(max(0, attempt - 1), 4)))


def _validate_settings(
    *,
    model: str,
    design_brief: str,
    temperature: float,
    max_output_tokens: int,
    max_attempts: int,
    timeout_seconds: float,
    request_interval_seconds: float,
    api_root: str,
    require_https: bool,
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?", model):
        raise ValueError("Framework model must be a non-empty model identifier.")
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
    if not math.isfinite(request_interval_seconds) or request_interval_seconds < 0:
        raise ValueError("request_interval_seconds must be finite and non-negative.")
    parsed = urllib.parse.urlparse(api_root)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        scheme_label = "HTTPS" if require_https else "HTTP(S)"
        raise ValueError(f"Framework api_root must be a valid {scheme_label} URL.")


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
