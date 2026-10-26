"""One-shot Codex CLI bootstrap for an immutable Java framework bundle.

This transport deliberately performs one bounded ``codex exec`` invocation.
Callers decide whether and how to invoke a separate provider fallback.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from eagle.generation.groq_framework import (
    FRAMEWORK_RESPONSE_SCHEMA,
    validate_framework_bundle_payload,
)
from eagle.prompts import load_prompt, render_prompt


CODEX_BOOTSTRAP_SCHEMA_VERSION = "eagle-codex-framework-bootstrap-v1"
DEFAULT_CODEX_TIMEOUT_SECONDS = 300.0


class CodexFrameworkError(RuntimeError):
    """The single Codex bootstrap invocation did not produce a valid bundle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CodexFrameworkResult:
    """Published bundle plus the complete, credential-free Codex evidence."""

    output_dir: Path
    bundle_path: Path
    result_path: Path
    bundle: dict[str, object]


def generate_codex_framework_bundle(
    output_dir: str | Path,
    *,
    model: str,
    design_brief: str,
    timeout_seconds: float = DEFAULT_CODEX_TIMEOUT_SECONDS,
) -> CodexFrameworkResult:
    """Run one read-only Codex CLI generation and publish a validated bundle.

    Prompt, response schema, exact command metadata, and process output are
    persisted before the direct JSON response is trusted.  This function never
    invokes an API fallback; a caller may safely catch :class:`CodexFrameworkError`
    and use a distinct fresh output directory for that policy.
    """

    _validate_settings(model=model, design_brief=design_brief, timeout_seconds=timeout_seconds)
    target = Path(output_dir).expanduser().resolve()
    _prepare_output_directory(target)

    prompt = render_prompt(
        "groq_framework_design",
        {
            "design_brief": design_brief.strip(),
            "gameplay_contract": load_prompt("microrts_gameplay_contract"),
            "action_api_guide": load_prompt("action_api_guide"),
        },
    )
    schema_path = target / "response_schema.json"
    last_message_path = target / "last_message.txt"
    stdout_path = target / "stdout.txt"
    stderr_path = target / "stderr.txt"
    result_path = target / "result.json"
    (target / "prompt.txt").write_text(prompt, encoding="utf-8")
    _write_json(schema_path, FRAMEWORK_RESPONSE_SCHEMA)
    # Pre-create every response artifact so failure evidence is deterministic.
    last_message_path.write_text("", encoding="utf-8")
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")

    command = [
        "codex",
        "exec",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(last_message_path),
        "-",
    ]
    command_metadata = {
        "schema_version": CODEX_BOOTSTRAP_SCHEMA_VERSION,
        "argv": command,
        "stdin_artifact": "prompt.txt",
        "response_schema_artifact": "response_schema.json",
        "last_message_artifact": "last_message.txt",
        "stdout_artifact": "stdout.txt",
        "stderr_artifact": "stderr.txt",
    }
    _write_json(target / "command.json", command_metadata)

    started_at = _utc_now()
    started = time.monotonic()
    stdout = ""
    stderr = ""
    returncode: int | None = None
    error: str | None = None
    status = "failed"
    bundle: dict[str, object] | None = None
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        error = f"Codex CLI timed out after {timeout_seconds:g} seconds."
    except FileNotFoundError:
        error = "Codex CLI executable was not found."
    except OSError as exc:
        error = f"Codex CLI could not be started: {exc.__class__.__name__}."
    else:
        stdout = _as_text(completed.stdout)
        stderr = _as_text(completed.stderr)
        returncode = completed.returncode
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        if completed.returncode != 0:
            error = f"Codex CLI exited with status {completed.returncode}."
        else:
            message = last_message_path.read_text(encoding="utf-8")
            if not message.strip():
                error = "Codex CLI did not write a final message."
            else:
                try:
                    bundle = validate_framework_bundle_payload(json.loads(message))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    error = f"Codex framework response validation failed: {exc}"
                else:
                    status = "success"

    finished_at = _utc_now()
    duration_seconds = max(0.0, time.monotonic() - started)
    last_message = last_message_path.read_bytes()
    record = {
        "schema_version": CODEX_BOOTSTRAP_SCHEMA_VERSION,
        "status": status,
        "provider": "codex",
        "model": model,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "returncode": returncode,
        "prompt_sha256": _sha256(prompt.encode("utf-8")),
        "response_schema_sha256": _sha256(schema_path.read_bytes()),
        "last_message_sha256": _sha256(last_message),
        "stdout_sha256": _sha256(stdout.encode("utf-8")),
        "stderr_sha256": _sha256(stderr.encode("utf-8")),
        "bundle_sha256": None,
        "framework_id": None,
        "error": error,
    }
    if bundle is not None:
        bundle_bytes = _pretty_json_bytes(bundle)
        bundle_path = target / "bundle.json"
        _atomic_write_bytes(bundle_path, bundle_bytes)
        (target / "CandidateAgent.template.java").write_text(
            str(bundle["java_template"]), encoding="utf-8"
        )
        (target / "slot_generation_prompt.txt").write_text(
            str(bundle["slot_generation_prompt"]).rstrip() + "\n", encoding="utf-8"
        )
        _write_json(target / "report.json", bundle["report"])
        record["bundle_sha256"] = _sha256(bundle_bytes)
        record["framework_id"] = bundle["framework_id"]
    _write_json(result_path, record)

    if bundle is None:
        raise CodexFrameworkError(error or "Codex framework generation failed.")
    return CodexFrameworkResult(
        output_dir=target,
        bundle_path=target / "bundle.json",
        result_path=result_path,
        bundle=bundle,
    )


def _validate_settings(*, model: str, design_brief: str, timeout_seconds: float) -> None:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Codex framework model must be a non-empty string.")
    if not design_brief.strip():
        raise ValueError("Framework design brief must not be empty.")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive.")


def _prepare_output_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Framework output is not a directory: {path}")
        if any(path.iterdir()):
            raise ValueError(f"Framework output directory is not empty: {path}")
    else:
        path.mkdir(parents=True)


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(path, _pretty_json_bytes(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
