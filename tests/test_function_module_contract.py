import random
import shutil
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.crossover import Crossover, CrossoverContext
from eagle.mutation import Mutation, MutationContext
from evaluation.compiler import compile_generated_agent
from generation.agent_template import (
    ACTION_HELPER_METHODS,
    ACTION_HELPERS_END_MARKER,
    ACTION_HELPERS_START_MARKER,
    STRATEGY_END_MARKER,
    STRATEGY_START_MARKER,
    JavaTemplatePaths,
    extract_strategy_region,
    load_java_template,
    validate_java_template,
)
from generation.backend import MockGenerationBackend
from generation.java_agent_generator import generate_java_agent


class CompleteJavaGenerationTests(unittest.TestCase):
    def test_template_is_one_complete_marked_java_file(self):
        template = load_java_template(JavaTemplatePaths())
        self.assertIn("public final class CandidateAgent extends AbstractionLayerAI", template)
        self.assertIn(STRATEGY_START_MARKER, template)
        self.assertIn(STRATEGY_END_MARKER, template)
        self.assertIn(ACTION_HELPERS_START_MARKER, template)
        self.assertIn(ACTION_HELPERS_END_MARKER, template)
        self.assertNotIn("EAGLE_BODY:", template)
        self.assertNotIn("CandidateBehaviors", template)

    def test_template_contains_six_stable_action_helpers(self):
        template = load_java_template(JavaTemplatePaths())
        for helper in ACTION_HELPER_METHODS:
            self.assertEqual(template.count(f"boolean {helper}("), 1)
        self.assertIn("return translateActions(player, gs);", template)

    def test_extracts_one_strategy_region_without_fixed_method_contract(self):
        template = load_java_template(JavaTemplatePaths())
        region = extract_strategy_region(template)
        self.assertIn("private void decide", region)
        self.assertIn("commandHarvest", region)
        self.assertNotIn(ACTION_HELPERS_START_MARKER, region)

    def test_rejects_missing_or_duplicate_strategy_markers(self):
        template = load_java_template(JavaTemplatePaths())
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent_path = Path(temp) / "CandidateAgent.java"
            agent_path.write_text(template.replace(STRATEGY_START_MARKER, ""), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Agent strategy markers"):
                validate_java_template(JavaTemplatePaths(agent_path))
            agent_path.write_text(
                template.replace(
                    STRATEGY_START_MARKER,
                    STRATEGY_START_MARKER + "\n" + STRATEGY_START_MARKER,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Agent strategy markers"):
                validate_java_template(JavaTemplatePaths(agent_path))

    def test_rejects_missing_action_helper(self):
        template = load_java_template(JavaTemplatePaths())
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent_path = Path(temp) / "CandidateAgent.java"
            agent_path.write_text(
                template.replace("private boolean commandIdle(", "private boolean removedIdle("),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "commandIdle.*exactly once"):
                validate_java_template(JavaTemplatePaths(agent_path))

    def test_generation_prompt_requires_complete_java_only(self):
        prompt = Candidate(strategy_prompt="balanced").generation_input(class_name="CandidateAgent")
        self.assertIn("Generate the complete Java source file", prompt)
        self.assertIn("EAGLE_AGENT_STRATEGY_START", prompt)
        self.assertIn("private boolean commandMove", prompt)
        self.assertIn("FINAL OUTPUT CONTRACT", prompt)
        self.assertIn("Never return JSON", prompt)
        self.assertNotIn("All six strategy methods must be present", prompt)
        self.assertTrue(prompt.rstrip().endswith("Markdown fences."))

    def test_mock_generation_writes_only_complete_candidate_agent(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent = generate_java_agent(
                Candidate(strategy_prompt="balanced"),
                MockGenerationBackend(),
                Path(temp),
            )
            self.assertEqual(agent.source_paths, (agent.source_path,))
            self.assertEqual(agent.source_path.name, "CandidateAgent.java")
            self.assertEqual(agent.source_path.read_text(encoding="utf-8"), agent.source)
            self.assertIn(STRATEGY_START_MARKER, agent.source)
            self.assertTrue(agent.strategy_region)
            self.assertFalse((agent.source_path.parent / "CandidateBehaviors.java").exists())

    def test_crossover_selects_complete_previous_java_as_one_component(self):
        template = load_java_template(JavaTemplatePaths())
        source_a = template.replace("private void decide", "private void decideA", 1)
        source_b = template.replace("private void decide", "private void decideB", 1)
        child = Crossover().crossover(
            Candidate(id="a", previous_code="old-a", generated_java=source_a),
            Candidate(id="b", previous_code="old-b", generated_java=source_b),
            CrossoverContext(1, 0, random.Random(2)),
        )
        self.assertIn(child.previous_code, (source_a, source_b))

    def test_strategy_reflection_preserves_complete_previous_java(self):
        class Backend:
            responses = iter(("reflection", "revised overall strategy"))
            def generate(self, prompt):
                return next(self.responses)

        source = load_java_template(JavaTemplatePaths())
        parent = Candidate(id="parent", strategy_prompt="old strategy", previous_code=source)
        child = Mutation(
            ExperimentConfig.from_mapping({"seed_prompts": ["seed"]}),
            backend=Backend(),
        ).mutate(parent, MutationContext(1, 0))
        self.assertEqual(child.strategy_prompt, "revised overall strategy")
        self.assertEqual(child.previous_code, source)

    @unittest.skipUnless(shutil.which("javac"), "javac is required for the real template compile test")
    def test_complete_marked_template_compiles(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent = generate_java_agent(
                Candidate(strategy_prompt="balanced"),
                MockGenerationBackend(),
                Path(temp),
            )
            result = compile_generated_agent(
                agent.source_paths,
                microrts_dir=Path("third_party/microrts"),
                output_dir=Path(temp) / "classes",
            )
            self.assertTrue(result.ok, result.stderr)


if __name__ == "__main__":
    unittest.main()
