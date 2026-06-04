"""Regression tests for GUI objective summary state."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
