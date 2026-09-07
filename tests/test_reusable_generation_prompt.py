from __future__ import annotations

import json
import unittest

from eagle.prompts import load_prompt
from eagle.reusable_generation_prompt import (
    RULES_END_MARKER,
    RULES_START_MARKER,
    apply_reusable_rule_delta,
    parse_reusable_generation_rules,
    reusable_rules_json,
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

    def test_delta_rejects_invented_runtime_mechanisms(self) -> None:
        for instruction in (
            "Schedule repeated actions until the policy condition becomes false.",
            "Poll state inside a loop until every requested behavior completes.",
        ):
            with self.subTest(instruction=instruction), self.assertRaisesRegex(
                ValueError, "runtime mechanisms"
            ):
                apply_reusable_rule_delta(
                    "legacy prompt",
                    {
                        "remove_rule_ids": [],
                        "add_rules": [{
                            "category": "state_continuity",
                            "instruction": instruction,
                        }],
                    },
                )

    def test_delta_accepts_explicit_runtime_mechanism_prohibition(self) -> None:
        updated = apply_reusable_rule_delta(
            "legacy prompt",
            {
                "remove_rule_ids": [],
                "add_rules": [{
                    "category": "state_continuity",
                    "instruction": (
                        "Reevaluate policy conditions each decision cycle without "
                        "introducing loops or state machines."
                    ),
                }],
            },
        )
        self.assertIn("without introducing loops or state machines", updated)

    def test_delta_rejects_persistent_role_tracking_mechanism(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime mechanisms"):
            apply_reusable_rule_delta(
                "legacy prompt",
                {
                    "remove_rule_ids": [],
                    "add_rules": [{
                        "category": "role_assignment",
                        "instruction": (
                            "Preserve roles by tracking dedicated actors in persistent state."
                        ),
                    }],
                },
            )

    def test_delta_rejects_bypassing_idle_action_guard(self) -> None:
        for instruction in (
            "Keep continuous roles active by omitting conditional idle checks.",
            "Prioritize policy-critical actions without relying on unit idle states.",
            "Enforce continuous policy actions by removing all idle-friendly-unit guards.",
            "Evaluate continuous actions without blocking on idle state or prerequisite checks.",
        ):
            with self.subTest(instruction=instruction), self.assertRaisesRegex(
                ValueError, "idle-friendly-unit action guard"
            ):
                apply_reusable_rule_delta(
                    "legacy prompt",
                    {
                        "remove_rule_ids": [],
                        "add_rules": [{
                            "category": "state_continuity",
                            "instruction": instruction,
                        }],
                    },
                )

    def test_delta_rejects_multi_rule_mutation(self) -> None:
        with self.assertRaisesRegex(ValueError, "add_rules must contain exactly 1 rule"):
            apply_reusable_rule_delta(
                load_prompt("initial_generation"),
                {
                    "remove_rule_ids": [],
                    "add_rules": [
                        {
                            "category": "requirement_coverage",
                            "instruction": (
                                "Preserve each explicit threshold as a reachable condition."
                            ),
                        },
                        {
                            "category": "priority_ordering",
                            "instruction": (
                                "Resolve overlapping conditions in their stated priority order."
                            ),
                        },
                    ],
                },
            )

    def test_rule_length_error_reports_item_and_measured_length(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"add_rules\[0\].*has 241 characters; expected 12-240",
        ):
            apply_reusable_rule_delta(
                load_prompt("initial_generation"),
                {
                    "remove_rule_ids": [],
                    "add_rules": [{
                        "category": "requirement_coverage",
                        "instruction": "x" * 241,
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

    def test_malformed_marked_prompt_is_strict_except_at_explicit_rewrite_boundary(self) -> None:
        malformed = """Translate the policy.
EAGLE_REUSABLE_RULES_START
[**bad-id**] invalid_category | This historical whole-prompt rewrite is malformed.
EAGLE_REUSABLE_RULES_END"""
        with self.assertRaisesRegex(ValueError, "Invalid reusable generation rule line"):
            parse_reusable_generation_rules(malformed)

        recovered = apply_reusable_rule_delta(
            malformed,
            {
                "remove_rule_ids": [],
                "add_rules": [{
                    "category": "requirement_coverage",
                    "instruction": (
                        "Make every stated prerequisite reachable before its dependent behavior."
                    ),
                }],
            },
            recover_invalid_current=True,
        )
        self.assertEqual(len(parse_reusable_generation_rules(recovered)), 1)
        self.assertNotIn("bad-id", recovered)

    def test_repair_preserves_valid_rules_but_discards_invalid_rule(self) -> None:
        current = load_prompt("initial_generation").replace(
            RULES_END_MARKER,
            "[bad-idle-rule] state_continuity | Enforce continuous policy actions by "
            "removing all idle-friendly-unit guards.\n" + RULES_END_MARKER,
        )

        audit = json.loads(reusable_rules_json(current, recover_invalid_current=True))
        self.assertEqual(audit["validation_status"], "invalid")
        self.assertIn("idle-friendly-unit action guard", audit["validation_error"])
        self.assertEqual(len(audit["recoverable_rules"]), 6)

        repaired = apply_reusable_rule_delta(
            current,
            {
                "remove_rule_ids": [],
                "add_rules": [{
                    "category": "state_continuity",
                    "instruction": (
                        "Reevaluate each policy condition only for idle actors in every decision cycle."
                    ),
                }],
            },
            recover_invalid_current=True,
        )
        self.assertEqual(len(parse_reusable_generation_rules(repaired)), 7)
        self.assertNotIn("bad-idle-rule", repaired)


if __name__ == "__main__":
    unittest.main()
