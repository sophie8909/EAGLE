from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from eagle.cli.run import _validate_experiment_document


class CanonicalRunCliTests(unittest.TestCase):
    def experiment(self, root: Path, **extra) -> Path:
        payload = {
            "schema_version": "experiment-v1",
            "algorithm": "nsga2",
            "application": "microrts",
            "objectives": {"game_performance": "maximize", "code_quality": "maximize"},
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
            self.assertEqual(payload["algorithm"], "nsga2")

    def test_experiment_rejects_model_and_endpoint_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.experiment(Path(directory), llm={"model": "other"})
            with self.assertRaisesRegex(ValueError, "cannot select runtime endpoints or models"):
                _validate_experiment_document(path)

    def test_run_shell_script_is_noninteractive(self):
        script = (Path(__file__).resolve().parents[1] / "run.sh").read_text(encoding="utf-8")
        self.assertNotIn("read -r -p", script)
        self.assertNotIn("mapfile -t CONFIGS", script)
        self.assertIn("microrts.yaml", script)
