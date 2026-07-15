import json
import tempfile
import unittest
from pathlib import Path

from eagle.artifacts import write_candidate_artifacts, write_candidate_inputs
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_candidate
from eagle.mutation import MutationContext
from eagle.rewrite import PromptRewriteMutation
from generation.agent_template import JavaTemplatePaths, load_java_template
from generation.backend import GenerationBackend, MockGenerationBackend


class ScriptedMutationBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        return next(self.responses)


class FailingGenerationBackend(GenerationBackend):
    def generate(self, candidate, class_name):
        return ""


class Phase2CMutationPipelineTests(unittest.TestCase):
    def _candidate(self):
        return Candidate(
            id="phase2c-child",
            generation=3,
            parent_ids=("parent-1", "parent-2"),
            strategy_prompt="original strategy prompt",
            previous_code=load_java_template(JavaTemplatePaths()),
            generation_prompt="original generation prompt",
            operator="crossover",
            strategy_parent_id="parent-1",
            previous_code_parent_id="parent-2",
            generation_prompt_parent_id="parent-1",
            source_candidate_ids=("parent-1", "parent-2"),
        )

    def _context(self):
        return MutationContext(
            generation=3,
            index=0,
            match_summary={"wins": 6, "draws": 1, "losses": 3},
            compilation_result={"ok": True},
        )

    def test_strategy_mutation_rewrite_generation_persists_complete_pipeline(self):
        self._assert_complete_pipeline(
            mutation_type="strategy",
            rewritten="rewritten strategy prompt",
            untouched="original generation prompt",
        )

    def test_code_mutation_rewrite_generation_persists_complete_pipeline(self):
        self._assert_complete_pipeline(
            mutation_type="code",
            rewritten="rewritten generation prompt",
            untouched="original strategy prompt",
        )


    def test_mutation_artifacts_survive_final_generation_failure(self):
        backend = ScriptedMutationBackend(("reflection evidence", "rewritten prompt"))
        config = ExperimentConfig.from_mapping(
            {"seed_prompts": ["seed"], "mutation_max_attempts": 1}
        )
        candidate = self._candidate()
        mutated = PromptRewriteMutation(
            config,
            mutation_type="code",
            reflection_backend=backend,
            rewrite_backend=backend,
        ).mutate(candidate, self._context())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evaluation = evaluate_candidate(
                mutated,
                config=config,
                backend=FailingGenerationBackend(),
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(root / "candidates", evaluation)
            candidate_dir = root / "candidates" / candidate.id
            self.assertEqual(evaluation.candidate.status, "failed")
            self.assertTrue((candidate_dir / "mutation" / "reflection_response_raw.txt").exists())
            self.assertTrue((candidate_dir / "mutation" / "rewrite_response_raw.txt").exists())
            self.assertTrue((candidate_dir / "generation" / "response_raw.txt").exists())
            timing = json.loads((candidate_dir / "timing.json").read_text(encoding="utf-8"))
            self.assertEqual(timing["generation_llm"]["attempts"][0]["status"], "error")

    def _assert_complete_pipeline(self, *, mutation_type, rewritten, untouched):
        backend = ScriptedMutationBackend(("reflection evidence", rewritten))
        config = ExperimentConfig.from_mapping(
            {"seed_prompts": ["seed"], "mutation_max_attempts": 1}
        )
        candidate = self._candidate()
        mutation = PromptRewriteMutation(
            config,
            mutation_type=mutation_type,
            reflection_backend=backend,
            rewrite_backend=backend,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mutated = mutation.mutate(
                candidate,
                self._context(),
                artifact_dir=root / candidate.id,
            )
            self.assertEqual(len(backend.calls), 2)
            self.assertEqual(mutated.previous_code, candidate.previous_code)
            if mutation_type == "strategy":
                self.assertEqual(mutated.strategy_prompt, rewritten)
                self.assertEqual(mutated.generation_prompt, untouched)
            else:
                self.assertEqual(mutated.strategy_prompt, untouched)
                self.assertEqual(mutated.generation_prompt, rewritten)

            evaluation = evaluate_candidate(
                mutated,
                config=config,
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_inputs(root / "candidates", mutated)
            write_candidate_artifacts(root / "candidates", evaluation)
            candidate_dir = root / "candidates" / candidate.id

            self.assertEqual(evaluation.candidate.previous_code, candidate.previous_code)
            self.assertEqual(evaluation.candidate.operator, "crossover+mutation")
            self.assertEqual(evaluation.candidate.mutation_type, mutation_type)
            self.assertEqual(evaluation.candidate.strategy_parent_id, "parent-1")
            self.assertEqual(evaluation.candidate.previous_code_parent_id, "parent-2")
            self.assertEqual(evaluation.candidate.generation_prompt_parent_id, "parent-1")
            self.assertEqual(evaluation.candidate.status, "evaluated")

            mutation_dir = candidate_dir / "mutation"
            generation_dir = candidate_dir / "generation"
            for name in (
                "reflection_request.txt",
                "reflection_response_raw.txt",
                "rewrite_request.txt",
                "rewrite_response_raw.txt",
                "metadata.json",
            ):
                self.assertTrue((mutation_dir / name).exists(), name)
            for name in (
                "request.txt",
                "response_raw.txt",
                "extracted_candidate.java",
                "normalized_candidate.java",
                "result.json",
            ):
                self.assertTrue((generation_dir / name).exists(), name)

            generation_request = (generation_dir / "request.txt").read_text(encoding="utf-8")
            self.assertIn(rewritten, generation_request)
            self.assertIn(candidate.previous_code, generation_request)
            self.assertIn("package ai.generated;", (generation_dir / "response_raw.txt").read_text(encoding="utf-8"))
            self.assertEqual(
                (generation_dir / "normalized_candidate.java").read_text(encoding="utf-8"),
                evaluation.result.assembled_java,
            )

            timing = json.loads((candidate_dir / "timing.json").read_text(encoding="utf-8"))
            for stage in ("reflection_llm", "rewrite_llm", "generation_llm"):
                self.assertEqual(len(timing[stage]["attempts"]), 1)
                self.assertGreaterEqual(timing[stage]["attempts"][0]["duration_seconds"], 0)
            self.assertEqual(timing["generation_llm"]["attempts"][0]["status"], "success")

            lineage = json.loads((candidate_dir / "lineage.json").read_text(encoding="utf-8"))
            self.assertEqual(lineage["source_candidate_ids"], ["parent-1", "parent-2"])
            self.assertEqual(lineage["operator"], "crossover+mutation")


if __name__ == "__main__":
    unittest.main()
