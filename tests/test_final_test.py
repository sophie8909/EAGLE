from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.final_test import (
    FINAL_TEST_GAMES_PER_SIDE,
    FINAL_TEST_OPPONENTS,
    _build_summary,
    _empty_cell,
    _markdown_table,
    _select_candidate,
)
from eagle.opponents import SAFE_ALLINBOT_CLASS_NAME


class FinalTestTests(unittest.TestCase):
    def test_roster_keeps_ea_opponents_and_adds_diagnostics(self):
        ids = [item.opponent_id for item in FINAL_TEST_OPPONENTS]
        self.assertEqual(
            ids,
            [
                "lightrush", "heavyrush", "workerrush", "allinbot",
                "mayari", "coac", "tma", "passive", "random", "randombias",
            ],
        )
        self.assertEqual(FINAL_TEST_GAMES_PER_SIDE, 10)
        self.assertEqual(
            next(item.class_name for item in FINAL_TEST_OPPONENTS if item.opponent_id == "allinbot"),
            SAFE_ALLINBOT_CLASS_NAME,
        )

    def test_markdown_table_contains_wins_losses_draws_and_side_breakdown(self):
        cell = _empty_cell()
        cell["wins"] = 11
        cell["losses"] = 7
        cell["draws"] = 2
        cell["p0"] = {"win": 6, "loss": 3, "draw": 1, "error": 0}
        cell["p1"] = {"win": 5, "loss": 4, "draw": 1, "error": 0}
        summary = {
            "candidate": {"candidate_id": "candidate-a"},
            "games_per_side_per_map": 10,
            "maps": [{"id": "map_1"}],
            "opponents": [{"id": "lightrush", "name": "LightRush"}],
            "table": {"lightrush": {"map_1": cell}},
        }
        table = _markdown_table(summary)
        self.assertIn("W/L/D/E", table)
        self.assertIn("11/7/2/0", table)
        self.assertIn("p0 6/3/1", table)
        self.assertIn("p1 5/4/1", table)

    def test_summary_counts_contained_opponent_fault_as_neutral_draw(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = _build_summary(
                config=ExperimentConfig.from_mapping({}),
                run_dir=Path(directory),
                output_dir=Path(directory),
                candidate={"candidate_id": "candidate-a"},
                integration=type("Integration", (), {"to_json_dict": lambda self: {}})(),
                results=[
                    {
                        "opponent_id": "allinbot",
                        "map_id": "map_1",
                        "candidate_player": 0,
                        "result": "draw",
                        "opponent_fault_contained": True,
                        "opponent_fault_recovered": True,
                    }
                ],
            )

        cell = summary["table"]["allinbot"]["map_1"]
        self.assertEqual(cell["draws"], 1)
        self.assertEqual(cell["opponent_fault_contained"], 1)
        self.assertEqual(cell["opponent_fault_recovered"], 1)
        self.assertEqual(summary["opponent_fault_contained_matches"], 1)

    def test_summary_best_candidate_does_not_override_failed_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "manifest.json").write_text(
                json.dumps({"latest_generation": 2}),
                encoding="utf-8",
            )
            generation_dir = run_dir / "generations"
            generation_dir.mkdir()
            (generation_dir / "generation_0001.json").write_text(
                json.dumps({
                    "population": [
                        {"candidate_id": "fallback-candidate", "status": "evaluated"},
                    ]
                }),
                encoding="utf-8",
            )
            (generation_dir / "generation_0002.json").write_text(
                json.dumps({
                    "population": [
                        {"candidate_id": "failed-candidate", "status": "failed"},
                    ]
                }),
                encoding="utf-8",
            )
            (run_dir / "summary.json").write_text(
                json.dumps({"best_candidate": {"candidate_id": "failed-candidate"}}),
                encoding="utf-8",
            )
            fallback_classes = run_dir / "classes" / "fallback-candidate" / "ai" / "generated"
            fallback_classes.mkdir(parents=True)
            (fallback_classes / "CandidateAgent.class").write_bytes(b"compiled")
            fallback_candidate = run_dir / "candidates" / "fallback-candidate"
            (fallback_candidate / "phenotype").mkdir(parents=True)
            (fallback_candidate / "phenotype" / "CandidateAgent.java").write_text("class CandidateAgent {}", encoding="utf-8")

            selected = _select_candidate(run_dir, None)

            self.assertEqual(selected["candidate_id"], "fallback-candidate")
