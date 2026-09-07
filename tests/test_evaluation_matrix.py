from __future__ import annotations

import unittest

from eagle.config import ExperimentConfig
from evaluation.match_matrix import MatrixOpponent, build_match_matrix, canonical_evaluation_maps


MAPS_WITH_TICK_LIMITS = [
    {"path": "maps/8x8/basesWorkers8x8.xml", "tick_limit": 1500},
    {"path": "maps/16x16/basesWorkers16x16.xml", "tick_limit": 3000},
    {"path": "maps/24x24/basesWorkers24x24.xml", "tick_limit": 4000},
]


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

    def test_map_specific_tick_limits_are_copied_to_every_match(self):
        matrix = build_match_matrix(
            [MatrixOpponent("opponent")],
            canonical_evaluation_maps(
                ("map-a", "map-b", "map-c"),
                tick_limits=(1500, 3000, 4000),
            ),
        )

        self.assertEqual([item.tick_limit for item in matrix[:6]], [1500] * 6)
        self.assertEqual([item.tick_limit for item in matrix[6:12]], [3000] * 6)
        self.assertEqual([item.tick_limit for item in matrix[12:]], [4000] * 6)

    def test_config_parses_and_serializes_map_specific_tick_limits(self):
        config = ExperimentConfig.from_mapping({
            "tick_limit": 999,
            "evaluation": {"maps": MAPS_WITH_TICK_LIMITS},
        })

        config.validate()
        self.assertEqual(config.resolved_evaluation_map_tick_limits, (1500, 3000, 4000))
        self.assertEqual(config.to_mapping()["evaluation"]["maps"], MAPS_WITH_TICK_LIMITS)

    def test_string_map_entries_keep_the_global_tick_limit_fallback(self):
        config = ExperimentConfig.from_mapping({
            "tick_limit": 777,
            "evaluation": {"maps": [item["path"] for item in MAPS_WITH_TICK_LIMITS]},
        })

        self.assertEqual(config.resolved_evaluation_map_tick_limits, (777, 777, 777))

    def test_nonpositive_map_tick_limit_is_rejected(self):
        invalid_maps = [dict(item) for item in MAPS_WITH_TICK_LIMITS]
        invalid_maps[1]["tick_limit"] = 0
        config = ExperimentConfig.from_mapping({"evaluation": {"maps": invalid_maps}})

        with self.assertRaisesRegex(ValueError, "map tick limits must be at least 1"):
            config.validate()


if __name__ == "__main__":
    unittest.main()
