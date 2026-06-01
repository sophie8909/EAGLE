"""Regression tests for objective eval-mode normalization."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from eagle.experiment.config import experiment_config_from_payload
from eagle.objectives.registry import objective_eval_mode, validate_objective_config


class ObjectiveEvalModeTests(unittest.TestCase):
    def test_explicit_gameplay_eval_mode_uses_full_game_objectives(self) -> None:
        config = SimpleNamespace(
            application="microrts",
            algorithm="ga",
            evaluator="gameplay",
            eval_mode="gameplay",
            objective_config={"mode": "single", "objective": "resource_advantage"},
        )

        self.assertEqual(objective_eval_mode(config), "full_game")
        self.assertEqual(
            validate_objective_config(config),
            {"mode": "single", "objective": "resource_advantage"},
        )

    def test_experiment_config_with_gameplay_eval_mode_loads(self) -> None:
        experiment = experiment_config_from_payload(
            {
                "algorithm": "ga",
                "evaluator": "gameplay",
                "ea": {
                    "eval_mode": "gameplay",
                    "objective_config": {"mode": "single", "objective": "resource_advantage"},
                },
            }
        )

        self.assertEqual(experiment.ea.eval_mode, "full_game")
        self.assertEqual(
            experiment.ea.objective_config,
            {"mode": "single", "objective": "resource_advantage"},
        )


if __name__ == "__main__":
    unittest.main()
