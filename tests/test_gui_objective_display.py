"""Regression tests for GUI objective summary state."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.config import load_config_payload
from eagle_ui import services
from eagle_ui.state import AppState


class GuiObjectiveDisplayTests(unittest.TestCase):
    def test_active_objective_display_uses_selected_objective_not_fitness_metric(self) -> None:
        state = AppState()
        state.config.eval_mode = "gameplay"
        state.config.fitness_metric = "win_score"
        state.objectives.mode = "single"
        state.objectives.single_objective = "resource_advantage"
        state.objectives.selected = {"resource_advantage"}

        self.assertEqual(services.active_objective_display(state), "resource_advantage")

    def test_load_run_config_refreshes_displayed_objective(self) -> None:
        state = AppState()
        state.config.fitness_metric = "win_score"
        state.objectives.mode = "single"
        state.objectives.single_objective = "win_score"
        state.objectives.selected = {"win_score"}

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "config.json").write_text(
                json.dumps(
                    {
                        "application": "microrts",
                        "algorithm": "ga",
                        "evaluator": "gameplay",
                        "fitness_metric": "win_score",
                        "llm_call_limit": 100,
                        "objective_config": {"mode": "single", "objective": "resource_advantage"},
                    }
                ),
                encoding="utf-8",
            )

            services.load_run_config_into_state(state, run_dir)

        self.assertEqual(state.objectives.single_objective, "resource_advantage")
        self.assertEqual(services.active_objective_display(state), "resource_advantage")
        self.assertEqual(state.config.fitness_metric, "win_score")

    def test_algorithm_sync_forces_single_objective_mode(self) -> None:
        state = AppState()
        state.config.algorithm = "ga"
        state.objectives.mode = "multi"
        state.objectives.single_objective = "resource_advantage"
        state.objectives.selected = {"resource_advantage", "win_score"}

        services.sync_algorithm_defaults(state)

        self.assertEqual(state.objectives.mode, "single")
        self.assertEqual(state.objectives.selected, {"resource_advantage"})

    def test_algorithm_sync_forces_multi_objective_mode(self) -> None:
        state = AppState()
        state.config.algorithm = "nsga2"
        state.objectives.mode = "single"
        state.objectives.single_objective = "resource_advantage"
        state.objectives.selected = {"resource_advantage"}

        services.sync_algorithm_defaults(state)

        self.assertEqual(state.objectives.mode, "multi")
        self.assertGreaterEqual(len(state.objectives.selected), 2)
        self.assertIn("resource_advantage", state.objectives.selected)

    def test_backend_preserves_objective_when_forcing_single_objective_mode(self) -> None:
        config = load_config_payload(
            {
                "application": "microrts",
                "algorithm": "ga",
                "component_pool_path": "eagle/prompts/components.json",
                "objective_config": {
                    "mode": "multi",
                    "objectives": ["resource_advantage", "win_score"],
                },
            },
            validate=True,
        )

        self.assertEqual(config.objective_config, {"mode": "single", "objective": "resource_advantage"})

    def test_reflection_operator_comes_from_registry_payload(self) -> None:
        state = AppState()
        state.config.algorithm = "nsga2"
        state.config.component_pool_path = "eagle/prompts/components.json"
        state.operators.reflection_operator = "round_reflection"

        payload = services.build_config_payload(state)

        self.assertIn("round_reflection", services.operator_choices("reflection"))
        self.assertEqual(payload["reflection_operator"], "round_reflection")

    def test_surrogate_mode_is_none_for_non_surrogate_algorithm(self) -> None:
        state = AppState()
        state.config.algorithm = "ga"
        state.config.surrogate = "early_end"

        services.sync_algorithm_defaults(state)

        self.assertEqual(state.config.surrogate, "none")

    def test_surrogate_algorithm_uses_plugin_default_surrogate(self) -> None:
        state = AppState()
        state.config.algorithm = "ga_surrogate"
        state.config.surrogate = "none"

        services.sync_algorithm_defaults(state)

        self.assertEqual(state.config.surrogate, "early_end")


if __name__ == "__main__":
    unittest.main()
