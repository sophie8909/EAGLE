"""Tests for the MicroRTS prompt-to-policy compiler."""

from __future__ import annotations

import unittest

from eagle.surrogate.compiler.prompt_policy_compiler import (
    DEFAULT_POLICY,
    build_compiler_prompt,
    compile_prompt_to_policy,
    validate_policy,
)


class PromptPolicyCompilerTests(unittest.TestCase):
    """Verify rule-based compilation and validation behavior."""

    def test_explicit_economic_prompt(self) -> None:
        """Verify clearly economic language maps to the economic default policy."""
        policy = compile_prompt_to_policy("Expand economy first and avoid early attacks.")
        self.assertEqual(
            policy,
            {
                "strategy_identity": "economic",
                "opening_plan": "worker_first",
                "unit_preference": "balanced",
                "attack_timing": "late",
            },
        )

    def test_explicit_aggressive_prompt(self) -> None:
        """Verify clearly aggressive language maps to an early rush policy."""
        policy = compile_prompt_to_policy(
            "Build military quickly and pressure the enemy as early as possible."
        )
        self.assertEqual(
            policy,
            {
                "strategy_identity": "aggressive",
                "opening_plan": "barracks_first",
                "unit_preference": "light",
                "attack_timing": "early",
            },
        )

    def test_explicit_defensive_prompt(self) -> None:
        """Verify clearly defensive language maps to a defensive late-attack policy."""
        policy = compile_prompt_to_policy("Play safely, defend your base, and only attack later.")
        self.assertEqual(
            policy,
            {
                "strategy_identity": "defensive",
                "opening_plan": "harvest_first",
                "unit_preference": "balanced",
                "attack_timing": "late",
            },
        )

    def test_vague_prompt_uses_defaults(self) -> None:
        """Verify underspecified prompts fall back to the neutral default policy."""
        policy = compile_prompt_to_policy("Play efficiently and defeat the opponent.")
        self.assertEqual(policy, DEFAULT_POLICY)

    def test_mixed_prompt_is_compressed_to_one_policy(self) -> None:
        """Verify mixed strategy language is compressed into one dominant policy."""
        policy = compile_prompt_to_policy(
            "Be aggressive when ahead but economic early and defend if needed."
        )
        self.assertEqual(
            policy,
            {
                "strategy_identity": "economic",
                "opening_plan": "harvest_first",
                "unit_preference": "balanced",
                "attack_timing": "mid",
            },
        )

    def test_invalid_llm_output_is_repaired(self) -> None:
        """Verify invalid LLM-produced values are repaired back to defaults."""
        def bad_llm(_: str) -> str:
            """Return an intentionally invalid policy payload for repair tests."""
            return (
                '{"strategy_identity": "berserk", "opening_plan": "all_in", '
                '"unit_preference": "laser", "attack_timing": "now"}'
            )

        policy = compile_prompt_to_policy("Rush them.", llm_callable=bad_llm)
        self.assertEqual(policy, DEFAULT_POLICY)

    def test_missing_fields_are_repaired(self) -> None:
        """Verify missing policy fields are backfilled with default values."""
        repaired = validate_policy({"strategy_identity": "aggressive"})
        self.assertEqual(
            repaired,
            {
                "strategy_identity": "aggressive",
                "opening_plan": "harvest_first",
                "unit_preference": "balanced",
                "attack_timing": "mid",
            },
        )

    def test_extra_fields_are_removed(self) -> None:
        """Verify validation strips fields outside the fixed compiler schema."""
        repaired = validate_policy(
            {
                "strategy_identity": "defensive",
                "opening_plan": "harvest_first",
                "unit_preference": "balanced",
                "attack_timing": "late",
                "extra": "ignored",
            }
        )
        self.assertEqual(
            repaired,
            {
                "strategy_identity": "defensive",
                "opening_plan": "harvest_first",
                "unit_preference": "balanced",
                "attack_timing": "late",
            },
        )
        self.assertEqual(set(repaired.keys()), set(DEFAULT_POLICY.keys()))

    def test_build_compiler_prompt_uses_exact_template(self) -> None:
        """Verify the compiler prompt preserves the required instruction template."""
        strategy_prompt = "Defend first."
        compiler_prompt = build_compiler_prompt(strategy_prompt)
        self.assertIn("You are a strategy compiler for MicroRTS.", compiler_prompt)
        self.assertIn(f"Strategy prompt:\n{strategy_prompt}", compiler_prompt)
        self.assertIn('"strategy_identity": "..."', compiler_prompt)


if __name__ == "__main__":
    unittest.main()
