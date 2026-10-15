from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from eagle.__main__ import main as eagle_main
from eagle.generation.gemini_framework import (
    FRAMEWORK_RESPONSE_SCHEMA,
    FRAMEWORK_SCHEMA_VERSION,
    GeminiFrameworkError,
    generate_framework_bundle,
    parse_gemini_framework_response,
)


class _Response:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


def _bundle() -> dict[str, object]:
    return {
        "schema_version": FRAMEWORK_SCHEMA_VERSION,
        "framework_id": "micro_control_1",
        "java_template": """package ai.generated;
public final class CandidateAgent extends AbstractionLayerAI {
    // EAGLE_AGENT_STRATEGY_START
    private static final int WORKER_TARGET = {{EAGLE_SLOT:worker_target}};
    private double score() { return {{EAGLE_SLOT:score_formula}}; }
    // EAGLE_AGENT_STRATEGY_END
}
""",
        "slots": [
            {
                "slot_id": "worker_target",
                "kind": "integer",
                "marker": "{{EAGLE_SLOT:worker_target}}",
                "default": 3,
                "minimum": 1,
                "maximum": 7,
                "step": 1,
                "choices": [],
                "purpose": "Control the desired worker count.",
            },
            {
                "slot_id": "score_formula",
                "kind": "expression_choice",
                "marker": "{{EAGLE_SLOT:score_formula}}",
                "default": "balanced",
                "minimum": None,
                "maximum": None,
                "step": None,
                "choices": [
                    {
                        "choice_id": "balanced",
                        "java_expression": "1.0",
                        "description": "Neutral score.",
                    },
                    {
                        "choice_id": "aggressive",
                        "java_expression": "2.0",
                        "description": "Prefer aggression.",
                    },
                ],
                "purpose": "Choose one fixed scoring formula.",
            },
        ],
        "slot_generation_prompt": "Return values for worker_target and score_formula only.",
        "report": {
            "architecture_summary": "One fixed controller with two typed controls.",
            "decision_flow": ["Observe", "Score", "Act"],
            "invariants": ["The framework never changes."],
            "slot_rationale": {
                "worker_target": "Controls force size.",
                "score_formula": "Controls target scoring.",
            },
            "assumptions": ["MicroRTS APIs are available."],
            "risks": ["The finite formulas may limit diversity."],
        },
    }


def _provider_response(bundle: dict[str, object] | None = None) -> bytes:
    content = json.dumps(_bundle() if bundle is None else bundle, ensure_ascii=False)
    return json.dumps(
        {"candidates": [{"content": {"role": "model", "parts": [{"text": content}]}}]},
        ensure_ascii=False,
    ).encode("utf-8")


