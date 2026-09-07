"""Focused contracts for the opt-in inherited Java candidate component."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.crossover import CrossoverContext, crossover
from eagle.evaluation import decode_validate_compile_candidate
from eagle.mutation import MutationContext
from eagle.rewrite import PromptRewriteMutation
from eagle.run_artifacts import load_candidate
from eagle.search import initialize_population
from generation.agent_template import JavaTemplatePaths, load_java_template
from generation.backend import GenerationBackend


class CountingBackend(GenerationBackend):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, candidate: Candidate, class_name: str) -> str:
        self.calls.append(candidate.id)
        return load_java_template(JavaTemplatePaths())


class ChoiceSequence:
    def __init__(self, choices: tuple[int, int, int]) -> None:
        self.choices = iter(choices)

    def choice(self, values):
        return values[next(self.choices)]


class ScriptedBackend:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = iter(responses)
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return next(self.responses)


class InheritedJavaGenotypeTests(unittest.TestCase):
    def test_generation_zero_single_seed_generates_ten_attempts_and_artifacts(self) -> None:
        config = ExperimentConfig.from_mapping({
            "candidate_java_mode": "inherited_genotype",
            "population_size": 10,
        })
        population = initialize_population(config)
        self.assertEqual(len(population), 10)
        self.assertEqual({candidate.strategy_prompt for candidate in population}, {""})
        self.assertEqual({candidate.metadata["seed_index"] for candidate in population}, {0})
        self.assertEqual(
            [candidate.metadata["replicate_index"] for candidate in population],
            list(range(10)),
        )
        self.assertEqual(
            {candidate.inherited_java for candidate in population},
            {config.initial_java_seed_path.read_text(encoding="utf-8")},
        )

        backend = CountingBackend()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for candidate in population:
                result = decode_validate_compile_candidate(
                    candidate,
                    config=config,
                    backend=backend,
                    generated_agents_dir=root / "generated_agents",
                    classes_dir=root / "classes",
                    candidate_artifact_dir=root / "candidates" / candidate.id,
                    mock=True,
                )
                self.assertEqual(len(result.attempts), 1)
                self.assertTrue(
                    (root / "candidates" / candidate.id / "generation" / "attempts" / "attempt_001" / "request.txt").is_file()
                )
        self.assertEqual(len(backend.calls), 10)

    def test_crossover_selects_java_parent_independently_and_records_provenance(self) -> None:
        parent_a = Candidate(
            id="parent-a", strategy_prompt="policy-a", generation_prompt="prompt-a",
            generated_java="generated-a",
        )
        parent_b = Candidate(
            id="parent-b", strategy_prompt="policy-b", generation_prompt="prompt-b",
            inherited_java="inherited-b",
        )
        child = crossover(
            parent_a,
            parent_b,
            CrossoverContext(1, 0, ChoiceSequence((0, 1, 1)), inherit_java=True),
        )
        self.assertEqual(child.strategy_parent_id, "parent-a")
        self.assertEqual(child.generation_prompt_parent_id, "parent-b")
        self.assertEqual(child.java_parent_id, "parent-b")
        self.assertEqual(child.inherited_java, "inherited-b")
        self.assertEqual(child.resolved_source_candidate_ids(), ("parent-a", "parent-b"))
        self.assertEqual(child.lineage_to_json_dict()["java_parent_id"], "parent-b")

    def test_resume_reconstructs_inherited_java_component(self) -> None:
        candidate = Candidate(
            id="child", generation=2, parent_ids=("parent",),
            strategy_prompt="policy", generation_prompt="prompt",
            inherited_java="// inherited Java", java_parent_id="parent",
            operator="copy", strategy_parent_id="parent",
            generation_prompt_parent_id="parent", source_candidate_ids=("parent",),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            candidates_dir = run_dir / "candidates"
            write_candidate_inputs(candidates_dir, candidate)
            write_candidate_snapshot(candidates_dir, candidate)
            restored = load_candidate(run_dir, candidate.id)
        self.assertEqual(restored.inherited_java, "// inherited Java")
        self.assertEqual(restored.java_parent_id, "parent")
        self.assertIn("parent", restored.resolved_source_candidate_ids())

    def test_default_request_does_not_receive_parent_java(self) -> None:
        request = Candidate(generated_java="PARENT_JAVA_SENTINEL").generation_input()
        self.assertNotIn("PARENT_JAVA_SENTINEL", request)

    def test_inherited_request_contains_all_active_components(self) -> None:
        request = Candidate(
            strategy_prompt="POLICY_SENTINEL",
            generation_prompt="GENERATION_SENTINEL",
            inherited_java="INHERITED_JAVA_SENTINEL",
        ).generation_input()
        self.assertIn("POLICY_SENTINEL", request)
        self.assertIn("GENERATION_SENTINEL", request)
        self.assertIn("INHERITED_JAVA_SENTINEL", request)

    def test_inherited_mode_rejects_multiple_seed_policies(self) -> None:
        config = ExperimentConfig(
            seed_prompts=("first", "second"),
            candidate_java_mode="inherited_genotype",
        )
        with self.assertRaisesRegex(ValueError, "exactly one seed_prompt_files"):
            config.validate()

    def test_code_reflection_reviews_child_policy_and_inherited_java(self) -> None:
        config = ExperimentConfig.from_mapping({"candidate_java_mode": "inherited_genotype"})
        backend = ScriptedBackend((
            '{"assessment":"java_faithfully_implements_policy","alignment_review":[],"required_generation_behaviors":[]}',
            '{"remove_rule_ids":[],"add_rules":[{"category":"requirement_coverage","instruction":"Preserve every stated prerequisite in reachable strategy behavior."}]}',
        ))
        child = Candidate(
            id="child", strategy_prompt="CHILD_POLICY", generation_prompt="parent translation",
            inherited_java=(
                "FIXED_INHERITED_JAVA\n"
                "// EAGLE_AGENT_STRATEGY_START\n"
                "private void decide(AgentContext context) { // INHERITED_JAVA\n}\n"
                "// EAGLE_AGENT_STRATEGY_END\n"
            ),
            java_parent_id="java-parent",
        )
        mutated = PromptRewriteMutation(
            config,
            mutation_type="code",
            reflection_backend=backend,
            rewrite_backend=backend,
        ).mutate(child, MutationContext(generation=1, index=0))
        self.assertIn("CHILD_POLICY", backend.calls[0])
        self.assertIn("INHERITED_JAVA", backend.calls[0])
        self.assertNotIn("FIXED_INHERITED_JAVA", backend.calls[0])
        evidence = mutated.metadata["mutation"]["evidence"]
        self.assertEqual(evidence["java_parent_id"], "java-parent")
        self.assertEqual(evidence["reviewed_java_input"], "inherited_java")
        self.assertEqual(
            evidence["reviewed_inherited_java_artifact"],
            "candidates/child/genotype/inherited_java.java",
        )


if __name__ == "__main__":
    unittest.main()
