from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
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
            config = Path(directory) / "config.yaml"
            config.write_text("generations: 2\n", encoding="utf-8")
            initialize_run_manifest(run, config_path=config)
            record_generation(run, 0, self.population(0))
            record_generation(run, 0, self.population(0))
            lines = (run / "generation_metrics.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            metric = json.loads(lines[0])["objectives"]["passive"]
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
            config = Path(directory) / "config.yaml"
            config.write_text("", encoding="utf-8")
            initialize_run_manifest(run, config_path=config)
            population = self.population(0)
            record_generation(run, 0, population)
            finalize_run(run, population, stop_reason=None)
            self.assertTrue((run / "final_population.json").is_file())
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "complete")

    def test_interrupted_manifest_remains_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            config = Path(directory) / "config.yaml"
            config.write_text("", encoding="utf-8")
            initialize_run_manifest(run, config_path=config)
            record_generation(run, 0, self.population(0))
            mark_run_interrupted(run)
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "interrupted")
            self.assertTrue(manifest["resumable"])
            self.assertEqual(manifest["last_completed_generation"], 0)

    def test_all_required_objective_fields_exist(self):
        values = generation_metrics(0, self.population(0))["objectives"]["passive"]
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
                {"opponent_id": "passive", "score": 10.0, "status": "completed"},
                {"opponent_id": "random", "score": -2.0, "status": "completed"},
            ]},
        )
        second = Candidate(
            id="second", status="evaluated",
                fitness_objectives={case: 6.0 for case in LEXICASE_CASES},
            game_eval_result={"opponent_results": [
                {"opponent_id": "passive", "score": 20.0, "status": "completed"},
                {"opponent_id": "random", "score": 4.0, "status": "completed"},
            ]},
        )
        by_opponent = generation_metrics(3, [first, second])["opponent_scores"]["by_opponent"]
        self.assertEqual(by_opponent["passive"]["game_performance"], 15.0)
        self.assertEqual(by_opponent["random"]["game_performance"], 1.0)

    def test_population_snapshot_is_compact_but_keeps_fitness_and_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            config = Path(directory) / "config.yaml"
            config.write_text("", encoding="utf-8")
            initialize_run_manifest(run, config_path=config)
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
            self.assertEqual(payload["fitness_objectives"]["passive"], 12.5)
            self.assertEqual(payload["timing"]["child_total"]["duration_seconds"], 3.25)
