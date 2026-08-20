from __future__ import annotations

import unittest

from eagle.final_test import (
    FINAL_TEST_GAMES_PER_SIDE,
    FINAL_TEST_OPPONENTS,
    _empty_cell,
    _markdown_table,
)


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
