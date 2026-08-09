from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evaluation.match_logs import iter_match_log
from evaluation.microrts_runner import run_microrts_match


class MatchLoggingTests(unittest.TestCase):
    def test_mock_match_writes_every_tick_and_metadata(self) -> None:
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
                seed=17,
                candidate_id="candidate-1",
                generation_index=3,
            )
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.match_log_path)
            records = list(iter_match_log(Path(result.match_log_path)))
            self.assertEqual([record["tick"] for record in records], [0, 1, 2, 3, 4])
            self.assertEqual({player["player_id"] for player in records[0]["players"]}, {"p0", "p1"})
            self.assertEqual(records[0]["metadata"]["candidate_id"], "candidate-1")
            self.assertEqual(records[0]["metadata"]["generation_index"], 3)
            self.assertEqual(result.to_json_dict()["match_log_path"], result.match_log_path)


if __name__ == "__main__":
    unittest.main()
