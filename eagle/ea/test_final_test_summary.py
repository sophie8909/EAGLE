"""Tests for final-test result summarization."""

from __future__ import annotations

import unittest

from eagle.ea.final_test_summary import format_final_test_summary, summarize_final_test_results


class FinalTestSummaryTests(unittest.TestCase):
    """Verify aggregation over final-test replay records."""

    def test_summarize_final_test_results(self) -> None:
        payload = {
            "results": {
                "ind-a": [
                    {"opponent": "ai.RandomAI", "result": "Win", "fitness": [1.0, 0.2]},
                    {"opponent": "ai.PassiveAI", "result": "Loss", "fitness": [0.0, 0.3]},
                ],
                "ind-b": [
                    {"opponent": "ai.RandomAI", "fitness": [0.5, 0.4]},
                ],
            }
        }

        summary = summarize_final_test_results(payload)

        self.assertEqual(summary["individual_count"], 2)
        self.assertEqual(summary["total_matches"], 3)
        self.assertEqual(summary["overall"]["Win"], 1)
        self.assertEqual(summary["overall"]["Loss"], 1)
        self.assertEqual(summary["overall"]["Draw"], 1)
        self.assertEqual(summary["by_opponent"]["ai.RandomAI"]["total"], 2)
        self.assertEqual(summary["by_individual"]["ind-a"]["Win"], 1)

    def test_format_final_test_summary(self) -> None:
        summary = {
            "individual_count": 1,
            "total_matches": 2,
            "overall": {"Win": 1, "Loss": 1, "Draw": 0, "Unknown": 0},
            "by_opponent": {
                "ai.RandomAI": {"Win": 1, "Loss": 0, "Draw": 0, "Unknown": 0, "total": 1},
                "ai.PassiveAI": {"Win": 0, "Loss": 1, "Draw": 0, "Unknown": 0, "total": 1},
            },
            "by_individual": {
                "ind-a": {"Win": 1, "Loss": 1, "Draw": 0, "Unknown": 0, "total": 2},
            },
        }

        rendered = format_final_test_summary(summary)

        self.assertIn("Final Test Summary", rendered)
        self.assertIn("Overall: W=1 L=1 D=0 U=0", rendered)
        self.assertIn("- ai.RandomAI: W=1 L=0 D=0 U=0 Total=1", rendered)
        self.assertIn("- ind-a: W=1 L=1 D=0 U=0 Total=2", rendered)


if __name__ == "__main__":
    unittest.main()
