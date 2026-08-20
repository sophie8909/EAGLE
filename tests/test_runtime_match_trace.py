from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evaluation.match_trace import iter_match_trace
from evaluation.runtime_evaluation import run_microrts_match


class RuntimeMatchTraceTests(unittest.TestCase):
    def test_mock_match_writes_bounded_endpoint_snapshots_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_microrts_match(
                microrts_dir=root,
                classes_dir=root / "classes",
                agent_class="ai.generated.CandidateAgent",
                opponent="ai.abstraction.LightRush",
                tick_limit=4,
                match_index=2,
                match_artifacts_dir=root / "matches",
                mock=True,
                mock_score=1.0,
                candidate_id="candidate-1",
                generation_index=3,
            )
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.trace_path)
            records = list(iter_match_trace(Path(result.trace_path)))
            self.assertEqual([record["tick"] for record in records], [0, 4])
            self.assertEqual({player["player_id"] for player in records[0]["players"]}, {0, 1})
            self.assertEqual(result.to_json_dict()["match_trace_path"], result.trace_path)


if __name__ == "__main__":
    unittest.main()
