from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from evaluation.microrts_runner import MatchResult
from evaluation.parent_offspring import evaluate_parent_vs_offspring, head_to_head_reward


class ParentOffspringEvaluationTests(unittest.TestCase):
    def test_reward_formula(self):
        cases = (
            ((18, 0, 0), 1.0),
            ((0, 0, 18), 0.0),
            ((0, 18, 0), 0.5),
            ((9, 0, 9), 0.5),
            ((6, 6, 6), 0.5),
        )
        for (wins, draws, losses), expected in cases:
            with self.subTest(wins=wins, draws=draws, losses=losses):
                self.assertEqual(
                    head_to_head_reward(wins=wins, draws=draws, losses=losses),
                    expected,
                )

    def test_matrix_runs_both_sides_for_every_map_round_pair(self):
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
        offspring = Candidate(
            id="offspring",
            generation=1,
            generated_java="source",
            generated_java_path=None,
            compile_status="success",
        )
        parent = Candidate(id="parent", generated_java="source", compile_status="success")
        observed: list[dict] = []

        def fake_match(**kwargs):
            observed.append(kwargs)
            candidate_player = kwargs["candidate_player"]
            return MatchResult(
                ok=True,
                score=100.0,
                command=["java"],
                match_index=kwargs["match_index"],
                candidate_player=candidate_player,
                winner=candidate_player,
            )

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "evaluation.parent_offspring.run_microrts_match", side_effect=fake_match
        ):
            result = evaluate_parent_vs_offspring(
                offspring,
                parent,
                config=config,
                classes_dir=Path(temp_dir) / "classes",
                match_artifacts_dir=Path(temp_dir) / "aos" / "head_to_head" / "matches",
                mock=True,
            )

        self.assertEqual(result.total_matches, 18)
        self.assertEqual(result.wins, 18)
        self.assertEqual(result.reward, 1.0)
        grouped = {
            (item["map_path"], item["round_index"], item["seed"]): []
            for item in observed
        }
        for item in observed:
            grouped[(item["map_path"], item["round_index"], item["seed"])].append(
                item["candidate_player"]
            )
        self.assertEqual(len(grouped), 9)
        self.assertTrue(all(sorted(sides) == [0, 1] for sides in grouped.values()))
        self.assertTrue(all(
            item["java_system_properties"]["eagle.comparison.parent.classes"].endswith("/parent")
            for item in observed
        ))


if __name__ == "__main__":
    unittest.main()
