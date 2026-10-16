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
from eagle.generation.groq_framework import (
    ATTEMPT_SCHEMA_VERSION,
    BOOTSTRAP_SCHEMA_VERSION,
    DEFAULT_GROQ_MODEL,
    DEFAULT_MAX_OUTPUT_TOKENS,
    FRAMEWORK_RESPONSE_SCHEMA,
    FRAMEWORK_SCHEMA_VERSION,
    GROQ_FRAMEWORK_INPUT_TOKEN_RESERVE,
    GROQ_REASONING_EFFORT,
    GROQ_USER_AGENT,
    GroqFrameworkError,
    generate_framework_bundle,
    parse_groq_framework_response,
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


def _provider_response(
    bundle: dict[str, object] | None = None,
    usage: dict[str, object] | None = None,
) -> bytes:
    content = json.dumps(_bundle() if bundle is None else bundle, ensure_ascii=False)
    payload = {
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        payload["usage"] = usage
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class GroqFrameworkTests(unittest.TestCase):
    def test_local_backend_uses_openai_compatible_json_object_mode_without_api_key(self) -> None:
        captured_requests = []

        def transport(request, timeout):
            captured_requests.append((request, timeout))
            payload = json.loads(_provider_response())
            payload["choices"][0]["finish_reason"] = "length"
            return _Response(json.dumps(payload).encode("utf-8"))

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=transport,
        ):
            result = generate_framework_bundle(
                Path(directory) / "framework",
                model="qwen3_5_9b",
                design_brief="Build a bounded local framework.",
                max_attempts=1,
                timeout_seconds=12.0,
                max_output_tokens=4096,
                request_interval_seconds=0.0,
                api_root="http://127.0.0.1:18080/v1",
                provider="local",
                require_api_key=False,
                require_https=False,
                json_object_mode=False,
                reasoning_effort=None,
                chat_template_kwargs={"enable_thinking": False},
            )

            request, timeout = captured_requests[0]
            self.assertEqual(timeout, 12.0)
            self.assertEqual(request.full_url, "http://127.0.0.1:18080/v1/chat/completions")
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertNotIn("authorization", headers)
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["model"], "qwen3_5_9b")
            self.assertEqual(payload["response_format"]["type"], "json_schema")
            self.assertNotIn("reasoning_effort", payload)
            self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
            bootstrap = json.loads(result.bootstrap_path.read_text(encoding="utf-8"))
            self.assertEqual(bootstrap["provider"], "local")
            attempt = json.loads(
                (result.output_dir / "attempts/attempt_001/result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(attempt["finish_reason"], "length")

    def test_bootstrap_persists_schema_artifacts_hashes_and_no_secret(self) -> None:
        secret = "test-api-key-that-must-not-be-persisted"
        captured_requests = []

        def transport(request, timeout):
            captured_requests.append((request, timeout))
            return _Response(_provider_response())

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": secret}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=transport,
        ):
            output = Path(directory) / "framework"
            result = generate_framework_bundle(
                output,
                model="openai/gpt-oss-120b",
                design_brief="Build a bounded economy and combat controller.",
                max_attempts=2,
                timeout_seconds=12.0,
                temperature=0.3,
                max_output_tokens=4096,
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
                "https://api.groq.com/openai/v1/chat/completions",
            )
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers["authorization"], f"Bearer {secret}")
            self.assertEqual(headers["accept"], "application/json")
            self.assertEqual(headers["user-agent"], GROQ_USER_AGENT)
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(bootstrap["schema_version"], BOOTSTRAP_SCHEMA_VERSION)
            self.assertEqual(payload["model"], "openai/gpt-oss-120b")
            self.assertEqual(payload["temperature"], 0.3)
            self.assertEqual(payload["max_completion_tokens"], 4096)
            self.assertEqual(payload["reasoning_effort"], GROQ_REASONING_EFFORT)
            self.assertEqual(payload["response_format"]["type"], "json_schema")
            self.assertEqual(bootstrap["provider"], "groq")
            self.assertEqual(payload["messages"][0]["role"], "user")
            self.assertIn("Build a bounded economy and combat controller.", payload["messages"][0]["content"])
            schema_format = payload["response_format"]["json_schema"]
            self.assertEqual(schema_format["name"], "eagle_framework")
            self.assertFalse(schema_format["strict"])
            self.assertEqual(schema_format["schema"], FRAMEWORK_RESPONSE_SCHEMA)
            attempt = json.loads((output / "attempts" / "attempt_001" / "result.json").read_text())
            self.assertEqual(attempt["schema_version"], ATTEMPT_SCHEMA_VERSION)

            persisted = b"\n".join(
                path.read_bytes() for path in output.rglob("*") if path.is_file()
            )
            self.assertNotIn(secret.encode("utf-8"), persisted)

    def test_invalid_first_response_is_retained_before_retry(self) -> None:
        responses = [
            _Response(b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"not json"}}]}'),
            _Response(_provider_response()),
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=responses,
        ):
            output = Path(directory) / "framework"
            result = generate_framework_bundle(
                output,
                model="openai/gpt-oss-120b",
                design_brief="Build a framework.",
                max_attempts=2,
                request_interval_seconds=0,
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

    def test_validation_retry_receives_error_feedback(self) -> None:
        invalid = _bundle()
        invalid["slots"] = [
            {**invalid["slots"][0], "marker": "{{EAGLE_SLOT:worker_target}"},
            *invalid["slots"][1:],
        ]
        requests = []

        def transport(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return _Response(
                _provider_response(invalid if len(requests) == 1 else _bundle())
            )

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=transport,
        ):
            result = generate_framework_bundle(
                Path(directory) / "framework",
                design_brief="Build a framework.",
                max_attempts=2,
                request_interval_seconds=0,
            )

        self.assertEqual(result.bundle, _bundle())
        self.assertEqual(len(requests), 2)
        self.assertNotEqual(
            requests[0]["messages"][0]["content"],
            requests[1]["messages"][0]["content"],
        )
        self.assertIn("canonical marker", requests[1]["messages"][0]["content"])

    def test_token_usage_enforces_rolling_window_before_retry(self) -> None:
        responses = [
            _Response(
                b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"not json"}}],"usage":{"total_tokens":9000}}'
            ),
            _Response(_provider_response()),
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=responses,
        ), patch("eagle.generation.groq_framework.time.sleep") as sleep:
            result = generate_framework_bundle(
                Path(directory) / "framework",
                design_brief="Build a framework.",
                max_attempts=2,
                request_interval_seconds=0,
            )

        self.assertEqual(result.bundle, _bundle())
        sleep.assert_called_once()
        self.assertGreaterEqual(sleep.call_args.args[0], 59.0)

    def test_exhaustion_keeps_raw_attempts_and_failure_summary(self) -> None:
        raw = b'{"choices":[]}'
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            return_value=_Response(raw),
        ):
            output = Path(directory) / "framework"
            with self.assertRaisesRegex(GroqFrameworkError, "after 2 attempt"):
                generate_framework_bundle(
                    output,
                    model="openai/gpt-oss-120b",
                    design_brief="Build a framework.",
                    max_attempts=2,
                    request_interval_seconds=0,
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
            "Bad Request: secret",
            {},
            io.BytesIO(raw),
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=http_error,
        ):
            output = Path(directory) / "framework"
            with self.assertRaisesRegex(
                GroqFrameworkError,
                "Invalid structured-output field value",
            ) as caught:
                generate_framework_bundle(
                    output,
                    model="openai/gpt-oss-120b",
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
            self.assertNotIn("secret", result["error"])
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(len(list(output.joinpath("attempts").iterdir())), 1)

    def test_json_schema_failure_retries_in_json_object_mode(self) -> None:
        raw = json.dumps(
            {
                "error": {
                    "message": "Failed to generate JSON.",
                    "code": "json_validate_failed",
                    "failed_generation": "{\"schema_version\":\"eagle-framework-bundle-v1\"}",
                }
            }
        ).encode("utf-8")
        schema_failure = urllib.error.HTTPError(
            "https://example.invalid",
            400,
            "Bad Request",
            {},
            io.BytesIO(raw),
        )
        requests = []

        def transport(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            if len(requests) == 1:
                raise schema_failure
            return _Response(_provider_response())

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=transport,
        ):
            output = Path(directory) / "framework"
            result = generate_framework_bundle(
                output,
                design_brief="Build a framework.",
                max_attempts=2,
                request_interval_seconds=0,
            )
            first_result = json.loads(
                (output / "attempts/attempt_001/result.json").read_text()
            )
            first_raw = (output / "attempts/attempt_001/response_raw.json").read_bytes()

        self.assertEqual(result.bundle, _bundle())
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["response_format"]["type"], "json_schema")
        self.assertEqual(requests[1]["response_format"], {"type": "json_object"})
        self.assertIn("JSON Object Mode", requests[1]["messages"][0]["content"])
        self.assertTrue(first_result["retryable"])
        self.assertEqual(first_raw, raw)

    def test_parser_rejects_malformed_groq_envelopes(self) -> None:
        valid_message = {"role": "assistant", "content": json.dumps(_bundle())}
        malformed = (
            ([], "envelope must be an object"),
            ({}, "exactly one choice"),
            ({"choices": [None]}, "finish with stop"),
            ({"choices": [{"finish_reason": "stop"}]}, "message must be an object"),
            ({"choices": [{"finish_reason": "stop", "message": valid_message}, {"finish_reason": "stop", "message": valid_message}]}, "exactly one choice"),
            ({"choices": [{"finish_reason": "length", "message": valid_message}]}, "finish with stop"),
            ({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "refusal": "no", "content": "{}"}}]}, "refused"),
            ({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": None}}]}, "JSON text"),
        )
        for payload, message in malformed:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_groq_framework_response(json.dumps(payload))

    def test_cli_uses_default_model_and_allows_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=[_Response(_provider_response()), _Response(_provider_response())],
        ) as urlopen:
            for name, extra in (("default", []), ("override", ["--model", "org/model-x"])):
                output = Path(directory) / name
                self.assertEqual(eagle_main(["framework", "--output", str(output), "--brief", "Build a framework.", *extra]), 0)
            payloads = [json.loads(call.args[0].data) for call in urlopen.call_args_list]
            self.assertEqual(payloads[0]["model"], DEFAULT_GROQ_MODEL)
            self.assertEqual(payloads[1]["model"], "org/model-x")
            self.assertEqual(payloads[0]["max_completion_tokens"], DEFAULT_MAX_OUTPUT_TOKENS)
            self.assertLessEqual(
                payloads[0]["max_completion_tokens"] + GROQ_FRAMEWORK_INPUT_TOKEN_RESERVE,
                8_000,
            )

    def test_transient_429_retries_then_succeeds(self) -> None:
        rate_limited = urllib.error.HTTPError(
            "https://api.groq.com/openai/v1/chat/completions", 429,
            "Too Many Requests", {"Retry-After": "0"},
            io.BytesIO(b'{"error":{"message":"rate limited"}}'),
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=[rate_limited, _Response(_provider_response())],
        ):
            result = generate_framework_bundle(
                Path(directory) / "framework",
                design_brief="Build a framework.",
                max_attempts=2,
                request_interval_seconds=0,
            )
            self.assertEqual(result.bundle, _bundle())
            first = json.loads((result.bundle_path.parent / "attempts/attempt_001/result.json").read_text())
            self.assertTrue(first["retryable"])

    def test_429_waits_for_provider_retry_after_before_retry(self) -> None:
        rate_limited = urllib.error.HTTPError(
            "https://api.groq.com/openai/v1/chat/completions",
            429,
            "Too Many Requests",
            {"Retry-After": "12.5"},
            io.BytesIO(b'{"error":{"message":"rate limited"}}'),
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            side_effect=[rate_limited, _Response(_provider_response())],
        ), patch("eagle.generation.groq_framework.time.sleep") as sleep:
            result = generate_framework_bundle(
                Path(directory) / "framework",
                design_brief="Build a framework.",
                max_attempts=2,
            )

        self.assertEqual(result.bundle, _bundle())
        sleep.assert_called_once()
        self.assertGreaterEqual(sleep.call_args.args[0], 59.0)

    def test_bundle_validation_rejects_marker_mismatch(self) -> None:
        bundle = _bundle()
        slots = list(bundle["slots"])
        slots[0] = {**slots[0], "marker": "{{EAGLE_SLOT:not_worker_target}}"}
        bundle["slots"] = slots
        with self.assertRaisesRegex(ValueError, "canonical marker"):
            parse_groq_framework_response(_provider_response(bundle))

    def test_missing_api_key_fails_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {}, clear=True
        ):
            output = Path(directory) / "framework"
            with self.assertRaisesRegex(GroqFrameworkError, "GROQ_API_KEY"):
                generate_framework_bundle(
                    output,
                    model="openai/gpt-oss-120b",
                    design_brief="Build a framework.",
                )
            self.assertFalse(output.exists())

    def test_framework_command_is_dispatched(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GROQ_API_KEY": "secret"}, clear=True
        ), patch(
            "eagle.generation.groq_framework.urllib.request.urlopen",
            return_value=_Response(_provider_response()),
        ):
            output = Path(directory) / "framework"
            status = eagle_main(
                [
                    "framework",
                    "--output",
                    str(output),
                    "--model",
                    "openai/gpt-oss-120b",
                    "--brief",
                    "Build a framework.",
                ]
            )
            self.assertEqual(status, 0)
            self.assertTrue((output / "bundle.json").is_file())


if __name__ == "__main__":
    unittest.main()
