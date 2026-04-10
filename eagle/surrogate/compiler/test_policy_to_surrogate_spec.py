"""Tests for mapping fixed policies into surrogate Java specs."""

from __future__ import annotations

import unittest

from eagle.surrogate.compiler.policy_to_surrogate_spec import (
    compile_prompt_to_surrogate_spec,
    policy_to_surrogate_spec,
)


class PolicyToSurrogateSpecTests(unittest.TestCase):
    """Verify policy compression into deterministic surrogate agent specs."""

    def test_aggressive_light_policy_maps_to_rush_like_spec(self) -> None:
        spec = policy_to_surrogate_spec(
            {
                "strategy_identity": "aggressive",
                "opening_plan": "barracks_first",
                "unit_preference": "light",
                "attack_timing": "early",
            }
        )

        self.assertTrue(spec["enabled"])
        self.assertEqual(spec["worker_target_before_barracks"], 1)
        self.assertEqual(spec["min_lights"], 2)
        self.assertTrue(spec["attack_workers_first"])
        self.assertEqual(spec["production_priority"][0], "Light")

    def test_compile_prompt_to_surrogate_spec_uses_policy_defaults(self) -> None:
        policy, spec = compile_prompt_to_surrogate_spec("Play efficiently and defeat the opponent.")

        self.assertEqual(policy["strategy_identity"], "balanced")
        self.assertEqual(policy["attack_timing"], "mid")
        self.assertTrue(spec["enabled"])
        self.assertEqual(spec["desired_barracks"], 1)
        self.assertEqual(spec["min_lights"], 1)
        self.assertEqual(spec["min_ranged"], 1)
        self.assertEqual(spec["min_heavies"], 1)


if __name__ == "__main__":
    unittest.main()
