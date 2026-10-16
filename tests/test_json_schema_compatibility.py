from __future__ import annotations

import json
import unittest
from unittest.mock import call, patch

from eagle.evaluation.strategy_alignment import (
    OpenAICompatibleStrategyAlignmentBackend,
    STRATEGY_ALIGNMENT_RESPONSE_SCHEMA,
)
from eagle.generation.framework_slots import validate_framework_bundle
from eagle.llm import (
    GENERIC_JSON_OBJECT_SCHEMA,
    LLMClient,
    json_schema_response_format,
    parse_json_object_response,
)
from eagle.operators.framework_coach import framework_selection_response_schema
from eagle.operators.initialization import INITIAL_POLICY_RESPONSE_SCHEMA
from eagle.operators.reflection import OpenAICompatibleReflectionBackend
from eagle.strategy_dsl import STRATEGY_DSL_JSON_SCHEMA
from tests.test_framework_coach_integration import bundle_payload


class _Response:
    def __init__(self, content: str) -> None:
        self._payload = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def __iter__(self):
        yield self._payload


class JsonSchemaCompatibilityTests(unittest.TestCase):
    def test_builder_rejects_non_object_schemas_and_builds_lm_studio_envelope(self):
        with self.assertRaises(ValueError):
            json_schema_response_format({"type": "string"})

        self.assertEqual(
            json_schema_response_format(
                GENERIC_JSON_OBJECT_SCHEMA,
                name="eagle_reflection",
            ),
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "eagle_reflection",
                    "strict": False,
                    "schema": GENERIC_JSON_OBJECT_SCHEMA,
                },
            },
        )

    def test_reflection_request_uses_json_schema_for_lm_studio(self):
        backend = OpenAICompatibleReflectionBackend(
            "http://192.168.1.136:1234/v1",
            "qwen/qwen3.5-9b",
            operation="initial_policy_generation",
        )

        with patch(
            "eagle.operators.reflection.urllib.request.urlopen",
            return_value=_Response('{"ok":true}'),
        ) as transport:
            self.assertEqual(backend.generate("return JSON"), '{"ok":true}')

        payload = json.loads(transport.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertNotEqual(payload["response_format"]["type"], "json_object")
        self.assertEqual(
            payload["response_format"]["json_schema"]["schema"],
            GENERIC_JSON_OBJECT_SCHEMA,
        )

    def test_initial_policy_schema_reuses_canonical_strategy_dsl_schema(self):
        self.assertIs(
            INITIAL_POLICY_RESPONSE_SCHEMA["properties"]["strategy_prompt"],
            STRATEGY_DSL_JSON_SCHEMA,
        )

        client = LLMClient("http://127.0.0.1:18080", "qwen3_5_9b")
        backend = client.prompt_backend(
            operation="initial_policy_generation",
            response_schema=INITIAL_POLICY_RESPONSE_SCHEMA,
            response_schema_name="eagle_initial_policy",
        )
        self.assertEqual(
            backend.response_schema["properties"]["strategy_prompt"],
            STRATEGY_DSL_JSON_SCHEMA,
        )

    def test_strategy_alignment_request_uses_its_existing_output_schema(self):
        backend = OpenAICompatibleStrategyAlignmentBackend(
            "http://192.168.1.136:1234/v1",
            "qwen/qwen3.5-9b",
        )
        with patch(
            "eagle.evaluation.strategy_alignment.urllib.request.urlopen",
            return_value=_Response('{"score":7,"reason":"aligned"}'),
        ) as transport:
            self.assertEqual(
                backend.evaluate("evaluate this"),
                '{"score":7,"reason":"aligned"}',
            )

        payload = json.loads(transport.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(
            payload["response_format"]["json_schema"]["schema"],
            STRATEGY_ALIGNMENT_RESPONSE_SCHEMA,
        )

    def test_framework_coach_selector_uses_bundle_schema_only_for_coach_role(self):
        bundle = validate_framework_bundle(bundle_payload())
        bundle_hash = "a" * 64
        framework_schema = framework_selection_response_schema(bundle, bundle_hash)
        backend = OpenAICompatibleReflectionBackend(
            "http://192.168.1.136:1234/v1",
            "qwen/qwen3.5-9b",
            response_schema_selector=lambda prompt: (
                framework_schema,
                "eagle_framework_selection",
            )
            if "ROLE: framework_coach" in prompt
            else None,
        )
        with patch(
            "eagle.operators.reflection.urllib.request.urlopen",
            return_value=_Response("{}"),
        ) as transport:
            backend.generate("ROLE: framework_coach")
            backend.generate("ROLE: match_commentator")

        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in transport.call_args_list
        ]
        self.assertEqual(
            payloads[0]["response_format"]["json_schema"]["name"],
            "eagle_framework_selection",
        )
        self.assertEqual(
            payloads[0]["response_format"]["json_schema"]["schema"],
            framework_schema,
        )
        self.assertEqual(
            payloads[1]["response_format"]["json_schema"]["schema"],
            GENERIC_JSON_OBJECT_SCHEMA,
        )

    def test_json_schema_response_content_keeps_existing_json_parser_behavior(self):
        response = '{"strategy_prompt":{"version":"eagle-strategy-dsl-v1","rules":[]}}'
        self.assertEqual(
            parse_json_object_response(response),
            {
                "strategy_prompt": {
                    "version": "eagle-strategy-dsl-v1",
                    "rules": [],
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
