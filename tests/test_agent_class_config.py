"""Tests for selectable MicroRTS LLM Java agent configuration."""

from __future__ import annotations

import unittest

from eagle.config import load_config_payload


class AgentClassConfigTests(unittest.TestCase):
    def test_missing_agent_class_defaults_to_original_eagle(self) -> None:
        config = load_config_payload({})

        self.assertEqual(config.agent_class, "ai.eagle.EAGLE")

    def test_repair_agent_class_is_preserved(self) -> None:
        config = load_config_payload({"agent_class": "ai.eagle.EAGLERepair"})

        self.assertEqual(config.agent_class, "ai.eagle.EAGLERepair")

    def test_skip_same_behavior_state_defaults_to_true(self) -> None:
        config = load_config_payload({})

        self.assertTrue(config.skip_same_behavior_state)

    def test_skip_same_behavior_state_can_be_disabled(self) -> None:
        config = load_config_payload({"skip_same_behavior_state": "false"})

        self.assertFalse(config.skip_same_behavior_state)

    def test_missing_surrogate_llm_call_limit_defaults_to_ten(self) -> None:
        config = load_config_payload({})

        self.assertEqual(config.surrogate_llm_call_limit, 10)

    def test_surrogate_llm_call_limit_is_preserved(self) -> None:
        config = load_config_payload({"surrogate_llm_call_limit": 7})

        self.assertEqual(config.surrogate_llm_call_limit, 7)


if __name__ == "__main__":
    unittest.main()
