import tempfile
import unittest
import random
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_candidate
from eagle.mutation import build_code_reflection_prompt
from eagle.search import choose_mutation, mutation_context_from_candidate
from generation.backend import MockGenerationBackend
from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE
from evaluation.code_quality import build_failure_code_quality
from evaluation.nsga2_objectives import build_objectives


class ReflectionContextTests(unittest.TestCase):
    def test_missing_game_metrics_uses_canonical_failure_sentinel(self):
        objectives = build_objectives(
            game_metrics=None,
            code_quality=build_failure_code_quality("generation"),
        )
        self.assertEqual(objectives["game_performance"], FAILED_GAME_PERFORMANCE)

    def test_evaluation_propagates_canonical_evidence_to_next_reflection(self):
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
        candidate = Candidate(strategy_prompt="Use economy before combat.")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evaluation = evaluate_candidate(
                candidate,
                config=config,
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )

        evidence = evaluation.candidate.metadata["reflection_evidence"]
        self.assertEqual(evidence["objectives"], evaluation.candidate.fitness_objectives)
        self.assertEqual(evidence["evaluation_status"], "evaluated")
        self.assertEqual(evidence["game"]["objective"], evaluation.candidate.fitness_objectives["game_performance"])
        self.assertEqual(evidence["code_quality"]["code_quality"], evaluation.candidate.fitness_objectives["code_quality"])
        context = mutation_context_from_candidate(evaluation.candidate, generation=1, index=0)
        self.assertEqual(context.objectives, evaluation.candidate.fitness_objectives)
        self.assertEqual(context.compilation_result["status"], "success")
        self.assertEqual(context.validation_result["status"], "passed")
        self.assertEqual(context.completed_match_count, 10)

    def test_failed_context_preserves_sentinel_and_root_cause(self):
        candidate = Candidate(
            status="failed",
            failure_stage="compilation",
            failure_reason="missing symbol: commandAttack",
            fitness_objectives={"game_performance": FAILED_GAME_PERFORMANCE, "code_quality": -805.0},
            metadata={
                "reflection_evidence": {
                    "candidate_id": "failed-candidate",
                    "objectives": {"game_performance": FAILED_GAME_PERFORMANCE, "code_quality": -805.0},
                    "evaluation_status": "failed",
                    "failure_stage": "compilation",
                    "failure_category": "Java compile failure",
                    "failure_reason": "missing symbol: commandAttack",
                    "generation": {"raw_response": "raw invalid response", "validation": {"status": "passed"}},
                    "compilation": {"status": "failed", "errors": ["missing symbol: commandAttack"]},
                    "game": {"objective": FAILED_GAME_PERFORMANCE, "completed_match_count": 0},
                    "code_quality": {"code_quality": -805.0, "failure_stage": "compilation", "compiler_errors": ["missing symbol: commandAttack"]},
                    "code_quality_payload": {},
                }
            },
        )
        context = mutation_context_from_candidate(candidate, generation=1, index=0)
        self.assertEqual(context.game_performance, FAILED_GAME_PERFORMANCE)
        self.assertEqual(context.failure_stage, "compilation")
        self.assertIn("missing symbol", context.error_message)
        self.assertEqual(choose_mutation(candidate, random.Random(1)), "code")
        prompt = build_code_reflection_prompt(candidate, context)
        self.assertIn(str(FAILED_GAME_PERFORMANCE), prompt)
        self.assertIn("missing symbol: commandAttack", prompt)

    def test_selection_uses_canonical_code_evidence(self):
        def candidate_with_quality(alignment, warnings=0):
            return Candidate(
                status="evaluated",
                fitness_objectives={"game_performance": 1.0, "code_quality": 500.0 + alignment},
                metadata={
                    "reflection_evidence": {
                        "evaluation_status": "evaluated",
                        "objectives": {"game_performance": 1.0, "code_quality": 500.0 + alignment},
                        "game": {"completed_match_count": 10},
                        "code_quality": {
                            "function_score": 80,
                            "strategy_alignment_score": alignment,
                            "warning_count": warnings,
                        },
                    }
                },
            )

        self.assertEqual(choose_mutation(candidate_with_quality(8), random.Random(1)), "strategy")
        self.assertEqual(choose_mutation(candidate_with_quality(3), random.Random(1)), "code")
        self.assertEqual(choose_mutation(candidate_with_quality(8, warnings=1), random.Random(1)), "code")


if __name__ == "__main__":
    unittest.main()
