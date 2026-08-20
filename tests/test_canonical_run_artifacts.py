from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.opponent_cases import LEXICASE_CASES
from eagle.run_artifacts import (
    finalize_run,
    generation_metrics,
    initialize_run_manifest,
    load_resume_population,
    mark_run_interrupted,
    record_generation,
)


class CanonicalRunArtifactTests(unittest.TestCase):
    def initialize(self, run: Path) -> None:
        initialize_run_manifest(
            run,
            config=ExperimentConfig.from_mapping({}),
        )

    def checkpoint(self, run: Path, population: list[Candidate]) -> None:
        for candidate in population:
            write_candidate_inputs(run / "candidates", candidate)
            write_candidate_snapshot(run / "candidates", candidate)

    def population(self, generation: int) -> list[Candidate]:
        scores = {case: 5.0 for case in LEXICASE_CASES}
        return [
            Candidate(
                id=f"valid-{generation}", generation=generation, status="evaluated",
                fitness_objectives=scores,
                game_eval_result={"game_performance": 5.0},
                operator="seed" if generation == 0 else "mutation",
            ),
            Candidate(
                id=f"failed-{generation}", generation=generation, status="failed",
                failure_reason="runtime", fitness_objectives={case: -1000.0 for case in LEXICASE_CASES},
                operator="seed" if generation == 0 else "mutation",
            ),
        ]

    def test_generation_statistics_and_resume_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            self.initialize(run)
            population = self.population(0)
            self.checkpoint(run, population)
            record_generation(run, 0, population)
            record_generation(run, 0, population)
            self.assertFalse((run / "source_config").exists())
            self.assertFalse((run / "source_config.json").exists())
            snapshot = json.loads((run / "generations" / "generation_0000.json").read_text())
            metric = snapshot["metrics"]["objectives"]["lightrush"]
            self.assertEqual(metric["valid_count"], 1)
            self.assertEqual(metric["failure_count"], 1)
            self.assertEqual(metric["best"], 5.0)
            generation, population = load_resume_population(run)
            self.assertEqual(generation, 0)
            self.assertEqual([item.id for item in population], ["valid-0", "failed-0"])

    def test_final_population_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            self.initialize(run)
            population = self.population(0)
            record_generation(run, 0, population)
            finalize_run(run, population, stop_reason=None)
            self.assertFalse((run / "final_population.json").exists())
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "complete")

    def test_interrupted_manifest_remains_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            self.initialize(run)
            record_generation(run, 0, self.population(0))
            mark_run_interrupted(run)
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "interrupted")
            self.assertTrue(manifest["resumable"])
            self.assertEqual(manifest["latest_generation"], 0)

    def test_all_required_objective_fields_exist(self):
        values = generation_metrics(0, self.population(0))["objectives"]["lightrush"]
        self.assertEqual(
            set(values),
            {
                "objective_id", "direction", "best", "mean", "median", "worst",
                "minimum", "maximum", "standard_deviation", "valid_count",
                "missing_count", "failure_count",
            },
        )

    def test_generation_metrics_record_game_performance_for_each_opponent(self):
        first = Candidate(
            id="first", status="evaluated",
                fitness_objectives={case: 5.0 for case in LEXICASE_CASES},
            game_eval_result={"opponent_results": [
                {"opponent_id": "lightrush", "score": 10.0, "status": "completed"},
                {"opponent_id": "heavyrush", "score": -2.0, "status": "completed"},
            ]},
        )
        second = Candidate(
            id="second", status="evaluated",
                fitness_objectives={case: 6.0 for case in LEXICASE_CASES},
            game_eval_result={"opponent_results": [
                {"opponent_id": "lightrush", "score": 20.0, "status": "completed"},
                {"opponent_id": "heavyrush", "score": 4.0, "status": "completed"},
            ]},
        )
        by_opponent = generation_metrics(3, [first, second])["opponent_scores"]["by_opponent"]
        self.assertEqual(by_opponent["lightrush"]["game_performance"], 15.0)
        self.assertEqual(by_opponent["heavyrush"]["game_performance"], 1.0)

    def test_generation_metrics_record_light_and_heavy_rush_capability_rates(self):
        candidates = [
            Candidate(id="light-winner", game_eval_result={"opponent_results": [
                {"opponent_id": "lightrush", "wins": 3, "losses": 0, "status": "completed"},
                {"opponent_id": "heavyrush", "wins": 0, "losses": 3, "status": "completed"},
            ]}),
            Candidate(id="heavy-winner", game_eval_result={"opponent_results": [
                {"opponent_id": "lightrush", "wins": 0, "losses": 3, "status": "completed"},
                {"opponent_id": "heavyrush", "wins": 2, "losses": 1, "status": "completed"},
            ]}),
            Candidate(id="failed", status="failed", game_eval_result={"opponent_results": [
                {"opponent_id": "lightrush", "wins": 3, "losses": 0, "status": "failed"},
                {"opponent_id": "heavyrush", "wins": 3, "losses": 0, "status": "failed"},
            ]}),
        ]
        metrics = generation_metrics(3, candidates)
        self.assertEqual(metrics["population_size"], 3)
        self.assertAlmostEqual(metrics["light_rush_win_rate"], 1 / 3)
        self.assertAlmostEqual(metrics["heavy_rush_win_rate"], 1 / 3)

    def test_population_snapshot_is_compact_but_keeps_fitness_and_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            self.initialize(run)
            marker = "verbose-match-output-" * 50_000
            candidate = Candidate(
                id="compact",
                status="evaluated",
                fitness_objectives={case: 12.5 for case in LEXICASE_CASES},
                timing={"child_total": {"duration_seconds": 3.25}},
                metadata={
                    "mutation": {
                        "candidate_id": "compact",
                        "operation": "code_mutation",
                        "evidence": {"stdout": marker},
                        "reflection": {"raw_response": marker},
                    }
                },
            )

            record_generation(run, 0, [candidate])
            snapshot_path = run / "generations" / "generation_0000.json"
            snapshot_text = snapshot_path.read_text(encoding="utf-8")
            payload = json.loads(snapshot_text)["population"][0]

            self.assertLess(snapshot_path.stat().st_size, 50_000)
            self.assertNotIn("verbose-match-output", snapshot_text)
            self.assertEqual(payload["fitness_objectives"]["lightrush"], 12.5)
            self.assertNotIn("timing", payload)
