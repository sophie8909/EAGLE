import json
import tempfile
import unittest
from pathlib import Path

from eagle.analysis.dashboard import AnalysisDataLoader
from eagle.analysis.records import ArtifactReadError


class AnalysisDashboardLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.experiment = self.root / "experiment"
        self.run = self.experiment / "20260727_120000_000001"
        (self.run / "candidates" / "good").mkdir(parents=True)
        (self.run / "candidates" / "failed").mkdir(parents=True)
        records = [
            {"candidate": {"candidate_id": "good", "generation": 0, "parent_ids": [], "operator": "seed", "status": "evaluated", "fitness_objectives": {"reward": 5, "cost": 2}}},
            {"candidate": {"candidate_id": "failed", "generation": 1, "parent_ids": ["good"], "operator": "mutation", "status": "failed", "fitness_objectives": {"reward": -1000, "cost": 10}, "failure_stage": "compilation", "failure_reason": "compile failed"}},
        ]
        (self.run / "results.jsonl").write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
        (self.run / "resolved_config.json").write_text(json.dumps({"population_size": 2, "generation_count": 2, "random_seed": 7, "objective_directions": {"reward": "maximize", "cost": "minimize"}}), encoding="utf-8")
        (self.run / "summary.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_folder_loads_experiment_and_newest_run_without_second_action(self):
        model = AnalysisDataLoader().load(self.experiment)
        self.assertEqual(model.run_dir, self.run)
        self.assertEqual(model.run_kind, "experiment")
        self.assertEqual(model.overview["random_seed"], 7)
        self.assertEqual(model.overview["failed_evaluations"], 1)

    def test_multi_objective_pareto_and_single_pass_sections(self):
        model = AnalysisDataLoader().load(self.run)
        self.assertTrue(model.pareto["available"])
        self.assertEqual(model.pareto["front_size"], 1)
        self.assertEqual(model.evolution["objectives"]["reward"][0]["mean"], 5.0)
        self.assertEqual(model.operators["mutation"]["failure_rate"], 1.0)

    def test_failure_sentinel_is_excluded_from_distribution(self):
        model = AnalysisDataLoader().load(self.run)
        self.assertEqual(model.distributions["reward"]["values"], [5.0])
        self.assertEqual(model.distributions["reward"]["failed_count"], 1)

    def test_missing_optional_artifacts_are_warnings_not_fatal(self):
        model = AnalysisDataLoader().load(self.run)
        self.assertFalse(model.available_artifacts["timing"])
        self.assertTrue(any("Timing data unavailable" in warning for warning in model.warnings))

    def test_invalid_folder_is_fatal(self):
        with self.assertRaises(ArtifactReadError):
            AnalysisDataLoader().load(self.root / "not-a-run")


if __name__ == "__main__":
    unittest.main()
