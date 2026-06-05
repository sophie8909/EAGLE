"""Regression tests for Analysis run config summaries."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle_ui import services


class AnalysisRunConfigSummaryTests(unittest.TestCase):
    def test_load_run_config_summary_reads_selected_run_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "config.json").write_text(
                json.dumps(
                    {
                        "algorithm": "ga",
                        "evaluator": "gameplay",
                        "eval_mode": "full_game",
                        "surrogate": "none",
                        "population_size": 7,
                        "num_generations": 11,
                        "gameplay_map_dir": "16x16",
                        "gameplay_opponents": ["ai.RandomAI"],
                        "llm_call_limit": 23,
                        "objective_config": {"mode": "single", "objective": "resource_advantage"},
                    }
                ),
                encoding="utf-8",
            )

            summary = services.load_run_config_summary(run_dir)

        rows = {row["field"]: row["value"] for row in summary["rows"]}
        self.assertIn("config.json", summary["status"])
        self.assertEqual(rows["algorithm"], "ga")
        self.assertEqual(rows["objective mode"], "single")
        self.assertEqual(rows["objective / objectives"], "resource_advantage")
        self.assertEqual(rows["eval mode"], "full_game")
        self.assertEqual(rows["surrogate mode"], "none")
        self.assertEqual(rows["population size"], "7")
        self.assertEqual(rows["generations"], "11")
        self.assertEqual(rows["map"], "16x16")
        self.assertEqual(rows["opponent"], "ai.RandomAI")
        self.assertEqual(rows["llm call limit"], "23")

    def test_load_run_config_summary_switches_between_run_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_a = root / "run_a"
            run_b = root / "run_b"
            run_a.mkdir()
            run_b.mkdir()
            (run_a / "config.json").write_text(
                json.dumps(
                    {
                        "algorithm": "ga",
                        "objective_config": {"mode": "single", "objective": "resource_advantage"},
                    }
                ),
                encoding="utf-8",
            )
            (run_b / "config.json").write_text(
                json.dumps(
                    {
                        "algorithm": "nsga2",
                        "objective_config": {"mode": "multi", "objectives": ["win_score", "resource_advantage"]},
                    }
                ),
                encoding="utf-8",
            )

            rows_a = {
                row["field"]: row["value"]
                for row in services.load_run_config_summary(run_a)["rows"]
            }
            rows_b = {
                row["field"]: row["value"]
                for row in services.load_run_config_summary(run_b)["rows"]
            }

        self.assertEqual(rows_a["algorithm"], "ga")
        self.assertEqual(rows_a["objective / objectives"], "resource_advantage")
        self.assertEqual(rows_b["algorithm"], "nsga2")
        self.assertEqual(rows_b["objective / objectives"], "win_score, resource_advantage")

    def test_load_run_config_summary_marks_missing_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = services.load_run_config_summary(Path(temp_dir))

        rows = {row["field"]: row["value"] for row in summary["rows"]}
        self.assertEqual(summary["status"], "Config not found for this run")
        self.assertEqual(rows["algorithm"], "N/A")
        self.assertEqual(rows["objective mode"], "N/A")
        self.assertNotEqual(rows["log path"], "N/A")

    def test_load_run_config_summary_supports_old_available_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "config.json").write_text(
                json.dumps(
                    {
                        "algorithm": "nsga2",
                        "population_size": 20,
                        "num_generations": 50,
                        "surrogate_mode": "light_rush_and_heavy_rush",
                        "real_eval_opponents": [],
                    }
                ),
                encoding="utf-8",
            )

            summary = services.load_run_config_summary(run_dir)

        rows = {row["field"]: row["value"] for row in summary["rows"]}
        self.assertEqual(rows["algorithm"], "nsga2")
        self.assertEqual(rows["surrogate mode"], "light_rush_and_heavy_rush")
        self.assertEqual(rows["opponent"], "(none)")
        self.assertEqual(rows["objective mode"], "N/A")
        self.assertEqual(rows["eval mode"], "N/A")
        self.assertEqual(rows["llm call limit"], "N/A")


if __name__ == "__main__":
    unittest.main()
