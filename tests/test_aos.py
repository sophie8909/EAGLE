from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from eagle.aos import (
    AdaptiveOperatorSelection,
    AdaptiveOperatorSelector,
    GENERATE_CODE_REFLECTION,
    PROMPT_COMPLIANCE_REFLECTION,
    STRATEGY_REFLECTION,
    StaticOperatorSelector,
    OperatorReward,
    build_reflection_operator_controller,
    calculate_head_to_head_reward,
    calculate_opponent_reward,
    opponent_result_ranks,
)
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.opponent_cases import LEXICASE_CASES
from eagle.selection import lexicase_select


def evaluated_candidate(
    candidate_id: str,
    *,
    runnable: bool = True,
    generation: int = 0,
    ranks: dict[str, int] | None = None,
) -> Candidate:
    opponent_results = []
    for case in LEXICASE_CASES:
        rank = (ranks or {}).get(case, 1)
        wins, losses = {0: (0, 2), 1: (1, 1), 2: (2, 0)}[rank]
        opponent_results.append({
            "opponent_id": case,
            "status": "completed",
            "wins": wins,
            "draws": 0 if rank != 1 else 1,
            "losses": losses,
        })
    return Candidate(
        id=candidate_id,
        generation=generation,
        generated_java="package ai.generated; public class CandidateAgent {}" if runnable else "",
        compile_status="success" if runnable else "failed",
        status="evaluated" if runnable else "failed",
        failure_stage=None if runnable else "compilation",
        game_eval_result={
            "expected_match_count": 180,
            "completed_match_count": 180 if runnable else 0,
            "missing_match_count": 0 if runnable else 180,
            "opponent_results": opponent_results if runnable else [],
        },
        fitness_objectives={case: 0.0 for case in LEXICASE_CASES},
    )


def selected(child: Candidate, parent: Candidate, operator: str) -> Candidate:
    return Candidate(**{
        **child.__dict__,
        "metadata": {"aos": {
            "generation": child.generation,
            "comparison_parent_id": parent.id,
            "offspring_id": child.id,
            "operator": "strategy" if operator == STRATEGY_REFLECTION else "code",
            "operator_id": operator,
        }},
    })


def config_for(mode: str, **overrides) -> ExperimentConfig:
    payload = {
        "reflection_operator_mode": mode,
        "strategy_reflection_probability": 0.20,
        "code_reflection_probability": 0.80,
        "prompt_compliance_reflection_probability": 0.0,
        "aos_minimum_probability": 0.10,
        **overrides,
    }
    config = ExperimentConfig.from_mapping(payload)
    config.validate()
    return config


