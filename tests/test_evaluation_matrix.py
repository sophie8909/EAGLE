from __future__ import annotations

import unittest

from evaluation.match_matrix import MatrixOpponent, build_match_matrix, canonical_evaluation_maps


class EvaluationMatrixTests(unittest.TestCase):
    def test_one_opponent_has_three_maps_three_rounds_and_both_sides(self):
        matrix = build_match_matrix(
            [MatrixOpponent("opponent", 2.0)],
            canonical_evaluation_maps(("map-a", "map-b", "map-c")),
        )
        self.assertEqual(len(matrix), 18)
        self.assertEqual(
            [(item.map_id, item.round_index, item.candidate_player) for item in matrix[:6]],
            [("map_1", 0, 0), ("map_1", 0, 1),
             ("map_1", 1, 0), ("map_1", 1, 1),
             ("map_1", 2, 0), ("map_1", 2, 1)],
        )
        self.assertEqual([(item.candidate_player, item.opponent_player) for item in matrix[::2]], [(0, 1)] * 9)

    def test_order_is_stable_across_opponents(self):
        kwargs = dict(maps=canonical_evaluation_maps(("a", "b", "c")))
        first = build_match_matrix([MatrixOpponent("a"), MatrixOpponent("b")], **kwargs)
        second = build_match_matrix([MatrixOpponent("a"), MatrixOpponent("b")], **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 36)
        self.assertEqual(first[18].opponent_id, "b")


if __name__ == "__main__":
    unittest.main()
