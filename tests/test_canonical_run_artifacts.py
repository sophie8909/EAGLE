from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.run_artifacts import (
    finalize_run,
    generation_metrics,
    initialize_run_manifest,
    load_resume_population,
    record_generation,
)


class CanonicalRunArtifactTests(unittest.TestCase):
    def population(self, generation: int) -> list[Candidate]:
        return [
            Candidate(
                id=f"valid-{generation}", generation=generation, status="evaluated",
                fitness_objectives={"game_performance": 5.0, "code_quality": 550.0},
                operator="seed" if generation == 0 else "mutation",
            ),
            Candidate(
                id=f"failed-{generation}", generation=generation, status="failed",
                failure_reason="runtime", fitness_objectives={"game_performance": -1000.0, "code_quality": -400.0},
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
            metric = json.loads(lines[0])["objectives"]["game_performance"]
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

    def test_all_required_objective_fields_exist(self):
        values = generation_metrics(0, self.population(0))["objectives"]["code_quality"]
        self.assertEqual(
            set(values),
            {
                "objective_id", "direction", "best", "mean", "median", "worst",
                "minimum", "maximum", "standard_deviation", "valid_count",
                "missing_count", "failure_count",
            },
        )
