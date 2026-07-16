from __future__ import annotations

import math
import unittest

from evaluation.game_metrics import FAILED_GAME_PERFORMANCE, compute_game_metrics
from evaluation.game_performance import (
    GamePerformanceBreakdown,
    GamePerformanceConfig,
    compute_performance_breakdown,
    tick_telemetry,
)
from evaluation.microrts_runner import MatchResult


class Phase4GamePerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = GamePerformanceConfig(material_scale=10.0, resource_scale=10.0)

    def tick(self, *, material_diff: int = 0, resource_diff: float = 0.0):
        player_units = {"Worker": max(0, material_diff)}
        enemy_units = {"Worker": max(0, -material_diff)}
        return tick_telemetry(
            50,
            max(0.0, resource_diff),
            max(0.0, -resource_diff),
            player_units,
            enemy_units,
            self.config,
        )

    def breakdown(self, *, winner: int, end_tick: int, tick=None):
        return compute_performance_breakdown(
            result="p0_win" if winner == 0 else "p1_win" if winner == 1 else "draw",
            winner=winner,
            end_tick=end_tick,
            max_tick=100,
            ticks=[tick or self.tick()],
            scoring_config=self.config,
            player_index=0,
        )

    def test_exact_result_baselines(self):
        self.assertEqual(self.breakdown(winner=0, end_tick=100).match_score, 100.0)
        self.assertEqual(self.breakdown(winner=-1, end_tick=50).match_score, 0.0)
        self.assertEqual(self.breakdown(winner=1, end_tick=0).match_score, -100.0)

    def test_tanh_components_and_survival_are_bounded(self):
        extreme = self.breakdown(
            winner=0,
            end_tick=0,
            tick=self.tick(material_diff=1_000_000, resource_diff=1_000_000),
        )

        self.assertAlmostEqual(extreme.unit_material_score, 5.0)
        self.assertAlmostEqual(extreme.final_resource_score, 3.0)
        self.assertEqual(extreme.survival_score, 2.0)
        self.assertEqual(extreme.shaping_score, 10.0)
        self.assertEqual(extreme.match_score, 110.0)

    def test_player_perspective_is_not_reversed(self):
        advantage = self.breakdown(
            winner=1,
            end_tick=100,
            tick=self.tick(material_diff=10, resource_diff=10),
        )
        expected_material = 5.0 * math.tanh(1.0)
        expected_resource = 3.0 * math.tanh(1.0)

        self.assertAlmostEqual(advantage.unit_material_score, expected_material, places=5)
        self.assertAlmostEqual(advantage.final_resource_score, expected_resource, places=5)
        self.assertGreater(advantage.match_score, -100.0)
        self.assertLess(advantage.match_score, -90.0)

    def test_ten_match_mean_and_statistics(self):
        results = [
            self.match(index, winner=0 if index < 4 else -1 if index < 6 else 1)
            for index in range(10)
        ]
        metrics = compute_game_metrics(results)

        self.assertEqual(metrics.completed_match_count, 10)
        self.assertEqual((metrics.wins, metrics.draws, metrics.losses), (4, 2, 4))
        self.assertEqual(metrics.win_rate, 0.4)
        self.assertEqual(metrics.objective, 0.0)
        self.assertEqual(metrics.mean_result_score, 0.0)
        self.assertEqual(metrics.minimum_match_score, -100.0)
        self.assertEqual(metrics.maximum_match_score, 100.0)
        self.assertGreater(metrics.score_stddev, 0.0)

    def test_partial_batch_is_failure_and_retains_evidence(self):
        results = [self.match(index, winner=0) for index in range(9)]
        metrics = compute_game_metrics(results)

        self.assertEqual(metrics.objective, FAILED_GAME_PERFORMANCE)
        self.assertEqual(metrics.completed_match_count, 9)
        self.assertEqual(len(metrics.match_summaries), 9)
        self.assertEqual(metrics.wins, 9)

    def match(self, index: int, *, winner: int) -> MatchResult:
        score = 100.0 if winner == 0 else -100.0 if winner == 1 else 0.0
        breakdown = GamePerformanceBreakdown(
            result_score=score,
            unit_material_score=0.0,
            final_resource_score=0.0,
            survival_score=0.0,
            shaping_score=0.0,
            match_score=score,
            mean_material_difference=0.0,
            final_resource_difference=0.0,
            survival_ratio=0.5,
        )
        return MatchResult(
            ok=True,
            score=score,
            command=["java"],
            winner=winner,
            final_cycle=50,
            player0_resource=5.0,
            player1_resource=5.0,
            weighted_resource_difference=0.0,
            performance_breakdown=breakdown,
            match_index=index,
            seed=index,
            raw_result={"result": "p0_win" if winner == 0 else "p1_win" if winner == 1 else "draw"},
        )


if __name__ == "__main__":
    unittest.main()