class ReflectionOperatorModeTests(unittest.TestCase):
    def test_static_selection_uses_fixed_config_and_never_updates(self):
        controller = build_reflection_operator_controller(config_for("static"))
        self.assertIsInstance(controller, StaticOperatorSelector)
        rng = random.Random(19)
        choices = [controller.select_operator(rng) for _ in range(20_000)]
        self.assertAlmostEqual(choices.count(STRATEGY_REFLECTION) / len(choices), 0.20, delta=0.015)

        before = dict(controller.probabilities)
        for _ in range(3):
            record = controller.update_generation([])
            self.assertEqual(controller.probabilities, before)
            self.assertEqual(record["reward_source"], "static")
            self.assertIsNone(record["strategy_reward"])
            self.assertIsNone(record["code_reward"])
            self.assertEqual(record["strategy_probability_before"], record["strategy_probability_after"])
            self.assertEqual(record["code_probability_before"], record["code_probability_after"])
            self.assertEqual(record["schema_version"], "eagle-reflection-operator-v4")
            self.assertIsNone(record["prompt_compliance_reward"])
            self.assertTrue({
                "mode", "reward_source",
                "strategy_probability_before", "code_probability_before",
                "prompt_compliance_probability_before",
                "strategy_probability_after", "code_probability_after",
                "prompt_compliance_probability_after",
                "strategy_reward", "code_reward", "prompt_compliance_reward",
            }.issubset(record))

    def test_operator_preconditions_condition_selection_and_usage_on_eligible_set(self):
        controller = build_reflection_operator_controller(config_for("static"))
        rng = random.Random(19)

        choices = [
            controller.select_operator(rng, eligible=(STRATEGY_REFLECTION,))
            for _ in range(20)
        ]

        self.assertEqual(choices, [STRATEGY_REFLECTION] * 20)
        record = controller.update_generation([])
        self.assertEqual(
            record["operators"][STRATEGY_REFLECTION]["usage_count"],
            20,
        )
        self.assertEqual(
            record["operators"][GENERATE_CODE_REFLECTION]["usage_count"],
            0,
        )

    def test_static_collects_no_reward_and_launches_no_head_to_head(self):
        config = config_for("static")
        controller = build_reflection_operator_controller(config)
        parent = evaluated_candidate("parent")
        child = selected(evaluated_candidate("child", generation=1), parent, STRATEGY_REFLECTION)
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.aos.evaluate_parent_vs_offspring"
        ) as direct_matches:
            updated, rewards = controller.collect_rewards(
                [parent], [child], config=config,
                candidates_dir=Path(directory), classes_dir=Path(directory), mock=True,
            )
        direct_matches.assert_not_called()
        self.assertEqual(updated, [child])
        self.assertEqual(rewards, [])

    def test_opponent_reward_restores_historical_rank_formula(self):
        parent_ranks = {case: 1 for case in LEXICASE_CASES}
        child_ranks = dict(parent_ranks)
        child_ranks[LEXICASE_CASES[0]] = 2
        child_ranks[LEXICASE_CASES[1]] = 2
        parent_ranks[LEXICASE_CASES[2]] = 2
        child_ranks[LEXICASE_CASES[2]] = 0
        reward = calculate_opponent_reward(
            evaluated_candidate("parent", ranks=parent_ranks),
            evaluated_candidate("child", generation=1, ranks=child_ranks),
            operator=STRATEGY_REFLECTION,
        )
        self.assertAlmostEqual(reward.reward, 1 / 10)
        self.assertEqual(reward.reward_source, "opponent")
        self.assertEqual(reward.opponent_comparison["improved_cases"], list(LEXICASE_CASES[:2]))
        self.assertEqual(reward.opponent_comparison["regressed_cases"], [LEXICASE_CASES[2]])
        self.assertEqual(reward.opponent_comparison["compared_cases"], 10)

    def test_opponent_rank_uses_wins_vs_losses_and_completed_rows_only(self):
        candidate = evaluated_candidate("candidate")
        rows = list(candidate.game_eval_result["opponent_results"])
        rows[0] = {"opponent_id": LEXICASE_CASES[0], "status": "completed", "wins": 4, "draws": 10, "losses": 4}
        rows[1] = {"opponent_id": LEXICASE_CASES[1], "status": "completed", "wins": 5, "draws": 0, "losses": 4}
        rows[2] = {"opponent_id": LEXICASE_CASES[2], "status": "failed", "wins": 18, "draws": 0, "losses": 0}
        candidate = Candidate(**{
            **candidate.__dict__,
            "game_eval_result": {**candidate.game_eval_result, "opponent_results": rows},
        })
        ranks = opponent_result_ranks(candidate)
        self.assertEqual(ranks[LEXICASE_CASES[0]], 1)
        self.assertEqual(ranks[LEXICASE_CASES[1]], 2)
        self.assertIsNone(ranks[LEXICASE_CASES[2]])

    def test_opponent_reward_preserves_execution_first_constants(self):
        cases = (
            (False, True, 1.0),
            (True, False, -1.0),
            (False, False, -0.1),
        )
        for parent_ok, child_ok, expected in cases:
            with self.subTest(parent_ok=parent_ok, child_ok=child_ok):
                reward = calculate_opponent_reward(
                    evaluated_candidate("parent", runnable=parent_ok),
                    evaluated_candidate("child", runnable=child_ok, generation=1),
                    operator=GENERATE_CODE_REFLECTION,
                )
                self.assertEqual(reward.reward, expected)

    def test_aos_opponent_uses_normal_evidence_without_direct_matches(self):
        config = config_for("aos_opponent")
        controller = build_reflection_operator_controller(config)
        self.assertIsInstance(controller, AdaptiveOperatorSelector)
        parent = evaluated_candidate("parent")
        child = selected(evaluated_candidate("child", generation=1), parent, STRATEGY_REFLECTION)
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.aos.evaluate_parent_vs_offspring"
        ) as direct_matches:
            _, rewards = controller.collect_rewards(
                [parent], [child], config=config,
                candidates_dir=Path(directory), classes_dir=Path(directory), mock=True,
            )
        direct_matches.assert_not_called()
        record = controller.update_generation(rewards)
        self.assertEqual(record["mode"], "aos_opponent")
        self.assertEqual(record["reward_source"], "opponent")
        self.assertAlmostEqual(record["operators"][STRATEGY_REFLECTION]["operator_quality_after"], 0.0)

    def test_aos_head2head_launches_configured_matrix_and_not_opponent_reward(self):
        config = config_for("aos_head2head")
        controller = build_reflection_operator_controller(config)
        parent = evaluated_candidate("parent")
        child = selected(evaluated_candidate("child", generation=1), parent, GENERATE_CODE_REFLECTION)
        direct_result = Mock(
            reward=0.5,
            to_dict=Mock(return_value={
                "maps": list(config.evaluation_maps),
                "rounds": list(range(config.rounds_per_map)),
                "sides": ["offspring_p0_parent_p1", "parent_p0_offspring_p1"],
                "total_matches": config.fixed_matches_per_opponent,
                "valid_matches": config.fixed_matches_per_opponent,
                "wins": 9, "draws": 0, "losses": 9, "errors": 0,
            }),
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.aos.evaluate_parent_vs_offspring", return_value=direct_result
        ) as direct_matches, patch(
            "eagle.aos.calculate_opponent_reward", side_effect=AssertionError("wrong provider")
        ):
            _, rewards = controller.collect_rewards(
                [parent], [child], config=config,
                candidates_dir=Path(directory), classes_dir=Path(directory), mock=True,
            )
        direct_matches.assert_called_once()
        self.assertEqual(rewards[0].reward, 0.5)
        self.assertEqual(rewards[0].reward_source, "head2head")
        self.assertEqual(rewards[0].head_to_head["total_matches"], 18)
        record = controller.update_generation(rewards)
        self.assertEqual(record["reward_source"], "head2head")
        self.assertAlmostEqual(record["operators"][GENERATE_CODE_REFLECTION]["operator_quality_after"], 0.1)

    def test_failed_head2head_offspring_gets_zero_without_direct_matches(self):
        config = config_for("aos_head2head")
        controller = build_reflection_operator_controller(config)
        parent = evaluated_candidate("parent")
        child = selected(
            evaluated_candidate("child", runnable=False, generation=1), parent, STRATEGY_REFLECTION
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.aos.evaluate_parent_vs_offspring"
        ) as direct_matches:
            _, rewards = controller.collect_rewards(
                [parent], [child], config=config,
                candidates_dir=Path(directory), classes_dir=Path(directory), mock=True,
            )
        direct_matches.assert_not_called()
        self.assertEqual(rewards[0].reward, 0.0)
        self.assertEqual(rewards[0].reward_reason, "execution_failure")

    def test_both_adaptive_modes_use_same_ema_updater_and_floor(self):
        controllers = [
            build_reflection_operator_controller(config_for(mode))
            for mode in ("aos_opponent", "aos_head2head")
        ]
        for controller in controllers:
            self.assertIsInstance(controller.updater, AdaptiveOperatorSelection)
            self.assertEqual(controller.updater.probabilities, {
                STRATEGY_REFLECTION: 0.20,
                GENERATE_CODE_REFLECTION: 0.80,
                PROMPT_COMPLIANCE_REFLECTION: 0.0,
            })
            for index in range(12):
                record = controller.update_generation([
                    OperatorReward(
                        operator=STRATEGY_REFLECTION,
                        comparison_parent_id="p", offspring_id=f"s-{index}", reward=1.0,
                        reward_source=controller.mode.reward_source,
                        comparison_parent_runnable=True, offspring_runnable=True,
                    ),
                    OperatorReward(
                        operator=GENERATE_CODE_REFLECTION,
                        comparison_parent_id="p", offspring_id=f"c-{index}", reward=0.0,
                        reward_source=controller.mode.reward_source,
                        comparison_parent_runnable=True, offspring_runnable=True,
                    ),
                ])
            self.assertEqual(record["code_probability_after"], 0.10)
            self.assertEqual(record["strategy_probability_after"], 0.90)

    def test_head_to_head_formula_remains_win_one_draw_half_loss_zero(self):
        evidence = {"reward": (6 + 0.5 * 6) / 18, "wins": 6, "draws": 6, "losses": 6}
        reward = calculate_head_to_head_reward(
            evaluated_candidate("parent"),
            evaluated_candidate("child", generation=1),
            operator=STRATEGY_REFLECTION,
            head_to_head=evidence,
        )
        self.assertEqual(reward.reward, 0.5)

    def test_same_ten_cases_still_drive_lexicase(self):
        low = evaluated_candidate("low")
        high = evaluated_candidate("high")
        low = Candidate(**{**low.__dict__, "fitness_objectives": {case: 0.0 for case in LEXICASE_CASES}})
        high = Candidate(**{**high.__dict__, "fitness_objectives": {case: 1.0 for case in LEXICASE_CASES}})
        self.assertEqual(lexicase_select([low, high], random.Random(7)).id, "high")


