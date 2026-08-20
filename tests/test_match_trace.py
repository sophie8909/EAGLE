import gzip
import json
import tempfile
import unittest
from pathlib import Path

from evaluation.match_trace import iter_match_trace, write_match_trace
from evaluation.runtime_evaluation import write_mock_round_state


class MatchTraceTests(unittest.TestCase):
    def _metadata(self):
        return {"match_id": "m0", "candidate_side": "p1", "opponent_name": "passive", "map_name": "8x8", "map_width": None, "map_height": None}

    def test_every_quiet_tick_is_streamed_and_compressed(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            states = root / "states"
            for tick in range(4):
                write_mock_round_state(states, tick=tick, p0_resource=5, p1_resource=6)
            artifact = write_match_trace(round_state_dir=states, match_dir=root / "match", metadata=self._metadata(), result={"final_tick": 3, "winner": 1}, expected_last_tick=3)
            self.assertEqual([row["tick"] for row in iter_match_trace(artifact.trace_path)], [0, 1, 2, 3])
            self.assertEqual(artifact.integrity["recorded_tick_count"], 4)
            self.assertTrue(artifact.integrity["complete"])
            with gzip.open(artifact.trace_path, "rt", encoding="utf-8") as handle:
                self.assertTrue(handle.readline().startswith("{"))

    def test_static_metadata_and_both_players_are_separate_from_rows(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=5, p1_resource=6)
            artifact = write_match_trace(round_state_dir=states, match_dir=root / "match", metadata=self._metadata(), result={"final_tick": 0, "winner": 1}, expected_last_tick=0)
            metadata = json.loads(artifact.metadata_path.read_text())
            row = next(iter_match_trace(artifact.trace_path))
            self.assertEqual(len(row["players"]), 2)
            self.assertNotIn("terrain", row)
            self.assertIn("terrain", metadata)
            self.assertEqual(metadata["candidate_side"], "p1")
            self.assertIn("ROUND_TICK", row["raw_state"])

    def test_result_fallback_keeps_commentary_trace_nonempty(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            artifact = write_match_trace(
                round_state_dir=root / "missing-states",
                match_dir=root / "match",
                metadata=self._metadata(),
                result={
                    "final_tick": 7,
                    "winner": 0,
                    "players": {
                        "p0": {"resource_total": 9},
                        "p1": {"resource_total": 3},
                    },
                },
                expected_last_tick=7,
            )
            row = next(iter_match_trace(artifact.trace_path))
            self.assertEqual(row["tick"], 7)
            self.assertEqual(row["state_source"], "result_json_fallback")
            self.assertIsNone(row["raw_state"])
            self.assertTrue(artifact.integrity["complete"])

    def test_integrity_reports_missing_duplicate_and_out_of_order_ticks(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=5, p1_resource=6)
            write_mock_round_state(states, tick=2, p0_resource=5, p1_resource=6)
            artifact = write_match_trace(round_state_dir=states, match_dir=root / "match", metadata=self._metadata(), result={"final_tick": 3, "winner": 1}, expected_last_tick=3)
            self.assertFalse(artifact.integrity["complete"])
            self.assertEqual(artifact.integrity["missing_tick_ranges"], [{"start": 1, "end": 1}, {"start": 3, "end": 3}])

    def test_units_have_stable_order_and_optional_action_fields(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            states = root / "states"
            states.mkdir()
            (states / "round_000000.log").write_text("""ROUND_TICK: 0\nGAMEOVER: false\ncurrent time 0 p0 player 0(5) p1 player 1(6)\nMap size: 8x8\n(2,2) Ally Worker Unit {ID=2, HP=1, MaxHP=1, resources=3, action=move, eta=1}\n(1,1) Ally Base Unit {ID=1, HP=10, MaxHP=10, resources=0}\n(6,6) Enemy Base Unit {ID=3, HP=10, MaxHP=10, resources=0}\n""", encoding="utf-8")
            artifact = write_match_trace(round_state_dir=states, match_dir=root / "match", metadata=self._metadata(), result={"final_tick": 0, "winner": 0}, expected_last_tick=0)
            row = next(iter_match_trace(artifact.trace_path))
            self.assertEqual([unit["unit_id"] for unit in row["units"]], ["1", "2", "3"])
            self.assertEqual(row["units"][1]["current_action"], "move")
            self.assertEqual(row["units"][1]["action_remaining_time"], 1)


if __name__ == "__main__":
    unittest.main()
