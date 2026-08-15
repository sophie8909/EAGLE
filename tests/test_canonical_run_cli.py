from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from eagle.cli.run import _resolve_resume_dir, _validate_experiment_document


class CanonicalRunCliTests(unittest.TestCase):
    def experiment(self, root: Path, **extra) -> Path:
        payload = {
            "schema_version": "experiment-v1",
            "algorithm": "lexicase",
            "application": "microrts",
            "objectives": {"opponent_cases": "maximize"},
            "seed_prompt_template": "microrts_blank_strategy_agent",
        }
        payload.update(extra)
        path = root / "experiment.yaml"
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        return path

    def test_experiment_allows_generation_behavior_only(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = _validate_experiment_document(
                self.experiment(Path(directory), llm={"temperature": 0.3, "max_tokens": 128})
            )
            self.assertEqual(payload["algorithm"], "lexicase")

    def test_experiment_rejects_model_and_endpoint_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.experiment(Path(directory), llm={"model": "other"})
            with self.assertRaisesRegex(ValueError, "cannot select runtime endpoints or models"):
                _validate_experiment_document(path)

    def test_experiment_allows_commentator_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = _validate_experiment_document(
                self.experiment(Path(directory), llm={"match_commentator": {"enabled": True, "temperature": 0.2, "sample_count": 10}})
            )
            self.assertTrue(payload["llm"]["match_commentator"]["enabled"])

    def test_run_shell_script_is_noninteractive(self):
        script = (Path(__file__).resolve().parents[1] / "run.sh").read_text(encoding="utf-8")
        self.assertNotIn("read -r -p", script)
        self.assertNotIn("mapfile -t CONFIGS", script)
        self.assertIn("microrts.yaml", script)

    def test_latest_resume_selects_newest_incomplete_run_with_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / "runs"
            for name, status, completed in (
                ("20260811_100000_000000", "running", [0]),
                ("20260811_110000_000000", "complete", [0, 1]),
                ("20260811_120000_000000", "interrupted", [0, 1]),
            ):
                run = runs / name
                run.mkdir(parents=True)
                (run / "manifest.json").write_text(
                    yaml.safe_dump({"status": status, "completed_generations": completed}),
                    encoding="utf-8",
                )
            self.assertEqual(
                _resolve_resume_dir("latest", runs).name,
                "20260811_120000_000000",
            )
