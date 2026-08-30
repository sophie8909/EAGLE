from __future__ import annotations

import os
import unittest
from unittest.mock import call, patch

from eagle.llm import EndpointConfigError, LLMClient, llm_request_progress


class LLMClientTests(unittest.TestCase):
    def test_one_client_has_one_base_url_and_model(self):
        client = LLMClient("http://127.0.0.1:8080", "qwen3.5-9b")
        self.assertEqual(client.base_url, "http://127.0.0.1:8080")
        self.assertEqual(client.model, "qwen3.5-9b")

    def test_invalid_endpoint_rejected(self):
        with self.assertRaises(EndpointConfigError):
            LLMClient("not-an-endpoint", "qwen3.5-9b")

    def test_llm_request_progress_is_visible_by_default(self):
        prefix = "[llm match_commentator] endpoint=http://127.0.0.1:8080 model=test-model"
        with patch.dict(os.environ, {}, clear=True), patch("builtins.print") as output:
            with llm_request_progress(
                stage="match_commentator",
                endpoint="http://127.0.0.1:8080",
                model="test-model",
            ):
                pass

        self.assertEqual(
            output.call_args_list,
            [
                call(f"{prefix} status=started", flush=True),
                call(f"{prefix} status=completed elapsed_seconds=0.0", flush=True),
            ],
        )

    def test_llm_request_progress_can_be_disabled(self):
        with patch.dict(os.environ, {"EAGLE_LLM_PROGRESS": "off"}, clear=True), patch(
            "builtins.print"
        ) as output:
            with llm_request_progress(
                stage="coach",
                endpoint="http://127.0.0.1:8080",
                model="test-model",
            ):
                pass

        output.assert_not_called()
