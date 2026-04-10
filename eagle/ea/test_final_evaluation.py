"""Tests for final-evaluation interval scheduling and result formatting."""

from __future__ import annotations

import unittest

from eagle.ea.config import EAConfig
from eagle.ea.final_evaluation import _build_final_test_interval_runs
from eagle.ea.result_test import build_result_record


class FinalEvaluationTests(unittest.TestCase):
    """Verify final-test runs cover both requested interval settings."""

    def test_build_final_test_interval_runs_uses_config_and_interval_one(self) -> None:
        runs = _build_final_test_interval_runs(EAConfig(llm_interval=7))

        self.assertEqual(
            runs,
            [
                {"label": "config", "llm_interval": 7},
                {"label": "interval_1", "llm_interval": 1},
            ],
        )

    def test_build_result_record_uses_two_objective_schema(self) -> None:
        class DummyIndividual:
            id = "ind-1"

        record = build_result_record(
            DummyIndividual(),
            "ai.RandomAI",
            [1.0, 0.25],
            "fake.log",
        )

        self.assertEqual(record["result"], "Win")
        self.assertEqual(record["win_score"], 1.0)
        self.assertEqual(record["game_round_score"], 0.25)
        self.assertEqual(record["fitness"], [1.0, 0.25])


if __name__ == "__main__":
    unittest.main()
