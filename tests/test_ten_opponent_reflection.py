from __future__ import annotations

import statistics
import unittest

from eagle.candidate import Candidate
from eagle.mutation import build_strategy_reflection_prompt
from eagle.opponents import EVALUATION_ROSTER, EXTERNAL_OPPONENTS
from eagle.run_artifacts import generation_metrics
from eagle.search import mutation_context_from_candidate
from evaluation.game_metrics import FAILED_GAME_PERFORMANCE, compute_game_metrics
from evaluation.game_performance import GamePerformanceBreakdown
from evaluation.microrts_runner import MatchResult


class TenOpponentReflectionTests(unittest.TestCase):
    def test_canonical_roster_is_ten_ordered_non_final_opponents(self):
        self.assertEqual(len(EVALUATION_ROSTER), 10)
        self.assertEqual(len({item.opponent_id for item in EVALUATION_ROSTER}), 10)
        self.assertEqual(
            [item.opponent_id for item in EVALUATION_ROSTER],
            ["random", "random_biased", "passive", "light_rush", "heavy_rush", "tiamat", "droplet", "izanagi", "mixed_bot", "guided_a3nw"],
        )
        self.assertTrue(set(EXTERNAL_OPPONENTS).isdisjoint(EVALUATION_ROSTER))

    def test_metrics_keep_all_opponents_and_aggregate_valid_scores(self):
        results = [self._match(item.opponent_id, 10.0 + index) for index, item in enumerate(EVALUATION_ROSTER)]
        metrics = compute_game_metrics(results)
        self.assertEqual(len(metrics.opponent_results), 10)
        self.assertEqual(metrics.opponent_scores, [10.0 + index for index in range(10)])
        self.assertEqual(metrics.objective, round(statistics.fmean(metrics.opponent_scores), 6))

    def test_failed_opponent_is_retained_with_failure_score(self):
        results = [self._match(item.opponent_id, 20.0 + index) for index, item in enumerate(EVALUATION_ROSTER)]
        results[4] = MatchResult(
            ok=False,
            score=0.0,
            command=["java"],
            opponent_id=EVALUATION_ROSTER[4].opponent_id,
            opponent=EVALUATION_ROSTER[4].display_name,
            status="failed",
            failure_category="timeout",
            failure_reason="opponent timed out",
        )
        metrics = compute_game_metrics(results)
        failed = metrics.opponent_results[4]
        self.assertEqual(len(metrics.opponent_results), 10)
        self.assertEqual(failed.score, FAILED_GAME_PERFORMANCE)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.failure["category"], "timeout")

    def test_prompt_contains_all_matchups_and_extrema(self):
        results = [self._match(item.opponent_id, float(index * 10)) for index, item in enumerate(EVALUATION_ROSTER)]
        metrics = compute_game_metrics(results)
        candidate = Candidate(
            id="reflection-candidate",
            status="evaluated",
            generated_java="parent Java",
            game_eval_result=metrics.to_json_dict(),
            fitness_objectives={"game_performance": metrics.objective, "code_quality": 590.0},
            metadata={
                "reflection_evidence": {
                    "candidate_id": "reflection-candidate",
                    "objectives": {"game_performance": metrics.objective, "code_quality": 590.0},
                    "evaluation_status": "evaluated",
                    "game": metrics.to_json_dict(),
                }
            },
        )
        context = mutation_context_from_candidate(candidate, generation=1, index=0)
        prompt = build_strategy_reflection_prompt(candidate, context)
        for index, item in enumerate(EVALUATION_ROSTER):
            self.assertIn(item.display_name, prompt)
            self.assertIn(f"{float(index * 10)}", prompt)
        self.assertIn("Strongest", prompt)
        self.assertIn("Weakest", prompt)
        self.assertIn("score_stddev", prompt)
        self.assertNotIn("TMA", prompt)
        self.assertNotIn("Mayari", prompt)
        self.assertNotIn("COAC", prompt)

    def test_generation_metrics_read_old_snapshots(self):
        candidate = Candidate(
            id="old-candidate",
            fitness_objectives={"game_performance": 12.0, "code_quality": 500.0},
            game_eval_result={"objective": 12.0},
        )
        payload = generation_metrics(0, [candidate])
        self.assertEqual(payload["opponent_scores"]["by_candidate"]["old-candidate"]["opponent_scores"], [])

    @staticmethod
    def _match(opponent_id: str, score: float) -> MatchResult:
        breakdown = GamePerformanceBreakdown(
            result_score=score,
            unit_material_score=0.0,
            final_resource_score=0.0,
            survival_score=0.0,
            shaping_score=0.0,
            match_score=score,
            mean_material_difference=0.0,
            final_resource_difference=2.0,
            survival_ratio=0.5,
        )
        return MatchResult(
            ok=True,
            score=score,
            command=["java"],
            opponent_id=opponent_id,
            opponent=opponent_id,
            opponent_name=next(item.display_name for item in EVALUATION_ROSTER if item.opponent_id == opponent_id),
            winner=0,
            performance_breakdown=breakdown,
            raw_result={
                "winner": 0,
                "result": "p0_win",
                "players": {
                    "p0": {"unit_count": 6, "resource_total": 10.0},
                    "p1": {"unit_count": 2, "resource_total": 3.0},
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
