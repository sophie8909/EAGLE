from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.resume import resume_search
from eagle.search import run_search


class ResumeWorkflowTests(unittest.TestCase):
    def test_partial_run_continues_without_duplicate_generation_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "experiment.yaml"
            config_path.write_text(
                "seed_prompt_template: microrts_blank_strategy_agent\n"
                "generations: 1\n"
                "population_size: 2\n"
                "generation_backend: mock\n"
                "alignment_backend: mock\n",
                encoding="utf-8",
            )
            config = ExperimentConfig.from_file(config_path)
            config = replace(config, runs_dir=root / "runs")
            initial = run_search(config, config_path=config_path, mock=True)
            resumed = resume_search(
                replace(config, generations=2),
                config_path=config_path,
                run_dir=initial.run_dir,
                mock=True,
            )
            self.assertEqual(resumed.run_dir, initial.run_dir)
            self.assertEqual(resumed.completed_generation, 1)
            lines = (initial.run_dir / "generation_metrics.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue((initial.run_dir / "generations" / "generation_0000.json").is_file())
            self.assertTrue((initial.run_dir / "generations" / "generation_0001.json").is_file())
