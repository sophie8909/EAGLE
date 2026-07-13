import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate, DEFAULT_MODULE_BODIES, MODULE_NAMES
from eagle.config import ExperimentConfig
from eagle.crossover import Crossover, CrossoverContext
from eagle.mutation import Mutation, MutationContext
from evaluation.compiler import compile_generated_agent
from generation.agent_template import (
    ACTION_HELPER_METHODS,
    JavaTemplatePaths,
    load_java_template,
    render_agent_template,
    validate_java_template,
)
from generation.backend import MockGenerationBackend
from generation.java_agent_generator import generate_java_agent, parse_behavior_functions
from generation.java_module_validator import validate_function_module


class StructuredBehaviorGenerationTests(unittest.TestCase):
    def test_loads_single_repository_java_template(self):
        template = load_java_template(JavaTemplatePaths())
        self.assertIn("public final class CandidateAgent extends AbstractionLayerAI", template)
        self.assertNotIn("CandidateBehaviors", template)

    def test_single_template_contains_six_action_helpers(self):
        template = load_java_template(JavaTemplatePaths())
        for helper in ACTION_HELPER_METHODS:
            self.assertEqual(template.count(f"boolean {helper}("), 1)
        self.assertIn("return translateActions(player, gs);", template)

    def test_replaces_all_agent_placeholders(self):
        template = load_java_template(JavaTemplatePaths())
        rendered = render_agent_template(template, DEFAULT_MODULE_BODIES)
        self.assertNotIn("EAGLE_BODY", rendered)
        for body in DEFAULT_MODULE_BODIES.values():
            for line in body.splitlines():
                self.assertIn(line, rendered)

    def test_rejects_missing_and_duplicate_placeholders(self):
        template = load_java_template(JavaTemplatePaths())
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent_path = Path(temp) / "CandidateAgent.java"
            agent_path.write_text(template.replace("/* EAGLE_BODY:combat */", ""), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "combat.*exactly once"):
                validate_java_template(JavaTemplatePaths(agent_path))
            agent_path.write_text(
                template.replace(
                    "/* EAGLE_BODY:combat */",
                    "/* EAGLE_BODY:combat */\n/* EAGLE_BODY:combat */",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "combat.*exactly once"):
                validate_java_template(JavaTemplatePaths(agent_path))

    def test_rejects_missing_action_helper(self):
        template = load_java_template(JavaTemplatePaths())
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent_path = Path(temp) / "CandidateAgent.java"
            agent_path.write_text(template.replace("private boolean commandIdle(", "private boolean removedIdle("), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "commandIdle.*exactly once"):
                validate_java_template(JavaTemplatePaths(agent_path))

    def test_rejects_unknown_generated_function_names(self):
        template = load_java_template(JavaTemplatePaths())
        with self.assertRaisesRegex(ValueError, "Unknown generated function names"):
            render_agent_template(template, {**DEFAULT_MODULE_BODIES, "helper": "return;"})

    def test_complete_java_parser_extracts_exact_function_set(self):
        template = load_java_template(JavaTemplatePaths())
        source = render_agent_template(template, DEFAULT_MODULE_BODIES)
        self.assertEqual(parse_behavior_functions(source), DEFAULT_MODULE_BODIES)
        with self.assertRaisesRegex(ValueError, "selectTarget.*exactly once"):
            parse_behavior_functions(source.replace("private Unit selectTarget(", "private Unit removedTarget("))

    def test_generation_prompt_requires_complete_java_file(self):
        prompt = Candidate(strategy_prompt="balanced").generation_input(class_name="CandidateAgent")
        self.assertIn("Generate the complete Java source file", prompt)
        self.assertIn("package ai.generated;", prompt)
        self.assertIn("private boolean commandMove", prompt)
        self.assertIn("final class brace", prompt)
        self.assertNotIn("Return only JSON", prompt)

    def test_function_body_validation_rejects_scope_and_declarations(self):
        bodies = (
            "",
            "```java\nreturn null;\n```",
            "return null; }",
            "class Helper {}",
            "private int helper() { return 1; }",
        )
        for body in bodies:
            with self.assertRaises(ValueError):
                validate_function_module(body, "controller")

    def test_mock_generation_writes_only_rendered_candidate_agent(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent = generate_java_agent(
                Candidate(strategy_prompt="balanced"),
                MockGenerationBackend(),
                Path(temp),
            )
            self.assertEqual(agent.source_paths, (agent.source_path,))
            self.assertEqual(agent.source_path.name, "CandidateAgent.java")
            self.assertEqual(agent.source_path.read_text(encoding="utf-8"), agent.source)
            self.assertNotIn("EAGLE_BODY", agent.source)
            self.assertFalse((agent.source_path.parent / "CandidateBehaviors.java").exists())

    def test_crossover_selects_behavior_collection_as_one_component(self):
        bodies_a = {name: f"{name} A" for name in MODULE_NAMES}
        bodies_b = {name: f"{name} B" for name in MODULE_NAMES}
        child = Crossover().crossover(
            Candidate(id="a", module_bodies=bodies_a),
            Candidate(id="b", module_bodies=bodies_b),
            CrossoverContext(1, 0, random.Random(2)),
        )
        self.assertIn(child.module_bodies, (bodies_a, bodies_b))

    def test_strategy_reflection_changes_strategy_not_functions(self):
        class Backend:
            responses = iter(("reflection", "revised overall strategy"))

            def generate(self, prompt):
                return next(self.responses)

        parent = Candidate(id="parent", strategy_prompt="old strategy")
        child = Mutation(
            ExperimentConfig.from_mapping({"seed_prompts": ["seed"]}),
            backend=Backend(),
        ).mutate(parent, MutationContext(1, 0))
        self.assertEqual(child.strategy_prompt, "revised overall strategy")
        self.assertEqual(child.module_bodies, parent.module_bodies)

    @unittest.skipUnless(shutil.which("javac"), "javac is required for the real template compile test")
    def test_rendered_single_template_compiles(self):
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