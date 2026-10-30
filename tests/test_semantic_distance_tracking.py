from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from eagle.analysis.loader import load_run
from eagle.analysis.report import generate_analysis
from eagle.artifacts import write_run_config
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.run_artifacts import initialize_run_manifest, record_generation
from eagle.semantic_distances import (
    pairwise_semantic_distance_records,
    semantic_distance_statistics,
)


def semantic_signature(*actions: str) -> dict[str, object]:
    return {
        "status": "complete",
        "dataset_id": "dataset-v1",
        "probe_ids": [f"probe-{index}" for index in range(len(actions))],
        "action_hashes": list(actions),
        "global_hash": "-".join(actions),
    }


def candidate(candidate_id: str, signature: dict[str, object]) -> Candidate:
    return Candidate(
        id=candidate_id,
        generation=0,
        semantic_signature=signature,
        status="evaluated",
        fitness_objectives={"game_performance": 1.0},
        game_eval_result={"game_performance": 1.0},
    )


class SemanticDistanceTrackingTests(unittest.TestCase):
    def population(self) -> list[Candidate]:
        return [
            candidate("a", semantic_signature("same", "left", "left")),
            candidate("b", semantic_signature("same", "right", "right")),
            candidate("c", {"status": "unavailable", "reason": "probe failed"}),
        ]

    def test_pairwise_records_keep_comparable_and_unavailable_pairs(self) -> None:
        records = pairwise_semantic_distance_records(self.population(), generation=4)
        summary = semantic_distance_statistics(records)

        self.assertEqual(
            [(item["left_candidate_id"], item["right_candidate_id"]) for item in records],
            [("a", "b"), ("a", "c"), ("b", "c")],
        )
        self.assertAlmostEqual(records[0]["distance"], 2 / 3)
        self.assertEqual(records[1]["unavailable_reason"], "signature_unavailable")
        self.assertEqual(summary["pair_count"], 3)
        self.assertEqual(summary["comparable_pair_count"], 1)
        self.assertEqual(summary["unavailable_pair_count"], 2)
        self.assertAlmostEqual(summary["minimum"], 2 / 3)
        self.assertAlmostEqual(summary["mean"], 2 / 3)
        self.assertAlmostEqual(summary["maximum"], 2 / 3)

    def test_generation_persists_pairs_and_analysis_plots_min_mean_max(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            config = ExperimentConfig.from_mapping({})
            initialize_run_manifest(run_dir, config=config)
            write_run_config(run_dir, config, mock=True)

            record_generation(run_dir, 0, self.population())

            snapshot = json.loads(
                (run_dir / "generations" / "generation_0000.json").read_text(encoding="utf-8")
            )
            distance = snapshot["metrics"]["semantic_distance"]
            self.assertEqual(distance["pair_count"], 3)
            self.assertEqual(distance["comparable_pair_count"], 1)
            sidecar = run_dir / "generations" / snapshot["semantic_distances"]["artifact"]
            self.assertEqual(len(sidecar.read_text(encoding="utf-8").splitlines()), 3)

            output = generate_analysis(load_run(run_dir), force=True)
            with (output / "semantic_distance_pairs.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertTrue((output / "plots" / "semantic_distance_by_generation.png").is_file())
            generation_csv = (output / "generation_metrics.csv").read_text(encoding="utf-8")
            self.assertIn("semantic_distance_minimum", generation_csv)
            self.assertIn("semantic_distance_mean", generation_csv)
            self.assertIn("semantic_distance_maximum", generation_csv)


if __name__ == "__main__":
    unittest.main()
