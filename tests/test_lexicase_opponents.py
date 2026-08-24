from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig, FIXED_OPPONENT_WEIGHT_SUM
from eagle.opponent_archive import ensure_opponent_archive, update_opponent_archive
from eagle.opponent_cases import LEXICASE_CASES
from eagle.selection import best_candidate, lexicase_select, select_next_generation


def candidate(candidate_id: str, scores: dict[str, float], *, generation: int = 0) -> Candidate:
    return Candidate(
        id=candidate_id,
        generation=generation,
        status="evaluated",
        fitness_objectives=scores,
        game_eval_result={"game_performance": sum(scores.values()) / len(scores)},
    )


class LexicaseOpponentTests(unittest.TestCase):
    def test_fixed_roster_and_reporting_weights(self) -> None:
        config = ExperimentConfig.from_mapping({})
        self.assertEqual(config.evaluation_opponent_ids, LEXICASE_CASES)
        self.assertEqual(config.fixed_opponent_weight_sum, FIXED_OPPONENT_WEIGHT_SUM)
        self.assertEqual(config.expected_match_count, 126)
        self.assertEqual(
            config.evaluation_opponent_ids,
            ("lightrush", "heavyrush", "workerrush", "allinbot", "mayari", "coac", "tma"),
        )
        self.assertNotIn("passive", config.evaluation_opponent_ids)
        self.assertNotIn("random", config.evaluation_opponent_ids)
        self.assertNotIn("randombias", config.evaluation_opponent_ids)

    def test_lexicase_is_reproducible_and_uses_all_cases(self) -> None:
        left = candidate("left", {case: 10.0 if case == "lightrush" else 0.0 for case in LEXICASE_CASES})
        right = candidate("right", {case: 10.0 if case == "heavyrush" else 0.0 for case in LEXICASE_CASES})
        first = lexicase_select([left, right], random.Random(17)).id
        second = lexicase_select([left, right], random.Random(17)).id
        self.assertEqual(first, second)

    def test_survivor_selection_keeps_elite_and_fixed_population_size(self) -> None:
        parents = [candidate("parent", {case: 1.0 for case in LEXICASE_CASES})]
        offspring = [
            candidate("child-a", {case: 2.0 for case in LEXICASE_CASES}, generation=1),
            candidate("child-b", {case: 3.0 for case in LEXICASE_CASES}, generation=1),
        ]
        selected = select_next_generation(parents, offspring, population_size=2, rng=random.Random(3))
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].id, "child-b")

    def test_opponent_capability_can_be_retained_or_lost_by_lexicase_replacement(self) -> None:
        capability_winner = candidate("light-capability", {case: 20.0 for case in LEXICASE_CASES})
        retained = select_next_generation(
            [capability_winner], [], population_size=1, rng=random.Random(1)
        )
        self.assertEqual(retained[0].id, "light-capability")

        aggregate_challenger = candidate("aggregate-challenger-wins", {case: 2.0 for case in LEXICASE_CASES})
        lost = select_next_generation(
            [capability_winner], [aggregate_challenger], population_size=1, rng=random.Random(1)
        )
        self.assertEqual(lost[0].id, "aggregate-challenger-wins")

    def test_best_candidate_excludes_failed_candidates(self) -> None:
        failed = Candidate(
            id="failed-high-score",
            status="failed",
            fitness_objectives={case: 100.0 for case in LEXICASE_CASES},
            game_eval_result={"game_performance": 100.0},
        )
        runnable = candidate("runnable", {case: 1.0 for case in LEXICASE_CASES})

        self.assertIs(best_candidate([failed]), None)
        self.assertEqual(best_candidate([failed, runnable]).id, "runnable")

    def test_per_opponent_archive_keeps_best_score_without_code_quality_tie_break(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            ensure_opponent_archive(run)
            low = candidate("z-low", {case: 1.0 for case in LEXICASE_CASES})
            high = candidate("a-high", {case: 2.0 for case in LEXICASE_CASES})
            update_opponent_archive(run, [low])
            update_opponent_archive(run, [high])
            payload = json.loads((run / "archives" / "opponents.json").read_text())
        self.assertEqual(payload["opponents"]["lightrush"]["candidate_id"], "a-high")


if __name__ == "__main__":
    unittest.main()
