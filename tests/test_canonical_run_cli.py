from __future__ import annotations

import tempfile
import unittest
import os
import subprocess
from pathlib import Path

import yaml

from eagle.__main__ import main as eagle_main
from eagle.config import ExperimentConfig
from eagle.experiment import resolve_experiment_config


class CanonicalRunCliTests(unittest.TestCase):
    def test_removed_compatibility_commands_are_not_dispatched(self):
        self.assertEqual(eagle_main(["run"]), 2)
        self.assertEqual(eagle_main(["runtime"]), 2)

    def test_folder_resolves_experiment_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "experiment.yaml"
            path.write_text("experiment_name: test\n", encoding="utf-8")
            self.assertEqual(resolve_experiment_config(folder), path.resolve())
            self.assertEqual(resolve_experiment_config(path), path.resolve())

    def test_missing_folder_config_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "no YAML configs found"):
                resolve_experiment_config(Path(directory))

    def test_model_section_selects_endpoint_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "experiment.yaml"
            path.write_text(yaml.safe_dump({
                "schema_version": "experiment-v2",
                "model": {
                    "name": "model-a", "path": "weights/model.gguf",
                    "llama_server": "bin/llama-server", "host": "127.0.0.1", "port": 9012,
                },
            }), encoding="utf-8")
            config = ExperimentConfig.from_file(path)
            repository = Path(__file__).resolve().parents[1]
            self.assertEqual(config.model.name, "model-a")
            self.assertEqual(config.llm_base_url, "http://127.0.0.1:9012")
            self.assertEqual(config.model.path, repository / "weights/model.gguf")

    def test_experiment_shell_is_thin_and_noninteractive(self):
        script = (Path(__file__).resolve().parents[1] / "experiment.sh").read_text(encoding="utf-8")
        self.assertNotIn("llama-server", script)
        self.assertNotIn("read -r -p", script)
        self.assertIn("python -m eagle experiment", script)
        self.assertIn("exec conda run --no-capture-output -n eagle", script)
        self.assertNotIn("find", script)
        self.assertNotIn("mapfile -t CONFIG_PATHS", script)

    def test_experiment_shell_batches_directory_configs(self):
        script = (Path(__file__).resolve().parents[1] / "experiment.sh").read_text(encoding="utf-8")
        self.assertNotIn("if [[ -d \"$CONFIG_TARGET\" ]]", script)
        self.assertNotIn("for config_path in", script)
        self.assertNotIn("mapfile -t CONFIG_PATHS", script)

    def test_experiment_shell_maps_positional_target_to_python_config_dir(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            conda = fake_bin / "conda"
            conda.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
            conda.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            completed = subprocess.run(
                [str(repository / "experiment.sh"), "folder", "--mock", "--skip-final-test"],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), [
            "run", "--no-capture-output", "-n", "eagle", "python", "-m", "eagle",
            "experiment", "--config-dir", "folder", "--mock", "--skip-final-test",
        ])
