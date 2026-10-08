import json
from pathlib import Path
import tempfile
import unittest

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.run_artifacts import initialize_run_manifest, load_aos_state, record_generation


class CheckpointStateTests(unittest.TestCase):
    def test_controller_load_uses_committed_snapshot_despite_newer_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_run_manifest(root, config=ExperimentConfig.from_mapping({}))
            record_generation(root, 1, [], aos={"state": {"completed": 1}})
            (root / "generations/generation_0001_parent_rematerialization.json").write_text("{}")
            (root / "generations/generation_0002.json").write_text('{"aos":{"state":{"completed":2}}}')
            self.assertEqual(load_aos_state(root), {"completed": 1})

    def test_snapshot_preserves_stagnation_archives_and_canonical_tie(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_run_manifest(root, config=ExperimentConfig.from_mapping({}))
            (root / "archives/error_memory.jsonl").write_text('{"signature":"known"}\n', encoding="utf-8")
            record_generation(root, 1, [Candidate(id="a"), Candidate(id="z")], stagnation_count=3)
            snapshot = json.loads((root / "generations/generation_0001.json").read_text())
            self.assertEqual(snapshot["stagnation_count"], 3)
            self.assertEqual(snapshot["resume_archives"]["archives/error_memory.jsonl"], '{"signature":"known"}\n')
            self.assertIsNone(snapshot["resume_archives"]["archives/strategy.json"])
            self.assertEqual(snapshot["best_candidate_id"], "z")


if __name__ == "__main__":
    unittest.main()
