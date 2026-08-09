from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig, FIXED_OPPONENT_WEIGHT_SUM
from eagle.evaluation import (
    EvaluationOpponent,
    _resolved_static_evaluation_opponents,
    evaluate_matches,
    prepare_eagle_opponent,
)
from evaluation.opponent_schedule import eagle_opponent_weight, select_previous_generation_champion
from evaluation.game_metrics import compute_game_metrics
from evaluation.game_performance import GamePerformanceBreakdown
from evaluation.microrts_runner import MatchResult
from generation.java_agent_generator import GeneratedJavaAgent


class WeightedAdaptiveOpponentTests(unittest.TestCase):
    def test_configured_weights_sum_to_12_5(self):
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
        self.assertEqual(config.fixed_opponent_weight_sum, FIXED_OPPONENT_WEIGHT_SUM)
        self.assertEqual(len(config.evaluation_opponent_ids), 10)

    def test_schedule_boundaries_and_quadratic_growth(self):
        self.assertEqual(eagle_opponent_weight(0, 50), 0.0)
        self.assertEqual(eagle_opponent_weight(1, 50), 0.5)
        self.assertEqual(eagle_opponent_weight(49, 50), 4.0)
        first_half = eagle_opponent_weight(12, 50) - eagle_opponent_weight(1, 50)
        second_half = eagle_opponent_weight(49, 50) - eagle_opponent_weight(25, 50)
        self.assertLess(first_half, second_half)

    def test_champion_tie_breaking(self):
        population = [
            Candidate(id="b", fitness_objectives={"game_performance": 4, "code_quality": 9}),
            Candidate(id="a", fitness_objectives={"game_performance": 4, "code_quality": 9}),
            Candidate(id="c", fitness_objectives={"game_performance": 5, "code_quality": 1}),
        ]
        self.assertEqual(select_previous_generation_champion(population).id, "c")
        population[2] = Candidate(id="c", fitness_objectives={"game_performance": 4, "code_quality": 9})
        self.assertEqual(select_previous_generation_champion(population).id, "a")

    def test_weighted_mean_is_normalized(self):
        results = [self._match(index, opponent_id, float(index + 1)) for index, opponent_id in enumerate((
            "passive", "random", "randombias", "lightrush", "heavyrush", "workerrush",
            "allibot", "mayari", "coac", "tma",
        ))]
        weights = {
            "passive": 0.5, "random": 0.5, "randombias": 0.5,
            "lightrush": 1.0, "heavyrush": 1.0, "workerrush": 1.0,
            "allibot": 2.0, "mayari": 2.0, "coac": 2.0, "tma": 2.0,
        }
        metrics = compute_game_metrics(results, fixed_opponent_weights=weights)
        expected = sum(weights[item.opponent_id] * item.score for item in metrics.opponent_results) / 12.5
        self.assertEqual(metrics.objective, round(expected, 6))
        self.assertEqual(metrics.total_weight, 12.5)
        self.assertEqual(metrics.weighted_numerator, round(sum(item.weighted_contribution for item in metrics.opponent_results), 6))

    def test_generation_one_evaluates_matrix_with_frozen_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "CandidateAgent.java"
            source.write_text("package ai.generated; public class CandidateAgent {}", encoding="utf-8")
            classes = root / "classes" / "candidate"
            classes.mkdir(parents=True)
            (classes / "CandidateAgent.class").write_bytes(b"compiled")
            agent = GeneratedJavaAgent("CandidateAgent", "ai.generated", source.read_text(), source)
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            reference = EvaluationOpponent(
                "eagle_previous_best", "ai.generated.EaglePreviousBest", weight=0.5,
                source_generation=0, source_candidate_id="champion-0",
            )
            observed = []

            def fake_match(**kwargs):
                observed.append(kwargs)
                return self._match(kwargs["match_index"], "match", 10.0)

            with patch("eagle.evaluation.run_microrts_match", side_effect=fake_match):
                results, error = evaluate_matches(
                    candidate=Candidate(id="child", generation=1), agent=agent,
                    config=config, classes_dir=root / "classes", match_artifacts_dir=root / "matches",
                    mock=True, ordinal=0, eagle_opponent=reference,
                )
        self.assertIsNone(error)
        self.assertEqual(len(results), 198)
        self.assertEqual(observed[-1]["opponent"], "ai.generated.EaglePreviousBest")
        self.assertEqual(observed[-1]["seed"], 2)
        self.assertEqual(results[-1].opponent_id, "eagle_previous_best")

    def test_dynamic_reference_compiles_with_relative_microrts_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = Path("eagle/java_templates/CandidateAgent.java").read_text(encoding="utf-8")
            champion = Candidate(
                id="champion",
                generation=0,
                generated_java=source,
                fitness_objectives={"game_performance": 12.0},
            )
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            opponent = prepare_eagle_opponent(
                champion,
                generation=1,
                config=config,
                classes_dir=root / "classes",
                mock=False,
            )
            self.assertEqual(opponent.class_name, "ai.generated.EaglePreviousBest")
            self.assertTrue((opponent.source_classes_dir / "ai" / "generated" / "EaglePreviousBest.class").is_file())
            manifest = root / "eagle_opponents" / "generation_0001_champion" / "manifest.json"
            self.assertTrue(manifest.is_file())

    def test_workerrush_roster_identity_is_loadable_from_vendored_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            opponents = _resolved_static_evaluation_opponents(
                config,
                mock=False,
                classes_dir=root / "classes",
            )
            worker = next(item for item in opponents if item.opponent_id == "workerrush")
            self.assertEqual(worker.class_name, "ai.abstraction.WorkerRush")
            self.assertTrue(
                (worker.classpath_entries[0] / "ai" / "abstraction" / "WorkerRush.class").is_file()
            )

    @staticmethod
    def _match(index: int, opponent_id: str, score: float) -> MatchResult:
        breakdown = GamePerformanceBreakdown(score, 0.0, 0.0, 0.0, 0.0, score, 0.0, 0.0, 0.5)
        return MatchResult(
            ok=True, score=score, command=["java"], match_index=index, opponent_id=opponent_id,
            opponent=opponent_id, opponent_name=opponent_id, winner=0,
            performance_breakdown=breakdown,
            raw_result={"winner": 0, "result": "p0_win", "players": {"p0": {}, "p1": {}}},
        )


if __name__ == "__main__":
    unittest.main()
