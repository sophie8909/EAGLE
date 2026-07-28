import json
import os
import tempfile
import unittest
from pathlib import Path

from eagle.analysis.dashboard import AnalysisDataLoader, filter_candidate_rows
from eagle.analysis.records import ArtifactReadError
from eagle_ui.controllers.analysis_controller import AnalysisLoadCoordinator
from eagle_ui.theme import COLORS
from eagle_ui.views.analysis_view import _base_options, _empty_options


class AnalysisDashboardLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.experiment = self.root / "experiment"
        self.run = self.experiment / "20260727_120000_000001"
        (self.run / "candidates" / "good").mkdir(parents=True)
        (self.run / "candidates" / "failed").mkdir(parents=True)
        records = [
            {
                "candidate": {
                    "candidate_id": "good",
                    "generation": 0,
                    "parent_ids": [],
                    "operator": "seed",
                    "status": "evaluated",
                    "fitness_objectives": {"reward": 5, "cost": 2},
                }
            },
            {
                "candidate": {
                    "candidate_id": "failed",
                    "generation": 1,
                    "parent_ids": ["good"],
                    "operator": "mutation",
                    "status": "failed",
                    "fitness_objectives": {"reward": -1000, "cost": 10},
                    "failure_stage": "compilation",
                    "failure_reason": "compile failed",
                }
            },
        ]
        (self.run / "results.jsonl").write_text(
            "\n".join(json.dumps(item) for item in records) + "\n",
            encoding="utf-8",
        )
        (self.run / "resolved_config.json").write_text(
            json.dumps(
                {
                    "population_size": 2,
                    "generation_count": 2,
                    "random_seed": 7,
                    "objective_directions": {
                        "reward": "maximize",
                        "cost": "minimize",
                    },
                }
            ),
            encoding="utf-8",
        )
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
        self.assertEqual(
            model.operators["statistics"]["mutation"]["failure_rate"], 1.0
        )
        self.assertEqual(model.evolution["objectives"]["reward"][0]["best"], 5.0)
        self.assertEqual(model.evolution["objectives"]["cost"][0]["best"], 2.0)

    def test_failure_sentinel_is_excluded_from_distribution(self):
        model = AnalysisDataLoader().load(self.run)
        self.assertEqual(model.distributions["reward"]["values"], [5.0])
        self.assertEqual(model.distributions["reward"]["failed_count"], 1)

    def test_missing_optional_artifacts_are_warnings_not_fatal(self):
        model = AnalysisDataLoader().load(self.run)
        self.assertFalse(model.available_artifacts["timing"])
        self.assertTrue(
            any("Timing data unavailable" in warning for warning in model.warnings)
        )

    def test_invalid_folder_is_fatal(self):
        with self.assertRaises(ArtifactReadError):
            AnalysisDataLoader().load(self.root / "not-a-run")

    def test_single_objective_run_produces_ranking_data(self):
        records = [
            {
                "candidate": {
                    "candidate_id": "one",
                    "generation": 0,
                    "operator": "seed",
                    "status": "evaluated",
                    "fitness_objectives": {"score": 2},
                }
            },
            {
                "candidate": {
                    "candidate_id": "two",
                    "generation": 0,
                    "operator": "seed",
                    "status": "evaluated",
                    "fitness_objectives": {"score": 8},
                }
            },
        ]
        (self.run / "results.jsonl").write_text(
            "\n".join(json.dumps(item) for item in records) + "\n",
            encoding="utf-8",
        )
        (self.run / "resolved_config.json").write_text(
            json.dumps({"objective_directions": {"score": "maximize"}}),
            encoding="utf-8",
        )

        model = AnalysisDataLoader().load(self.run)

        self.assertFalse(model.pareto["available"])
        self.assertEqual(model.overview["objective_names"], ["score"])
        self.assertEqual(
            [row["candidate_id"] for row in model.candidates], ["one", "two"]
        )

    def test_operator_statistics_and_generic_evaluation_metrics(self):
        payloads = [
            {
                "candidate": {
                    "candidate_id": "a",
                    "generation": 0,
                    "operator": "cross-a",
                    "status": "evaluated",
                    "fitness_objectives": {"score": 1},
                    "operator_reward": 2,
                },
                "game_metrics": {"accuracy": 0.75},
            },
            {
                "candidate": {
                    "candidate_id": "b",
                    "generation": 1,
                    "operator": "cross-a",
                    "status": "failed",
                    "failure_stage": "evaluation",
                    "failure_reason": "evaluator failed",
                    "fitness_objectives": {"score": -1000},
                    "operator_reward": -1,
                },
                "game_metrics": {"accuracy": 0.25},
            },
        ]
        (self.run / "results.jsonl").write_text(
            "\n".join(json.dumps(item) for item in payloads) + "\n",
            encoding="utf-8",
        )
        (self.run / "resolved_config.json").write_text(
            json.dumps({"objective_directions": {"score": "maximize"}}),
            encoding="utf-8",
        )

        model = AnalysisDataLoader().load(self.run)
        stats = model.operators["statistics"]["cross-a"]

        self.assertEqual(stats["usage_count"], 2)
        self.assertEqual(stats["successful_offspring"], 1)
        self.assertEqual(stats["success_rate"], 0.5)
        self.assertEqual(stats["mean_reward_or_improvement"], 0.5)
        self.assertEqual(
            model.evaluation["summaries"]["accuracy"]["mean"], 0.75
        )

    def test_timing_statistics_include_mean_median_p95_and_maximum(self):
        events = [
            {
                "event": "generation",
                "generation": 0,
                "duration_seconds": 20,
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:00:20+00:00",
            },
            *[
                {
                    "event": "llm_request",
                    "generation": 0,
                    "candidate_id": f"c{index}",
                    "operation_stage": "role",
                    "model_id": "model",
                    "duration_seconds": duration,
                }
                for index, duration in enumerate((1, 2, 10))
            ],
        ]
        (self.run / "timing.jsonl").write_text(
            "\n".join(json.dumps(item) for item in events) + "\n",
            encoding="utf-8",
        )

        model = AnalysisDataLoader().load(self.run)
        stats = model.timing["request_statistics"]

        self.assertEqual(stats["mean"], 13 / 3)
        self.assertEqual(stats["median"], 2)
        self.assertEqual(stats["p95"], 10)
        self.assertEqual(stats["maximum"], 10)

    def test_error_categories_stages_and_candidate_detail_are_normalized(self):
        model = AnalysisDataLoader().load(self.run)

        self.assertEqual(model.errors["by_stage"], {"compilation": 1})
        self.assertEqual(model.errors["total"], 1)
        self.assertEqual(model.errors["by_generation_failure_rate"], {1: 1.0})
        self.assertEqual(model.errors["by_operator_failure_rate"], {"mutation": 1.0})
        self.assertIn("identity", model.candidate_details["good"])
        self.assertIn("artifact_paths", model.candidate_details["failed"])

    def test_candidate_filtering_by_id_generation_status_and_pareto(self):
        model = AnalysisDataLoader().load(self.run)

        self.assertEqual(
            [
                row["candidate_id"]
                for row in filter_candidate_rows(model.candidates, search="goo")
            ],
            ["good"],
        )
        self.assertEqual(
            [
                row["candidate_id"]
                for row in filter_candidate_rows(
                    model.candidates, generation=1, status="failed"
                )
            ],
            ["failed"],
        )
        self.assertEqual(
            [
                row["candidate_id"]
                for row in filter_candidate_rows(
                    model.candidates, pareto=True
                )
            ],
            ["good"],
        )

    def test_malformed_optional_timing_is_section_warning(self):
        (self.run / "timing.jsonl").write_text(
            '{"event":"generation","generation":0,"duration_seconds":1}\n'
            "not-json\n",
            encoding="utf-8",
        )

        model = AnalysisDataLoader().load(self.run)

        self.assertEqual(len(model.timing["generations"]), 1)
        self.assertTrue(
            any("timing.jsonl line 2" in value for value in model.warnings)
        )

    def test_experiment_selects_most_recent_valid_direct_run(self):
        older_mtime = self.run.stat().st_mtime
        newest = self.experiment / "20260727_130000_000002"
        newest.mkdir()
        (newest / "results.jsonl").write_text("", encoding="utf-8")
        os.utime(newest, (older_mtime + 10, older_mtime + 10))

        model = AnalysisDataLoader().load(self.experiment)

        self.assertEqual(model.run_dir, newest)
        self.assertEqual(len(model.run_options), 2)

    def test_unknown_version_is_rejected_explicitly(self):
        (self.run / "resolved_config.json").write_text(
            json.dumps({"artifact_schema_version": "future-v99"}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ArtifactReadError, "Unsupported artifact schema"
        ):
            AnalysisDataLoader().load(self.run)

    def test_load_coordinator_rejects_stale_completion(self):
        coordinator = AnalysisLoadCoordinator()
        first = coordinator.begin()
        second = coordinator.begin()

        self.assertFalse(coordinator.is_current(first))
        self.assertTrue(coordinator.is_current(second))

    def test_dark_theme_chart_options_are_readable(self):
        populated = _base_options()
        empty = _empty_options("Unavailable")

        self.assertEqual(populated["backgroundColor"], COLORS["surface"])
        self.assertEqual(
            populated["legend"]["textStyle"]["color"], COLORS["text"]
        )
        self.assertEqual(empty["backgroundColor"], COLORS["surface"])
        self.assertEqual(
            empty["title"]["textStyle"]["color"], COLORS["muted"]
        )


if __name__ == "__main__":
    unittest.main()
