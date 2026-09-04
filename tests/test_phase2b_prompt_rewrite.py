import tempfile
import unittest
import json
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.mutation import MutationContext, ReflectionStage, build_strategy_reflection_prompt
from eagle.rewrite import (
    PromptRewriteMutation,
    PromptRewriteStage,
    build_code_rewrite_prompt,
    build_strategy_rewrite_prompt,
)
from eagle.reusable_generation_prompt import (
    RULES_END_MARKER,
    RULES_START_MARKER,
    parse_reusable_generation_rules,
)


GENERIC_RULE = "Make every stated prerequisite reachable before its dependent behavior."


def code_rule_delta(*, instruction: str = GENERIC_RULE, extra: bool = False) -> str:
    payload = {
        "remove_rule_ids": [],
        "add_rules": [{
            "category": "requirement_coverage",
            "instruction": instruction,
        }],
    }
    if extra:
        payload["analysis"] = "not allowed"
    return json.dumps(payload)


class ScriptedRewriteBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


class Phase2BPromptRewriteTests(unittest.TestCase):
    def setUp(self):
        self.config = ExperimentConfig.from_mapping({"mutation_max_attempts": 2})
        self.candidate = Candidate(
            id="rewrite-child",
            strategy_prompt="old strategy",
            generation_prompt="old generation prompt",
            operator="crossover",
        )
        self.context = MutationContext(
            generation=2,
            index=0,
            match_summary={"wins": 5, "draws": 2, "losses": 3},
            compilation_result={"ok": True},
            error_category="",
        )

    def test_strategy_rewrite_call_order_and_component_isolation(self):
        backend = ScriptedRewriteBackend((self._strategy_reflection(), "new strategy prompt"))
        mutation = PromptRewriteMutation(
            self.config,
            mutation_type="strategy",
            reflection_backend=backend,
            rewrite_backend=backend,
        )
        child = mutation.mutate(self.candidate, self.context)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("Strategy Reflection stage", backend.calls[0])
        self.assertIn("Strategy Prompt Rewrite stage", backend.calls[1])
        self.assertEqual(child.strategy_prompt, "new strategy prompt")
        self.assertEqual(child.generation_prompt, self.candidate.generation_prompt)
        self.assertEqual(child.operator, "crossover+mutation")
        self.assertTrue(child.metadata["mutation"]["applied"])
        self.assertEqual(child.metadata["mutation"]["original_strategy_prompt"], "old strategy")

    def test_code_rewrite_changes_only_generation_prompt(self):
        backend = ScriptedRewriteBackend((
            self._code_reflection(),
            code_rule_delta(),
        ))
        mutation = PromptRewriteMutation(
            self.config,
            mutation_type="code",
            reflection_backend=backend,
            rewrite_backend=backend,
        )
        child = mutation.mutate(self.candidate, self.context)
        self.assertEqual(child.strategy_prompt, self.candidate.strategy_prompt)
        self.assertIn(RULES_START_MARKER, child.generation_prompt)
        self.assertIn(GENERIC_RULE, child.generation_prompt)
        self.assertEqual(len(parse_reusable_generation_rules(child.generation_prompt)), 1)
        self.assertEqual(child.mutation_type, "code")

    def test_code_rewrite_requires_exact_json_contract_and_retries(self):
        backend = ScriptedRewriteBackend((
            code_rule_delta(extra=True),
            "```json\n" + code_rule_delta() + "\n```",
        ))
        result = PromptRewriteStage(backend, max_attempts=2).run(
            rewrite_type="generation_prompt_rewrite",
            candidate=self.candidate,
            request="rewrite request",
        )
        self.assertTrue(result.succeeded)
        self.assertIn(GENERIC_RULE, result.rewritten_prompt)
        self.assertIn(RULES_END_MARKER, result.rewritten_prompt)
        self.assertEqual([attempt.status for attempt in result.attempts], ["error", "success"])
        self.assertEqual(backend.calls[0], "rewrite request")
        self.assertIn("previous response was rejected", backend.calls[1].lower())
        self.assertIn("exactly remove_rule_ids and add_rules", backend.calls[1])
        self.assertIn("rewrite request", backend.calls[1])

    def test_code_rewrite_retries_multi_rule_output_with_actionable_feedback(self):
        excessive_delta = json.dumps({
            "remove_rule_ids": [],
            "add_rules": [
                {
                    "category": "requirement_coverage",
                    "instruction": "Preserve each explicit threshold as a reachable condition.",
                },
                {
                    "category": "priority_ordering",
                    "instruction": "Resolve overlapping conditions in their stated priority order.",
                },
            ],
        })
        backend = ScriptedRewriteBackend((excessive_delta, code_rule_delta()))

        result = PromptRewriteStage(backend, max_attempts=2).run(
            rewrite_type="generation_prompt_rewrite",
            candidate=self.candidate,
            request="original code rewrite request",
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.attempts[0].error, "Code Rewrite add_rules must contain exactly 1 rule.")
        self.assertIn(result.attempts[0].error, backend.calls[1])
        self.assertIn("original code rewrite request", backend.calls[1])

    def test_code_rewrite_recovers_historically_malformed_balance_prompt(self):
        malformed_prompt = """Translate the policy.
EAGLE_REUSABLE_RULES_START
[**counterplay-priority**] counterplay_priority | Implement opponent-specific behavior:
  - lightrush: produce a concrete counter
EAGLE_REUSABLE_RULES_END"""
        candidate = Candidate(
            id="malformed-prompt-compliance-child",
            generation=2,
            strategy_prompt=self.candidate.strategy_prompt,
            generation_prompt=malformed_prompt,
            operator="copy",
        )
        backend = ScriptedRewriteBackend((
            self._code_reflection(),
            code_rule_delta(),
        ))

        child = PromptRewriteMutation(
            self.config,
            mutation_type="code",
            reflection_backend=backend,
            rewrite_backend=backend,
        ).mutate(candidate, self.context)

        self.assertTrue(child.metadata["mutation"]["applied"])
        self.assertNotIn("counterplay-priority", child.generation_prompt)
        self.assertIn(GENERIC_RULE, child.generation_prompt)
        self.assertEqual(len(parse_reusable_generation_rules(child.generation_prompt)), 1)
        self.assertIn("Current reusable rules", backend.calls[1])
        self.assertIn("[]", backend.calls[1])

    def test_code_rewrite_rejects_java_inside_json(self):
        backend = ScriptedRewriteBackend((
            code_rule_delta(instruction="Call implementPolicy() before returning Java."),
        ))
        result = PromptRewriteStage(backend, max_attempts=1).run(
            rewrite_type="generation_prompt_rewrite",
            candidate=self.candidate,
            request="rewrite request",
        )
        self.assertFalse(result.succeeded)
        self.assertIn("plain policy-agnostic prose", result.error)
    def test_rewrite_prompt_builders_include_reflection_and_original_component(self):
        backend = ScriptedRewriteBackend((self._strategy_reflection(),))
        reflection = ReflectionStage(backend, max_attempts=1).run(
            reflection_type="strategy",
            candidate=self.candidate,
            request=build_strategy_reflection_prompt(self.candidate, self.context),
        )
        strategy_prompt = build_strategy_rewrite_prompt(self.candidate, reflection, self.context)
        code_reflection = ReflectionStage(
            ScriptedRewriteBackend((self._code_reflection(),)), max_attempts=1
        ).run(
            reflection_type="code",
            candidate=self.candidate,
            request="review",
        )
        code_prompt = build_code_rewrite_prompt(self.candidate, code_reflection, self.context)
        self.assertIn("old strategy", strategy_prompt)
        self.assertIn("reflection", strategy_prompt)
        self.assertIn("IMMUTABLE MICRORTS GAMEPLAY CONTRACT", strategy_prompt)
        self.assertIn("may change strategy type", strategy_prompt)
        self.assertIn("old generation prompt", code_prompt)
        self.assertIn("Current reusable rules", code_prompt)
        self.assertIn('"add_rules"', code_prompt)
        self.assertIn("Policy-Code Alignment Review", code_prompt)
        self.assertIn("Immutable MicroRTS API contract", code_prompt)
        self.assertIn("commandMove", code_prompt)
        self.assertIn("exactly one add_rules item", code_prompt)
        self.assertIn("12-240 characters", code_prompt)
        self.assertNotIn("old strategy", code_prompt)

    def test_rewrite_output_rejects_java_and_retries(self):
        backend = ScriptedRewriteBackend(("package ai.generated; class CandidateAgent {}", "usable revised prompt"))
        result = PromptRewriteStage(backend, max_attempts=2).run(
            rewrite_type="strategy_prompt_rewrite",
            candidate=self.candidate,
            request="rewrite request",
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.rewritten_prompt, "usable revised prompt")
        self.assertEqual([attempt.status for attempt in result.attempts], ["error", "success"])

    def test_reflection_and_rewrite_artifacts_survive_rewrite_failure(self):
        backend = ScriptedRewriteBackend((self._strategy_reflection(), "", ""))
        with tempfile.TemporaryDirectory() as temp:
            mutation = PromptRewriteMutation(
                self.config,
                mutation_type="strategy",
                reflection_backend=backend,
                rewrite_backend=backend,
            )
            child = mutation.mutate(self.candidate, self.context, artifact_dir=Path(temp))
            mutation_dir = Path(temp) / "mutation" / "strategy_reflection"
            self.assertFalse(child.metadata["mutation"]["applied"])
            self.assertEqual(child.strategy_prompt, self.candidate.strategy_prompt)
            self.assertTrue((mutation_dir / "reflector_request.txt").exists())
            self.assertTrue((mutation_dir / "reflector_response_raw.txt").exists())
            self.assertTrue((mutation_dir / "rewriter_request.txt").exists())
            self.assertTrue((mutation_dir / "rewriter_response_raw.txt").exists())
            self.assertEqual(
                (mutation_dir / "rewriter_attempt_001_request.txt").read_text(encoding="utf-8"),
                backend.calls[1],
            )
            retry_request = (mutation_dir / "rewriter_attempt_002_request.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("non-empty prompt", retry_request)
            self.assertEqual(retry_request, backend.calls[2])
            self.assertTrue((mutation_dir / "original_policy_prompt.txt").exists())
            self.assertTrue((Path(temp) / "timing.json").exists())

    @staticmethod
    def _strategy_reflection():
        return json.dumps({
            "analysis": {"strengths": ["workers"], "weaknesses": ["late attack"], "priority_changes": ["attack earlier"]},
            "revised_strategy_prompt": "Attack earlier while preserving workers.",
        })

    @staticmethod
    def _code_reflection():
        return json.dumps({
            "assessment": "java_faithfully_implements_policy",
            "alignment_review": [],
            "required_generation_behaviors": [],
        })


if __name__ == "__main__":
    unittest.main()
