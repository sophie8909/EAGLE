from __future__ import annotations

import random
import unittest

from eagle.aos import (
    AOSConfig,
    AdaptiveOperatorSelection,
    GENERATE_CODE_REFLECTION,
    STRATEGY_REFLECTION,
    OperatorReward,
    calculate_operator_reward,
)
from eagle.candidate import Candidate
from eagle.opponent_cases import LEXICASE_CASES


def candidate_with_cases(
    candidate_id: str,
    results: dict[str, tuple[int, int, int]],
    *,
    runnable: bool = True,
) -> Candidate:
    rows = [
        {
            "opponent_id": opponent,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "status": "completed" if runnable else "failed",
        }
        for opponent, (wins, draws, losses) in results.items()
    ]
    return Candidate(
        id=candidate_id,
        status="evaluated" if runnable else "failed",
        failure_stage=None if runnable else "compilation",
        game_eval_result={
            "expected_match_count": 126,
            "completed_match_count": 126 if runnable else 0,
            "missing_match_count": 0 if runnable else 126,
            "opponent_results": rows,
        },
    )


class AdaptiveOperatorSelectionTests(unittest.TestCase):
    def test_initial_probabilities_are_code_biased(self):
        aos = AdaptiveOperatorSelection(AOSConfig())
        self.assertEqual(aos.probability(STRATEGY_REFLECTION), 0.20)
        self.assertEqual(aos.probability(GENERATE_CODE_REFLECTION), 0.80)
        self.assertAlmostEqual(sum(aos.probabilities.values()), 1.0)

    def test_execution_repair_gets_strong_positive_reward(self):
        parent = candidate_with_cases("parent", {}, runnable=False)
        child = candidate_with_cases("child", {"lightrush": (1, 0, 0)})
        reward = calculate_operator_reward(
            parent, child, operator=GENERATE_CODE_REFLECTION, config=AOSConfig()
        )
        self.assertEqual(reward.reward, 1.0)
        self.assertEqual(reward.transition, "failed_parent_to_runnable_child")

    def test_execution_regression_gets_strong_negative_reward(self):
        parent = candidate_with_cases("parent", {"lightrush": (1, 0, 0)})
        child = candidate_with_cases("child", {}, runnable=False)
        reward = calculate_operator_reward(
            parent, child, operator=STRATEGY_REFLECTION, config=AOSConfig()
        )
        self.assertEqual(reward.reward, -1.0)
        self.assertEqual(reward.transition, "runnable_parent_to_failed_child")

    def test_both_failed_are_small_negative(self):
        parent = candidate_with_cases("parent", {}, runnable=False)
        child = candidate_with_cases("child", {}, runnable=False)
        reward = calculate_operator_reward(
            parent, child, operator=GENERATE_CODE_REFLECTION, config=AOSConfig()
        )
        self.assertEqual(reward.reward, -0.1)

    def test_case_reward_counts_improvements_and_regressions(self):
        parent = candidate_with_cases(
            "parent",
            {
                "lightrush": (0, 0, 1),
                "heavyrush": (1, 0, 0),
                "workerrush": (0, 0, 1),
            },
        )
        child = candidate_with_cases(
            "child",
            {
                "lightrush": (1, 0, 0),
                "heavyrush": (0, 0, 1),
                "workerrush": (0, 0, 1),
            },
        )
        reward = calculate_operator_reward(
            parent, child, operator=STRATEGY_REFLECTION, config=AOSConfig()
        )
        self.assertEqual(reward.improved_cases, ("lightrush",))
        self.assertEqual(reward.regressed_cases, ("heavyrush",))
        self.assertEqual(reward.unchanged_cases, ("workerrush",))
        self.assertEqual(reward.compared_cases, 3)
        self.assertEqual(reward.reward, 0.0)

    def test_passive_random_and_randombias_do_not_affect_reward(self):
        parent = candidate_with_cases("parent", {"lightrush": (1, 0, 0)})
        child = candidate_with_cases("child", {"lightrush": (1, 0, 0)})
        for candidate in (parent, child):
            candidate.game_eval_result["opponent_results"].extend([
                {"opponent_id": "passive", "wins": 0, "losses": 1, "status": "completed"},
                {"opponent_id": "random", "wins": 1, "losses": 0, "status": "completed"},
                {"opponent_id": "randombias", "wins": 1, "losses": 0, "status": "completed"},
            ])
        reward = calculate_operator_reward(
            parent, child, operator=STRATEGY_REFLECTION, config=AOSConfig()
        )
        self.assertEqual(reward.reward, 0.0)
        self.assertEqual(reward.compared_cases, 1)

    def test_probability_floor_survives_repeated_negative_credit(self):
        aos = AdaptiveOperatorSelection(AOSConfig())
        for _ in range(12):
            record = aos.update_generation([
                OperatorReward(
                    STRATEGY_REFLECTION, "p", "c", -1.0, True, False,
                )
            ])
        self.assertGreaterEqual(record["post_update_probabilities"][GENERATE_CODE_REFLECTION], 0.10)
        self.assertGreaterEqual(record["post_update_probabilities"][STRATEGY_REFLECTION], 0.10)
        self.assertAlmostEqual(sum(record["post_update_probabilities"].values()), 1.0)

    def test_generation_update_uses_batch_rewards_and_records_stats(self):
        aos = AdaptiveOperatorSelection(AOSConfig())
        before = dict(aos.probabilities)
        selected = [aos.select_operator(random.Random(seed)) for seed in range(20)]
        record = aos.update_generation([
            OperatorReward(
                operator, "p", f"c-{index}", 1.0, True, True,
                transition="runnable_parent_to_runnable_child",
            )
            for index, operator in enumerate(selected)
        ])
        self.assertEqual(record["selection_probabilities"], before)
        self.assertEqual(
            record["operators"][STRATEGY_REFLECTION]["usage_count"],
            selected.count(STRATEGY_REFLECTION),
        )
        self.assertEqual(
            record["operators"][GENERATE_CODE_REFLECTION]["usage_count"],
            selected.count(GENERATE_CODE_REFLECTION),
        )
        self.assertAlmostEqual(sum(record["post_update_probabilities"].values()), 1.0)
        self.assertEqual(
            record["cumulative_transition_counts"]["runnable_parent_to_runnable_child"],
            20,
        )

    def test_initial_probabilities_can_be_configured(self):
        config = AOSConfig.from_mapping({
            "initial_probabilities": {
                "strategy_reflection": 0.60,
                "generate_code_reflection": 0.40,
            },
            "min_probability": 0.10,
            "credit": {"alpha": 0.3},
        })
        aos = AdaptiveOperatorSelection(config)
        self.assertEqual(aos.probabilities, {
            STRATEGY_REFLECTION: 0.60,
            GENERATE_CODE_REFLECTION: 0.40,
        })
        self.assertEqual(config.credit_alpha, 0.3)


if __name__ == "__main__":
    unittest.main()
