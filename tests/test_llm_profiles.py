from __future__ import annotations

import unittest

from eagle.llm_profiles import EndpointConfigError, LLMClient


class LLMClientTests(unittest.TestCase):
    def test_one_client_has_one_base_url_and_model(self):
        client = LLMClient("http://127.0.0.1:8080", "qwen3.5-9b")
        self.assertEqual(client.profile.base_url, "http://127.0.0.1:8080")
        self.assertEqual(client.profile.model, "qwen3.5-9b")
        self.assertEqual(client.profile.profile, "shared")

    def test_invalid_endpoint_rejected(self):
        with self.assertRaises(EndpointConfigError):
            LLMClient("not-an-endpoint", "qwen3.5-9b")