class ReflectionOperatorConfigTests(unittest.TestCase):
    def test_prompt_compliance_probability_is_canonical_and_legacy_alias_loads(self):
        canonical = config_for(
            "static",
            strategy_reflection_probability=0.0,
            code_reflection_probability=0.0,
            prompt_compliance_reflection_probability=1.0,
        )
        self.assertEqual(canonical.prompt_compliance_reflection_probability, 1.0)
        self.assertIn(
            "prompt_compliance_reflection_probability",
            canonical.to_mapping(),
        )
        self.assertNotIn("balance_reflection_probability", canonical.to_mapping())

        legacy = ExperimentConfig.from_mapping({
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
            "balance_reflection_probability": 1.0,
        })
        self.assertEqual(legacy.prompt_compliance_reflection_probability, 1.0)

        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            ExperimentConfig.from_mapping({
                "prompt_compliance_reflection_probability": 1.0,
                "balance_reflection_probability": 0.0,
            })

    def test_removed_balance_operator_state_cannot_resume_under_new_semantics(self):
        config = config_for("static")
        with self.assertRaisesRegex(ValueError, "removed Balance Reflection"):
            build_reflection_operator_controller(
                config,
                state={
                    "mode": "static",
                    "total_usage": {"balance_reflection": 4},
                },
            )

    def test_rejects_probabilities_that_do_not_sum_to_one(self):
        with self.assertRaisesRegex(ValueError, "must equal 1.0"):
            config_for(
                "static",
                strategy_reflection_probability=0.4,
                code_reflection_probability=0.4,
            )

    def test_rejects_operator_probability_outside_unit_interval(self):
        for strategy, code in ((-0.1, 1.1), (1.1, -0.1)):
            with self.subTest(strategy=strategy), self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
                config_for(
                    "static",
                    strategy_reflection_probability=strategy,
                    code_reflection_probability=code,
                )

    def test_rejects_invalid_mode(self):
        with self.assertRaisesRegex(ValueError, "reflection_operator_mode must be one of"):
            config_for("adaptive")

    def test_rejects_incompatible_adaptive_minimum(self):
        with self.assertRaisesRegex(ValueError, r"\[0, 0.5\]"):
            config_for("aos_opponent", aos_minimum_probability=0.6)

    def test_static_parses_but_ignores_aos_minimum(self):
        config = config_for("static", aos_minimum_probability=0.6)
        controller = build_reflection_operator_controller(config)
        self.assertEqual(controller.probabilities[STRATEGY_REFLECTION], 0.2)

    def test_rejects_obsolete_nested_aos_config(self):
        with self.assertRaisesRegex(ValueError, "nested aos config is obsolete"):
            ExperimentConfig.from_mapping({"aos": {}})

    def test_production_config_explicitly_uses_head_to_head_defaults(self):
        config = ExperimentConfig.from_file(
            Path(__file__).resolve().parents[1] / "configs" / "experiments" / "qwen3_5_9b" / "experiment.yaml"
        )
        self.assertEqual(config.reflection_operator_mode.value, "aos_head2head")
        self.assertEqual(config.strategy_reflection_probability, 0.20)
        self.assertEqual(config.code_reflection_probability, 0.80)
        self.assertEqual(config.aos_minimum_probability, 0.10)


if __name__ == "__main__":
    unittest.main()
