import json
import tempfile
import unittest
from pathlib import Path
import random
from eagle.candidate import Candidate, DEFAULT_MODULE_BODIES, MODULE_NAMES
from eagle.crossover import Crossover, CrossoverContext
from eagle.mutation import Mutation, MutationContext
from evaluation.compiler import compile_generated_agent
from generation.agent_template import render_agent_wrapper, render_behavior_class
from generation.backend import MockGenerationBackend
from generation.java_agent_generator import generate_java_agent, parse_behavior_functions
from generation.java_module_validator import validate_function_module
from eagle.config import ExperimentConfig

class StructuredBehaviorGenerationTests(unittest.TestCase):
    def test_structured_parser_requires_exact_complete_function_set(self):
        payload = json.dumps({"functions": DEFAULT_MODULE_BODIES})
        self.assertEqual(parse_behavior_functions(payload), DEFAULT_MODULE_BODIES)
        for functions in ({**DEFAULT_MODULE_BODIES, "helper": "return;"}, {k:v for k,v in DEFAULT_MODULE_BODIES.items() if k != "combat"}):
            with self.assertRaises(ValueError): parse_behavior_functions(json.dumps({"functions": functions}))

    def test_function_body_validation_rejects_scope_and_declarations(self):
        for body in ("", "```java\nreturn null;\n```", "return null; }", "class Helper {}", "private int helper() { return 1; }"):
            with self.assertRaises(ValueError): validate_function_module(body, "controller")
        validate_function_module("if (context.player == 0) { return new Decision(); }\nreturn new Decision();", "controller")

    def test_renderer_separates_fixed_wrapper_from_generated_behaviors(self):
        wrapper = render_agent_wrapper("CandidateAgent")
        behaviors = render_behavior_class("CandidateAgent", DEFAULT_MODULE_BODIES)
        self.assertIn("extends AI", wrapper)
        self.assertIn("new CandidateAgentBehaviors", wrapper)
        self.assertNotIn("Decision decision = new Decision()", wrapper)
        self.assertIn("Decision decision = new Decision()", behaviors)
        self.assertNotIn("extends AI", behaviors)
        for name in MODULE_NAMES:
            for line in DEFAULT_MODULE_BODIES[name].splitlines(): self.assertIn(line, behaviors)

    def test_mock_generation_writes_two_java_files(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent = generate_java_agent(Candidate(strategy_prompt="balanced"), MockGenerationBackend(), Path(temp))
            self.assertTrue(agent.source_path.exists())
            self.assertTrue(agent.behavior_source_path.exists())
            self.assertNotEqual(agent.source_path, agent.behavior_source_path)

    def test_crossover_selects_behavior_collection_as_one_component(self):
        bodies_a = {name: f"{name} A" for name in MODULE_NAMES}
        bodies_b = {name: f"{name} B" for name in MODULE_NAMES}
        child = Crossover().crossover(
            Candidate(id="a", module_bodies=bodies_a), Candidate(id="b", module_bodies=bodies_b),
            CrossoverContext(generation=1, index=0, rng=random.Random(2)),
        )
        self.assertIn(child.module_bodies, (bodies_a, bodies_b))
    def test_strategy_reflection_changes_strategy_not_individual_functions(self):
        class Backend:
            responses = iter(("reflection", "revised overall strategy"))
            def generate(self, prompt): return next(self.responses)
        parent = Candidate(id="parent", strategy_prompt="old strategy")
        child = Mutation(ExperimentConfig.from_mapping({"seed_prompts":["seed"]}), backend=Backend()).mutate(parent, MutationContext(1, 0))
        self.assertEqual(child.strategy_prompt, "revised overall strategy")
        self.assertEqual(child.module_bodies, parent.module_bodies)
    def test_fixed_wrapper_and_behaviors_compile_together(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            agent = generate_java_agent(Candidate(strategy_prompt="balanced"), MockGenerationBackend(), Path(temp))
            result = compile_generated_agent(agent.source_paths, microrts_dir=Path("third_party/microrts"), output_dir=Path(temp)/"classes")
            self.assertTrue(result.ok, result.stderr)

if __name__ == "__main__": unittest.main()
