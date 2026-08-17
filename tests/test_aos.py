from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.aos import (
    AOSConfig,
    AdaptiveOperatorSelection,
    GENERATE_CODE_REFLECTION,
    STRATEGY_REFLECTION,
    OperatorReward,
    calculate_operator_reward,
)
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.opponent_cases import LEXICASE_CASES
from eagle.search import apply_aos_rewards
from eagle.selection import lexicase_select


def evaluated_candidate(candidate_id: str, *, runnable: bool = True, generation: int = 0) -> Candidate:
    return Candidate(
        id=candidate_id,
        generation=generation,
        generated_java="package ai.generated; public class CandidateAgent {}" if runnable else "",
        compile_status="success" if runnable else "failed",
        status="evaluated" if runnable else "failed",
        failure_stage=None if runnable else "compilation",
        game_eval_result={
            "expected_match_count": 126,
            "completed_match_count": 126 if runnable else 0,
            "missing_match_count": 0 if runnable else 126,
        },
        fitness_objectives={case: 0.0 for case in LEXICASE_CASES},
    )


def direct_evidence(*, wins: int, draws: int, losses: int, errors: int = 0) -> dict:
    valid = wins + draws + losses
    return {
        "reward": 0.0 if valid == 0 else (wins + 0.5 * draws) / valid,
        "total_matches": valid + errors,
        "valid_matches": valid,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "errors": errors,
    }


class AdaptiveOperatorSelectionTests(unittest.TestCase):
    def test_initial_probabilities_are_code_biased(self):
        aos = AdaptiveOperatorSelection(AOSConfig())
        self.assertEqual(aos.probability(STRATEGY_REFLECTION), 0.20)
        self.assertEqual(aos.probability(GENERATE_CODE_REFLECTION), 0.80)
        self.assertAlmostEqual(sum(aos.probabilities.values()), 1.0)

    def test_failed_offspring_gets_zero_without_head_to_head(self):
        reward = calculate_operator_reward(
            evaluated_candidate("parent"),
            evaluated_candidate("child", runnable=False, generation=1),
            operator=STRATEGY_REFLECTION,
            config=AOSConfig(),
        )
        self.assertEqual(reward.reward, 0.0)
        self.assertEqual(reward.reward_source, "execution_failure")
        self.assertEqual(reward.head_to_head, {})

    def test_direct_reward_is_independent_of_seven_case_fitness(self):
        parent = evaluated_candidate("parent")
        child = evaluated_candidate("child", generation=1)
        evidence = direct_evidence(wins=9, draws=0, losses=9)
        first = calculate_operator_reward(
            parent, child, operator=STRATEGY_REFLECTION, config=AOSConfig(), head_to_head=evidence
        )
        parent = Candidate(**{**parent.__dict__, "fitness_objectives": {case: 100.0 for case in LEXICASE_CASES}})
        child = Candidate(**{**child.__dict__, "fitness_objectives": {case: -100.0 for case in LEXICASE_CASES}})
        second = calculate_operator_reward(
            parent, child, operator=STRATEGY_REFLECTION, config=AOSConfig(), head_to_head=evidence
        )
        self.assertEqual(first.reward, 0.5)
        self.assertEqual(second.reward, first.reward)
        self.assertEqual(second.reward_source, "parent_vs_offspring")

    def test_same_seven_cases_still_drive_lexicase(self):
        low = evaluated_candidate("low")
        high = evaluated_candidate("high")
        low = Candidate(**{**low.__dict__, "fitness_objectives": {case: 0.0 for case in LEXICASE_CASES}})
        high = Candidate(**{**high.__dict__, "fitness_objectives": {case: 1.0 for case in LEXICASE_CASES}})
        self.assertEqual(lexicase_select([low, high], random.Random(7)).id, "high")

    def test_generation_update_applies_exact_ema(self):
        state = {
            "probabilities": {
                STRATEGY_REFLECTION: 0.5,
                GENERATE_CODE_REFLECTION: 0.5,
            },
            "credits": {
                STRATEGY_REFLECTION: 0.5,
                GENERATE_CODE_REFLECTION: 0.5,
            },
        }
        aos = AdaptiveOperatorSelection.from_state(AOSConfig(), state)
        record = aos.update_generation([
            OperatorReward(
                operator=STRATEGY_REFLECTION,
                comparison_parent_id="p",
                offspring_id="c",
                reward=1.0,
                reward_source="parent_vs_offspring",
                comparison_parent_runnable=True,
                offspring_runnable=True,
                head_to_head=direct_evidence(wins=18, draws=0, losses=0),
            )
        ])
        stats = record["operators"][STRATEGY_REFLECTION]
        self.assertEqual(stats["operator_quality_before"], 0.5)
        self.assertAlmostEqual(stats["operator_quality_after"], 0.6)

    def test_probability_floor_remains_point_one(self):
        aos = AdaptiveOperatorSelection(AOSConfig())
        for index in range(12):
            record = aos.update_generation([
                OperatorReward(
                    operator=STRATEGY_REFLECTION,
                    comparison_parent_id="p",
                    offspring_id=f"c-{index}",
                    reward=1.0,
                    reward_source="parent_vs_offspring",
                    comparison_parent_runnable=True,
                    offspring_runnable=True,
                ),
                OperatorReward(
                    operator=GENERATE_CODE_REFLECTION,
                    comparison_parent_id="p",
                    offspring_id=f"d-{index}",
                    reward=0.0,
                    reward_source="parent_vs_offspring",
                    comparison_parent_runnable=True,
                    offspring_runnable=True,
                ),
            ])
        self.assertEqual(record["post_update_probabilities"][GENERATE_CODE_REFLECTION], 0.10)
        self.assertEqual(record["post_update_probabilities"][STRATEGY_REFLECTION], 0.90)

    def test_failed_offspring_does_not_launch_direct_matches(self):
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
        parent = evaluated_candidate("parent")
        child = evaluated_candidate("child", runnable=False, generation=1)
        child = Candidate(**{
            **child.__dict__,
            "metadata": {"aos": {
                "generation": 1,
                "comparison_parent_id": parent.id,
                "offspring_id": child.id,
                "operator": "strategy",
                "operator_id": STRATEGY_REFLECTION,
            }},
        })
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "eagle.search.evaluate_parent_vs_offspring"
        ) as direct_match:
            _, rewards = apply_aos_rewards(
                [parent],
                [child],
                config=config,
                aos=AdaptiveOperatorSelection(config.aos),
                candidates_dir=Path(temp_dir) / "candidates",
                classes_dir=Path(temp_dir) / "classes",
                mock=True,
            )
        direct_match.assert_not_called()
        self.assertEqual(rewards[0].reward, 0.0)
        self.assertEqual(rewards[0].reward_source, "execution_failure")
        self.assertEqual(rewards[0].head_to_head["total_matches"], 0)
        self.assertEqual(rewards[0].head_to_head["skipped_reason"], "execution_failure")

    def test_initial_probabilities_can_be_configured(self):
        config = AOSConfig.from_mapping({
            "initial_probabilities": {
                "strategy_reflection": 0.60,
                "generate_code_reflection": 0.40,
            },
            "min_probability": 0.10,
            "credit": {"alpha": 0.3},
            "reward": {"execution_failure": 0.0},
        })
        aos = AdaptiveOperatorSelection(config)
        self.assertEqual(aos.probabilities, {
            STRATEGY_REFLECTION: 0.60,
            GENERATE_CODE_REFLECTION: 0.40,
        })
        self.assertEqual(config.credit_alpha, 0.3)


if __name__ == "__main__":
    unittest.main()
