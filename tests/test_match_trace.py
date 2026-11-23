import gzip
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from eagle.evaluation.game_performance import build_match_telemetry
from eagle.evaluation.match_trace import iter_match_trace, write_match_trace
from eagle.evaluation.round_states import ROUND_STATE_STREAM_NAME, read_round_state_stream, require_buffered_round_states
from eagle.evaluation.runtime_evaluation import write_mock_round_state


class MatchTraceTests(unittest.TestCase):
    def test_compact_preflight_rejects_a_stale_game_class(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            game = root / "bin/rts/Game.class"
            game.parent.mkdir(parents=True)
            game.write_bytes(b"microrts.round_state_dir")
            with self.assertRaisesRegex(ValueError, "lacks buffered round-state support"):
                require_buffered_round_states(root)

    @unittest.skipUnless(shutil.which("java"), "requires Java")
    def test_compiled_microrts_writes_one_buffered_stream_with_all_ticks(self):
        microrts = Path(__file__).resolve().parents[1] / "third_party/microrts"
        if not (microrts / "bin/rts/Game.class").is_file():
            self.skipTest("requires compiled MicroRTS")
        require_buffered_round_states(microrts)
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            states = root / "round_states"
            classpath = os.pathsep.join(str(microrts / path) for path in ("bin", "lib/*"))
            command = [
                "java", "-Dmicrorts.round_state_stream=true", f"-Dmicrorts.round_state_dir={states}",
                "-cp", classpath, "rts.MicroRTS", "-l", "STANDALONE", "--headless", "true",
                "-m", "maps/8x8/basesWorkers8x8.xml", "-c", "12", "-i", "0",
                "--ai1", "ai.PassiveAI", "--ai2", "ai.PassiveAI", "--result-json", str(root / "result.json"),
            ]
            result = subprocess.run(command, cwd=microrts, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([path.name for path in states.iterdir()], [ROUND_STATE_STREAM_NAME])
            snapshots = list(read_round_state_stream(states / ROUND_STATE_STREAM_NAME))
            self.assertEqual([name for name, _ in snapshots], [f"round_{tick:06d}.log" for tick in range(13)])

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

    def test_compact_snapshot_stream_matches_legacy_files_and_retains_complete_prefix(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            states = root / "states"
            for tick in range(3):
                write_mock_round_state(states, tick=tick, p0_resource=5 + tick, p1_resource=6)
            stream_path = states / ROUND_STATE_STREAM_NAME
            with stream_path.open("wb") as handle:
                for tick, path in enumerate(sorted(states.glob("round_*.log"))):
                    payload = path.read_text(encoding="utf-8").encode("utf-8")
                    handle.write(struct.pack(">II", tick, len(payload)) + payload)
                handle.write(struct.pack(">II", 3, 100) + b"interrupted frame")
            snapshots = list(read_round_state_stream(stream_path))
            self.assertEqual([name for name, _ in snapshots], [
                "round_000000.log", "round_000001.log", "round_000002.log",
            ])

            result = {"final_tick": 2, "winner": 1}
            telemetry_args = {
                "raw_result": result, "round_state_dir": states, "max_tick": 10, "player_index": 1,
            }
            self.assertEqual(
                build_match_telemetry(**telemetry_args, snapshots=snapshots),
                build_match_telemetry(**telemetry_args),
            )
            trace_args = {
                "round_state_dir": states, "metadata": {**self._metadata(), "start_timestamp": "fixed"},
                "result": result,
            }
            legacy = write_match_trace(match_dir=root / "legacy", **trace_args)
            compact = write_match_trace(match_dir=root / "compact", snapshots=snapshots, **trace_args)
            self.assertEqual(list(iter_match_trace(compact.trace_path)), list(iter_match_trace(legacy.trace_path)))
            self.assertEqual(compact.integrity, legacy.integrity)
            self.assertTrue(compact.integrity["complete"])
            interrupted = write_match_trace(
                match_dir=root / "interrupted", snapshots=snapshots, expected_last_tick=3,
                **{**trace_args, "result": {}},
            )
            self.assertEqual(interrupted.integrity["missing_tick_ranges"], [{"start": 3, "end": 3}])

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

    def test_result_write_can_be_deferred_to_canonical_match_persistence(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            artifact = write_match_trace(
                round_state_dir=root / "missing-states",
                match_dir=root / "match",
                metadata=self._metadata(),
                result={"final_tick": 0, "winner": 0},
                expected_last_tick=0,
                write_result=False,
            )
            self.assertFalse(artifact.result_path.exists())
            self.assertTrue(artifact.trace_path.exists())

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
