import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.mutation import MutationContext
from eagle.rewrite import (
    PromptRewriteMutation,
    PromptRewriteStage,
    build_code_rewrite_prompt,
    build_strategy_rewrite_prompt,
)


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
        self.config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"], "mutation_max_attempts": 2})
        self.candidate = Candidate(
            id="rewrite-child",
            strategy_prompt="old strategy",
            previous_code="parent Java",
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
        backend = ScriptedRewriteBackend(("strategy reflection", "new strategy prompt"))
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
        self.assertEqual(child.previous_code, self.candidate.previous_code)
        self.assertEqual(child.generation_prompt, self.candidate.generation_prompt)
        self.assertEqual(child.operator, "crossover+mutation")
        self.assertTrue(child.metadata["mutation"]["applied"])
        self.assertEqual(child.metadata["mutation"]["original_strategy_prompt"], "old strategy")

    def test_code_rewrite_changes_only_generation_prompt(self):
        backend = ScriptedRewriteBackend(("code reflection", "new generation prompt"))
        mutation = PromptRewriteMutation(
            self.config,
            mutation_type="code",
            reflection_backend=backend,
            rewrite_backend=backend,
        )
        child = mutation.mutate(self.candidate, self.context)
        self.assertEqual(child.strategy_prompt, self.candidate.strategy_prompt)
        self.assertEqual(child.previous_code, self.candidate.previous_code)
        self.assertEqual(child.generation_prompt, "new generation prompt")
        self.assertEqual(child.mutation_type, "code")

    def test_rewrite_prompt_builders_include_reflection_and_original_component(self):
        backend = ScriptedRewriteBackend(("reflection",))
        reflection = PromptRewriteMutation(
            self.config,
            mutation_type="strategy",
            reflection_backend=backend,
            rewrite_backend=backend,
        ).reflection.reflect(self.candidate, self.context)
        strategy_prompt = build_strategy_rewrite_prompt(self.candidate, reflection, self.context)
        code_prompt = build_code_rewrite_prompt(self.candidate, reflection, self.context)
        self.assertIn("old strategy", strategy_prompt)
        self.assertIn("reflection", strategy_prompt)
        self.assertIn("old generation prompt", code_prompt)
        self.assertIn("reflection", code_prompt)

    def test_rewrite_output_rejects_java_and_retries(self):
        backend = ScriptedRewriteBackend(("package ai.generated; class CandidateAgent {}", "usable revised prompt"))
        result = PromptRewriteStage(backend, max_attempts=2).run(
            stage="strategy_rewrite",
            rewrite_type="strategy_prompt_rewrite",
            candidate=self.candidate,
            request="rewrite request",
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.rewritten_prompt, "usable revised prompt")
        self.assertEqual([attempt.status for attempt in result.attempts], ["error", "success"])

    def test_reflection_and_rewrite_artifacts_survive_rewrite_failure(self):
        backend = ScriptedRewriteBackend(("reflection", "", ""))
        with tempfile.TemporaryDirectory() as temp:
            mutation = PromptRewriteMutation(
                self.config,
                mutation_type="strategy",
                reflection_backend=backend,
                rewrite_backend=backend,
            )
            child = mutation.mutate(self.candidate, self.context, artifact_dir=Path(temp))
            mutation_dir = Path(temp) / "mutation"
            self.assertFalse(child.metadata["mutation"]["applied"])
            self.assertEqual(child.strategy_prompt, self.candidate.strategy_prompt)
            self.assertTrue((mutation_dir / "strategy_reflection_request.txt").exists())
            self.assertTrue((mutation_dir / "strategy_reflection_response_raw.txt").exists())
            self.assertTrue((mutation_dir / "strategy_rewrite_request.txt").exists())
            self.assertTrue((mutation_dir / "strategy_rewrite_response_raw.txt").exists())
            self.assertTrue((mutation_dir / "original_strategy_prompt.txt").exists())
            self.assertTrue((Path(temp) / "timing.json").exists())


if __name__ == "__main__":
    unittest.main()
