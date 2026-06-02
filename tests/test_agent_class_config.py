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


if __name__ == "__main__":
    unittest.main()
