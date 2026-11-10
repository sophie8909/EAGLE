from __future__ import annotations

import unittest

from scripts.plot_all_candidate_fixed_convergence import aggregate


class AllCandidateConvergenceTests(unittest.TestCase):
    def test_aggregate_produces_five_requested_statistics(self):
        records = [
            {"treatment": "A", "seed": 8, "generation": 0, "mean_match_score": 1.0},
            {"treatment": "A", "seed": 8, "generation": 0, "mean_match_score": 3.0},
            {"treatment": "A", "seed": 9, "generation": 0, "mean_match_score": 2.0},
            {"treatment": "A", "seed": 9, "generation": 0, "mean_match_score": 4.0},
        ]

        row = aggregate(records)[0]

        self.assertEqual(row["all_individuals_mean"], 2.5)
        self.assertEqual(row["mean_of_seed_best"], 3.5)
        self.assertEqual(row["mean_of_seed_worst"], 1.5)
        self.assertEqual(row["best_seed_mean"], 3.0)
        self.assertEqual(row["worst_seed_mean"], 2.0)


if __name__ == "__main__":
    unittest.main()
