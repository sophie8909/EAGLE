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
from generation.agent_template import JavaTemplatePaths, load_java_templates, render_behavior_template, validate_java_templates
from generation.backend import MockGenerationBackend
from generation.java_agent_generator import generate_java_agent, parse_behavior_functions
from generation.java_module_validator import validate_function_module

class StructuredBehaviorGenerationTests(unittest.TestCase):
    def test_loads_repository_java_templates(self):
        agent, behaviors = load_java_templates(JavaTemplatePaths())
        self.assertIn("public final class CandidateAgent", agent)
        self.assertIn("public final class CandidateBehaviors", behaviors)

    def test_replaces_all_behavior_placeholders(self):
        _, template = load_java_templates(JavaTemplatePaths())
        rendered = render_behavior_template(template, DEFAULT_MODULE_BODIES)
        self.assertNotIn("EAGLE_BODY", rendered)
        for body in DEFAULT_MODULE_BODIES.values():
            for line in body.splitlines(): self.assertIn(line, rendered)

    def test_rejects_missing_and_duplicate_placeholders(self):
        paths = JavaTemplatePaths()
        agent, behaviors = load_java_templates(paths)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp); agent_path = root / "CandidateAgent.java"; behavior_path = root / "CandidateBehaviors.java"
            agent_path.write_text(agent, encoding="utf-8")
            behavior_path.write_text(behaviors.replace("/* EAGLE_BODY:combat */", ""), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "combat.*exactly once"): validate_java_templates(JavaTemplatePaths(agent_path, behavior_path))
            behavior_path.write_text(behaviors.replace("/* EAGLE_BODY:combat */", "/* EAGLE_BODY:combat */\n/* EAGLE_BODY:combat */"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "combat.*exactly once"): validate_java_templates(JavaTemplatePaths(agent_path, behavior_path))

    def test_rejects_unknown_generated_function_names(self):
        _, template = load_java_templates(JavaTemplatePaths())
        with self.assertRaisesRegex(ValueError, "Unknown generated function names"):
            render_behavior_template(template, {**DEFAULT_MODULE_BODIES, "helper": "return;"})

    def test_structured_parser_requires_exact_complete_function_set(self):
        self.assertEqual(parse_behavior_functions(json.dumps({"functions": DEFAULT_MODULE_BODIES})), DEFAULT_MODULE_BODIES)
        with self.assertRaises(ValueError): parse_behavior_functions(json.dumps({"functions": {**DEFAULT_MODULE_BODIES, "helper": "return;"}}))

    def test_function_body_validation_rejects_scope_and_declarations(self):
        for body in ("", "```java\nreturn null;\n```", "return null; }", "class Helper {}", "private int helper() { return 1; }"):
            with self.assertRaises(ValueError): validate_function_module(body, "controller")

    def test_mock_generation_copies_and_renders_templates(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent = generate_java_agent(Candidate(strategy_prompt="balanced"), MockGenerationBackend(), Path(temp))
            source_template, _ = load_java_templates(JavaTemplatePaths())
            self.assertEqual(agent.source, source_template)
            self.assertEqual(agent.source_path.read_text(encoding="utf-8"), source_template)
            self.assertNotIn("EAGLE_BODY", agent.behavior_source)

    def test_crossover_selects_behavior_collection_as_one_component(self):
        bodies_a = {name: f"{name} A" for name in MODULE_NAMES}; bodies_b = {name: f"{name} B" for name in MODULE_NAMES}
        child = Crossover().crossover(Candidate(id="a", module_bodies=bodies_a), Candidate(id="b", module_bodies=bodies_b), CrossoverContext(1, 0, random.Random(2)))
        self.assertIn(child.module_bodies, (bodies_a, bodies_b))

    def test_strategy_reflection_changes_strategy_not_functions(self):
        class Backend:
            responses = iter(("reflection", "revised overall strategy"))
            def generate(self, prompt): return next(self.responses)
        parent = Candidate(id="parent", strategy_prompt="old strategy")
        child = Mutation(ExperimentConfig.from_mapping({"seed_prompts":["seed"]}), backend=Backend()).mutate(parent, MutationContext(1, 0))
        self.assertEqual(child.strategy_prompt, "revised overall strategy")
        self.assertEqual(child.module_bodies, parent.module_bodies)

    @unittest.skipUnless(shutil.which("javac"), "javac is required for the real template compile test")
    def test_rendered_templates_compile_together(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent = generate_java_agent(Candidate(strategy_prompt="balanced"), MockGenerationBackend(), Path(temp))
            result = compile_generated_agent(agent.source_paths, microrts_dir=Path("third_party/microrts"), output_dir=Path(temp)/"classes")
            self.assertTrue(result.ok, result.stderr)

if __name__ == "__main__": unittest.main()
