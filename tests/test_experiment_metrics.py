import json
import tempfile
import unittest
from pathlib import Path

from eagle.analysis.experiment_metrics import read_metrics
from eagle.evaluation.game_performance import GamePerformanceConfig
from eagle.fixed_evaluation import SCHEMA_VERSION as FIXED_SCHEMA
from eagle.final_test import FINAL_TEST_SCHEMA_VERSION
from eagle.run_artifacts import GENERATION_SCHEMA_VERSION
from eagle.self_play import SNAPSHOT_SCHEMA_VERSION


class ExperimentMetricsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.run = {"path": self.root, "latest_generation": 0, "seed": 8, "label": "Test"}
        self.write("config.yaml", {"evaluation": {"mode": "self_play", "self_play_refresh_interval": 5}})
        self.hash = "f" * 64
        signature = {
            "status": "complete", "dataset_id": "test", "dataset_sha256": self.hash,
            "normalization_version": "action-v1", "probe_ids": ["map:opening:p0"],
        }
        for generation in (0, 1):
            self.write(f"generations/generation_{generation:04d}.json", {
                "schema_version": GENERATION_SCHEMA_VERSION, "generation": generation,
                "population": [{"candidate_id": candidate, "semantic_signature": signature} for candidate in ("a", "b")],
                "metrics": {
                    "population_size": 2, "game_performance": {"best": 1, "mean": 0, "count": 2},
                    "semantic_distance": {"mean": 0, "comparable_pair_count": 1, "unavailable_pair_count": 0},
                },
            })
        self.write("generations/generation_0000_self_play_snapshot.json", {
            "schema_version": SNAPSHOT_SCHEMA_VERSION, "generation": 0, "context_id": "frozen",
        })
        self.protocol = {
            "opponents": [{"id": "o", "class": "ai.O", "jar_sha256": None}],
            "maps": [{"id": "m", "path": "maps/m.xml", "tick_limit": 900, "sha256": self.hash}],
            "games_per_side_per_map": 1, "matches_per_representative": 2,
            "seed_identity": "candidate_id", "seed_scheme": "derive_match_seed(root, candidate_id)", "random_seed": 8,
            "scoring": GamePerformanceConfig().to_json_dict(),
            "microrts_identity": {"src": self.hash}, "support_identity": {"eagle/adapters": self.hash},
            "worker_rush_source_sha256": self.hash,
        }

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_committed_generation_includes_zero_and_diversity_definition(self):
        result = read_metrics(self.run)
        points = {(row["metric"], row["statistic"]): row for row in result["points"]}
        self.assertTrue(all(row["generation"] == 0 for row in result["points"]))
        self.assertEqual(points["self_play", "mean"]["context"], "frozen")
        self.assertEqual(points["self_play", "mean"]["value"], 0)
        semantic = points["diversity", "mean"]
        self.assertEqual(semantic["coverage"]["comparable_pair_count"], 1)
        self.assertEqual(result["protocols"][semantic["protocol"]]["probe_ids"], ["map:opening:p0"])

    def test_fixed_population_coverage_and_conflicting_retries(self):
        def fixture(scores):
            return {
                "schema_version": FIXED_SCHEMA, "selection_mode": "all_runnable_candidates",
                "protocol": self.protocol,
                "selections": [
                    {"generation": 0, "candidate_id": candidate, "search_game_performance": score}
                    for candidate, score in (("a", 1), ("b", 0))
                ],
                "rows": [
                    {"generation": 0, "candidate_id": candidate, "status": "complete", "expected_matches": 2,
                     "completed_matches": 2, "errors": 0, "mean_match_score": score}
                    for candidate, score in scores.items()
                ],
            }

        source = "fixed_evaluation/fixed_evaluation_summary.json"
        retry = "final_test/cross_generation_retry_001/fixed_evaluation_summary.json"
        self.write(source, fixture({"a": 2}))
        partial = read_metrics(self.run)
        self.assertEqual([row["statistic"] for row in partial["points"] if row["metric"] == "fixed"], ["representative"])
        self.assertEqual(partial["fixed_coverage"][0]["coverage"], {"expected": 2, "evaluated": 1})

        self.write(source, fixture({"a": 2, "b": 8}))
        self.write(retry, fixture({"a": 2, "b": 8}))
        complete = read_metrics(self.run)
        self.assertEqual(
            {row["statistic"]: row["value"] for row in complete["points"] if row["metric"] == "fixed"},
            {"mean": 5, "best": 8, "representative": 2},
        )
        self.assertEqual(sum(row["metric"] == "fixed" for row in complete["points"]), 3)

        self.write(retry, fixture({"a": 2, "b": 10}))
        conflict = read_metrics(self.run)
        self.assertEqual([row["statistic"] for row in conflict["points"] if row["metric"] == "fixed"], ["representative"])
        self.assertTrue(any("conflicting scores" in issue for issue in conflict["issues"]))

    def test_final_score_generation_and_invalid_matrix(self):
        source = "final_test/final_test_summary.json"
        summary = {
            "schema_version": FINAL_TEST_SCHEMA_VERSION, "protocol": self.protocol, "final_test_valid": True,
            "selection": {"mode": "latest_or_fallback", "requested_generation": 2, "selected_generation": 0, "fallback": True},
            "opponents": self.protocol["opponents"], "maps": self.protocol["maps"],
            "games_per_side_per_map": 1,
            "matches": [
                {"opponent_id": "o", "map_id": "m", "candidate_player": side, "game_index": 0,
                 "result": result, "match": {"score": score}}
                for side, result, score in ((0, "win", 100), (1, "draw", 0))
            ],
            "table": {"o": {"m": {"wins": 1, "draws": 1, "losses": 0, "errors": 0, "opponent_fault_contained": 1}}},
        }
        self.write(source, summary)
        result = read_metrics(self.run)
        score = next(row for row in result["points"] if row["metric"] == "final" and row["statistic"] == "score")
        self.assertEqual((score["generation"], score["requested_generation"], score["value"]), (0, 2, 50))
        self.assertTrue(score["fallback"])
        self.assertTrue(score["protocol"])
        self.assertEqual(result["opponents"][0]["win_rate"], 0.5)
        self.assertEqual(result["opponents"][0]["faults"], 1)

        self.write(source, {**summary, "final_test_valid": False})
        result = read_metrics(self.run)
        self.assertFalse(any(row["metric"] == "final" for row in result["points"]))
        self.assertFalse(result["opponents"])


if __name__ == "__main__":
    unittest.main()
