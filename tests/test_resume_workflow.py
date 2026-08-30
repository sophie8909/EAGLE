from __future__ import annotations

import tempfile
import unittest
import json
from dataclasses import replace
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.aos import ReflectionOperatorMode
from eagle.resume import resume_search
from eagle.search import run_search


class ResumeWorkflowTests(unittest.TestCase):
    def test_partial_run_continues_without_duplicate_generation_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "experiment.yaml"
            config_path.write_text(
                "generations: 2\n"
                "population_size: 2\n"
                "execution_mode: mock\n",
                encoding="utf-8",
            )
            config = ExperimentConfig.from_file(config_path)
            config = replace(config, runs_dir=root / "runs")
            initial = run_search(config, config_path=config_path, mock=True)
            (initial.run_dir / "generations" / "generation_0002.json").unlink()
            manifest_path = initial.run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(status="interrupted", latest_generation=1)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            resumed = resume_search(
                None,
                run_dir=initial.run_dir,
                mock=True,
            )
            self.assertEqual(resumed.run_dir, initial.run_dir)
            self.assertEqual(resumed.completed_generation, 2)
            self.assertFalse((initial.run_dir / "generation_metrics.jsonl").exists())
            self.assertTrue((initial.run_dir / "generations" / "generation_0000.json").is_file())
            self.assertTrue((initial.run_dir / "generations" / "generation_0001.json").is_file())
            self.assertTrue((initial.run_dir / "generations" / "generation_0002.json").is_file())

    def test_resume_cannot_switch_reflection_operator_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "experiment.yaml"
            config_path.write_text(
                "generations: 1\n"
                "population_size: 1\n"
                "mutation_rate: 0.0\n"
                "reflection_operator_mode: aos_opponent\n",
                encoding="utf-8",
            )
            config = replace(ExperimentConfig.from_file(config_path), runs_dir=root / "runs")
            initial = run_search(config, config_path=config_path, mock=True)
            for replacement in (
                ReflectionOperatorMode.AOS_HEAD2HEAD,
                ReflectionOperatorMode.STATIC,
            ):
                with self.subTest(replacement=replacement.value), self.assertRaisesRegex(
                    ValueError, "reflection_operator_mode"
                ):
                    resume_search(
                        replace(config, generations=2, reflection_operator_mode=replacement),
                        config_path=config_path,
                        run_dir=initial.run_dir,
                        mock=True,
                    )