class GeminiFrameworkTests(unittest.TestCase):
    def test_bootstrap_persists_schema_artifacts_hashes_and_no_secret(self) -> None:
        secret = "test-api-key-that-must-not-be-persisted"
        captured_requests = []

        def transport(request, timeout):
            captured_requests.append((request, timeout))
            return _Response(_provider_response())

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GEMINI_API_KEY": secret}, clear=True
        ), patch(
            "eagle.generation.gemini_framework.urllib.request.urlopen",
            side_effect=transport,
        ):
            output = Path(directory) / "framework"
            result = generate_framework_bundle(
                output,
                model="gemini-test",
                design_brief="Build a bounded economy and combat controller.",
                max_attempts=2,
                timeout_seconds=12.0,
            )

            self.assertEqual(result.bundle, _bundle())
            self.assertEqual(json.loads(result.bundle_path.read_text(encoding="utf-8")), _bundle())
            self.assertEqual(
                (output / "CandidateAgent.template.java").read_text(encoding="utf-8"),
                _bundle()["java_template"],
            )
            bootstrap = json.loads(result.bootstrap_path.read_text(encoding="utf-8"))
            self.assertEqual(bootstrap["status"], "success")
            self.assertEqual(bootstrap["selected_attempt"], 1)
            self.assertEqual(len(bootstrap["request_sha256"]), 64)
            self.assertEqual(len(bootstrap["response_sha256"]), 64)
            self.assertEqual(len(bootstrap["bundle_sha256"]), 64)
            self.assertEqual(
                bootstrap["bundle_sha256"],
                hashlib.sha256(result.bundle_path.read_bytes()).hexdigest(),
            )

            self.assertEqual(len(captured_requests), 1)
            request, timeout = captured_requests[0]
            self.assertEqual(timeout, 12.0)
            self.assertEqual(
                request.full_url,
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-test:generateContent",
            )
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers["x-goog-api-key"], secret)
            payload = json.loads(request.data.decode("utf-8"))
            text_format = payload["generationConfig"]["responseFormat"]["text"]
            self.assertEqual(text_format["mimeType"], "APPLICATION_JSON")
            self.assertEqual(text_format["schema"], FRAMEWORK_RESPONSE_SCHEMA)

            persisted = b"\n".join(
                path.read_bytes() for path in output.rglob("*") if path.is_file()
            )
            self.assertNotIn(secret.encode("utf-8"), persisted)

    def test_invalid_first_response_is_retained_before_retry(self) -> None:
        responses = [
            _Response(b'{"candidates":[{"content":{"parts":[{"text":"not json"}]}}]}'),
            _Response(_provider_response()),
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GEMINI_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.gemini_framework.urllib.request.urlopen",
            side_effect=responses,
        ):
            output = Path(directory) / "framework"
            result = generate_framework_bundle(
                output,
                model="gemini-test",
                design_brief="Build a framework.",
                max_attempts=2,
            )

            bootstrap = json.loads(result.bootstrap_path.read_text(encoding="utf-8"))
            self.assertEqual(bootstrap["selected_attempt"], 2)
            first = output / "attempts" / "attempt_001"
            self.assertEqual(
                first.joinpath("response_raw.json").read_bytes(), responses[0].payload
            )
            first_result = json.loads(first.joinpath("result.json").read_text(encoding="utf-8"))
            self.assertEqual(first_result["status"], "failed")
            self.assertTrue(first_result["retryable"])
            self.assertGreaterEqual(first_result["duration_seconds"], 0.0)
            self.assertEqual(len(first_result["request_sha256"]), 64)
            self.assertEqual(len(first_result["response_sha256"]), 64)

    def test_exhaustion_keeps_raw_attempts_and_failure_summary(self) -> None:
        raw = b'{"candidates":[]}'
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GEMINI_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.gemini_framework.urllib.request.urlopen",
            return_value=_Response(raw),
        ):
            output = Path(directory) / "framework"
            with self.assertRaisesRegex(GeminiFrameworkError, "after 2 attempt"):
                generate_framework_bundle(
                    output,
                    model="gemini-test",
                    design_brief="Build a framework.",
                    max_attempts=2,
                )
            self.assertFalse((output / "bundle.json").exists())
            self.assertEqual(
                (output / "attempts" / "attempt_001" / "response_raw.json").read_bytes(),
                raw,
            )
            failure = json.loads((output / "bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(len(failure["attempts"]), 2)

    def test_http_error_surfaces_provider_message_and_retains_raw_body(self) -> None:
        raw = json.dumps(
            {
                "error": {
                    "code": 400,
                    "message": "Invalid structured-output field value.",
                    "status": "INVALID_ARGUMENT",
                }
            }
        ).encode("utf-8")
        http_error = urllib.error.HTTPError(
            "https://example.invalid",
            400,
            "Bad Request",
            {},
            io.BytesIO(raw),
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GEMINI_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.gemini_framework.urllib.request.urlopen",
            side_effect=http_error,
        ):
            output = Path(directory) / "framework"
            with self.assertRaisesRegex(
                GeminiFrameworkError,
                "Invalid structured-output field value",
            ):
                generate_framework_bundle(
                    output,
                    model="gemini-test",
                    design_brief="Build a framework.",
                )

            self.assertEqual(
                output.joinpath("attempts/attempt_001/response_raw.json").read_bytes(),
                raw,
            )
            result = json.loads(
                output.joinpath("attempts/attempt_001/result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("Invalid structured-output field value", result["error"])

    def test_bundle_validation_rejects_marker_mismatch(self) -> None:
        bundle = _bundle()
        slots = list(bundle["slots"])
        slots[0] = {**slots[0], "marker": "{{EAGLE_SLOT:not_worker_target}}"}
        bundle["slots"] = slots
        with self.assertRaisesRegex(ValueError, "canonical marker"):
            parse_gemini_framework_response(_provider_response(bundle))

    def test_missing_api_key_fails_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {}, clear=True
        ):
            output = Path(directory) / "framework"
            with self.assertRaisesRegex(GeminiFrameworkError, "GEMINI_API_KEY"):
                generate_framework_bundle(
                    output,
                    model="gemini-test",
                    design_brief="Build a framework.",
                )
            self.assertFalse(output.exists())

    def test_framework_command_is_dispatched(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GEMINI_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.gemini_framework.urllib.request.urlopen",
            return_value=_Response(_provider_response()),
        ):
            output = Path(directory) / "framework"
            status = eagle_main(
                [
                    "framework",
                    "--output",
                    str(output),
                    "--model",
                    "gemini-test",
                    "--brief",
                    "Build a framework.",
                ]
            )
            self.assertEqual(status, 0)
            self.assertTrue((output / "bundle.json").is_file())


if __name__ == "__main__":
    unittest.main()
