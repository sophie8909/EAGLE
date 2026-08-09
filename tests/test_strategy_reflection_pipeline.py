from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.mutation import ReflectionContext
from eagle.strategy_reflection import MockRoleBackend, StrategyReflectionMutation
from evaluation.match_logs import iter_match_log, write_match_log
from evaluation.microrts_runner import write_mock_round_state


class StrategyReflectionPipelineTests(unittest.TestCase):
    def test_commentator_manager_coach_delete_trace_and_preserve_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            for tick in range(4):
                write_mock_round_state(states, tick=tick, p0_resource=10 + tick, p1_resource=10)
            log_path = root / "match_log.jsonl.gz"
            write_match_log(
                log_path,
                metadata={
                    "match_id": "match-1",
                    "candidate_id": "candidate-1",
                    "generation_index": 1,
                    "candidate_side": "p0",
                    "opponent_name": "LightRush",
                    "opponent_agent": "ai.abstraction.LightRush",
                    "map_name": "maps/8x8/basesWorkers8x8.xml",
                    "map_width": 8,
                    "map_height": 8,
                    "round_index": 0,
                    "seed": 7,
                },
                round_state_dir=states,
                raw_result={"final_tick": 3, "players": {"p0": {"resource_total": 13}, "p1": {"resource_total": 10}}},
                tick_limit=3,
            )
            self.assertEqual([item["tick"] for item in iter_match_log(log_path)], [0, 1, 2, 3])
            candidate = Candidate(id="candidate-1", generation=1, strategy_prompt="Open with workers and defend the base.")
            context = ReflectionContext(
                generation=1,
                index=0,
                candidate_id=candidate.id,
                aggregate_game_performance=12.0,
                per_match_results=({
                    "match_id": "match-1",
                    "match_index": 0,
                    "match_log_path": str(log_path),
                    "opponent_name": "LightRush",
                    "map_name": "maps/8x8/basesWorkers8x8.xml",
                    "candidate_side": "p0",
                },),
            )
            mutation = StrategyReflectionMutation(MockRoleBackend(), max_attempts=2)
            result = mutation.run(candidate, context, artifact_dir=root / "child")

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manager)
            self.assertIsNotNone(result.coach)
            self.assertFalse(log_path.exists())
            self.assertTrue((root / "child" / "commentary" / "match-1" / "match_analysis.json").exists())
            self.assertTrue((root / "child" / "commentary" / "match-1" / "commentary_status.json").exists())
            self.assertTrue((root / "child" / "reflection" / "manager_analysis.json").exists())
            self.assertTrue((root / "child" / "reflection" / "coach_result.json").exists())
            self.assertNotIn("match_log", json.loads((root / "child" / "reflection" / "manager_request.json").read_text(encoding="utf-8"))["prompt"])
            self.assertIn("If the first combat group is ready", result.candidate.strategy_prompt)

    def test_commentary_failure_deletes_trace_without_changing_candidate(self) -> None:
        class BadBackend:
            def generate(self, prompt: str) -> str:
                return "not json"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
            log_path = root / "match_log.jsonl.gz"
            write_match_log(log_path, metadata={"match_id": "match-2"}, round_state_dir=states, raw_result={}, tick_limit=0)
            candidate = Candidate(id="candidate-2", strategy_prompt="Keep the base safe.")
            context = ReflectionContext(generation=1, index=0, candidate_id=candidate.id, per_match_results=({"match_id": "match-2", "match_log_path": str(log_path)},))
            result = StrategyReflectionMutation(BadBackend(), max_attempts=1).run(candidate, context, artifact_dir=root / "child")

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.candidate.strategy_prompt, candidate.strategy_prompt)
            self.assertFalse(log_path.exists())
            self.assertTrue((root / "child" / "reflection" / "commentary_failure.json").exists())


if __name__ == "__main__":
    unittest.main()
