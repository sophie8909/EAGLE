import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_candidate
from eagle.mutation import build_code_reflection_prompt, build_strategy_reflection_prompt, ReflectionContext
from eagle.search import mutation_context_from_candidate
from generation.backend import MockGenerationBackend
from eagle.opponent_cases import FAILED_OPPONENT_SCORE as FAILED_GAME_PERFORMANCE, LEXICASE_CASES
from evaluation.code_quality import build_failure_code_quality
from evaluation.objectives import build_objectives


class ReflectionContextTests(unittest.TestCase):
    def test_missing_game_metrics_uses_canonical_failure_sentinel(self):
        objectives = build_objectives(
            game_metrics=None,
            code_quality=build_failure_code_quality("generation"),
        )
        self.assertTrue(all(value == FAILED_GAME_PERFORMANCE for value in objectives.values()))

    def test_evaluation_propagates_canonical_evidence_to_next_reflection(self):
        config = ExperimentConfig.from_mapping({})
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
        self.assertNotIn("game", evidence)
        self.assertNotIn("code_quality", evidence)
        self.assertEqual(evaluation.candidate.game_eval_result["game_performance"], evaluation.game_metrics.objective)
        context = mutation_context_from_candidate(evaluation.candidate, generation=1, index=0)
        self.assertEqual(context.objectives, evaluation.candidate.fitness_objectives)
        self.assertEqual(context.compilation_result["status"], "success")
        self.assertEqual(context.validation_result["status"], "passed")
        self.assertEqual(context.completed_match_count, 180)

    def test_failed_context_preserves_sentinel_and_root_cause(self):
        candidate = Candidate(
            status="failed",
            failure_stage="compilation",
            failure_reason="missing symbol: commandAttack",
            fitness_objectives={case: FAILED_GAME_PERFORMANCE for case in LEXICASE_CASES},
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
        prompt = build_code_reflection_prompt(candidate, context)
        self.assertIn("missing symbol: commandAttack", prompt)

    def test_strategy_template_keeps_canonical_envelope_in_stable_field(self):
        candidate = Candidate(id="strategy-parent", strategy_prompt="play economy")
        context = ReflectionContext(
            generation=1,
            index=0,
            candidate_id="feedback-parent",
            objectives={"game_performance": 12.5, "code_quality": 590.0},
            evaluation_status="evaluated",
            game_evidence={"completed_match_count": 180, "objective": 12.5},
            match_summary={"wins": 6},
        )
        prompt = build_strategy_reflection_prompt(candidate, context)
        self.assertIn("feedback-parent", prompt)
        self.assertIn("game_performance", prompt)
        self.assertIn("12.5", prompt)
        self.assertNotIn("Parent generated_java", prompt)


if __name__ == "__main__":
    unittest.main()
