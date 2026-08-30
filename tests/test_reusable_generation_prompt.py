from __future__ import annotations

import unittest

from eagle.prompts import load_prompt
from eagle.reusable_generation_prompt import (
    RULES_END_MARKER,
    RULES_START_MARKER,
    apply_reusable_rule_delta,
    parse_reusable_generation_rules,
)


class ReusableGenerationPromptTests(unittest.TestCase):
    def test_initial_generation_prompt_is_canonical_and_bounded(self) -> None:
        prompt = load_prompt("initial_generation")
        rules = parse_reusable_generation_rules(prompt)

        self.assertEqual(len(rules), 6)
        self.assertEqual(len({rule.rule_id for rule in rules}), len(rules))
        self.assertIn(RULES_START_MARKER, prompt)
        self.assertIn(RULES_END_MARKER, prompt)
        self.assertLess(len(prompt), 4_000)

    def test_legacy_prompt_is_replaced_by_policy_agnostic_rule_delta(self) -> None:
        legacy = "Build Workers, remove barracksType, and call assignHarvesters()."
        result = apply_reusable_rule_delta(
            legacy,
            {
                "remove_rule_ids": [],
                "add_rules": [{
                    "category": "role_assignment",
                    "instruction": (
                        "Keep policy-defined roles mutually exclusive when one actor could satisfy several roles."
                    ),
                }],
            },
        )

        self.assertNotIn("Workers", result)
        self.assertNotIn("barracksType", result)
        self.assertNotIn("assignHarvesters", result)
        self.assertEqual(len(parse_reusable_generation_rules(result)), 1)

    def test_rule_ids_are_derived_deterministically(self) -> None:
        payload = {
            "remove_rule_ids": [],
            "add_rules": [{
                "category": "requirement_coverage",
                "instruction": "Make every stated prerequisite reachable before its dependent behavior.",
            }],
        }

        first = parse_reusable_generation_rules(
            apply_reusable_rule_delta("legacy prompt", payload)
        )
        second = parse_reusable_generation_rules(
            apply_reusable_rule_delta("different legacy prompt", payload)
        )
        self.assertEqual(first, second)

    def test_delta_removes_only_known_ids_and_preserves_order(self) -> None:
        current = load_prompt("initial_generation")
        result = apply_reusable_rule_delta(
            current,
            {
                "remove_rule_ids": ["core-priority-ordering"],
                "add_rules": [{
                    "category": "priority_ordering",
                    "instruction": (
                        "Honor explicit ordering between prerequisites, actions, and fallback behavior."
                    ),
                }],
            },
        )
        rules = parse_reusable_generation_rules(result)

        self.assertNotIn("core-priority-ordering", {rule.rule_id for rule in rules})
        self.assertEqual(rules[0].rule_id, "core-requirement-coverage")
        self.assertEqual(rules[-1].category, "priority_ordering")

    def test_delta_rejects_policy_specific_or_java_instructions(self) -> None:
        for instruction in (
            "Always produce Workers before attacking.",
            "Remove barracksType from CandidateAgent.",
            "Call assignRoles() before returning.",
        ):
            with self.subTest(instruction=instruction), self.assertRaises(ValueError):
                apply_reusable_rule_delta(
                    "legacy prompt",
                    {
                        "remove_rule_ids": [],
                        "add_rules": [{
                            "category": "requirement_coverage",
                            "instruction": instruction,
                        }],
                    },
                )

    def test_delta_rejects_unknown_removal(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown rule ids"):
            apply_reusable_rule_delta(
                load_prompt("initial_generation"),
                {
                    "remove_rule_ids": ["missing-rule"],
                    "add_rules": [],
                },
            )


if __name__ == "__main__":
    unittest.main()
