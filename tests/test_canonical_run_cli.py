from __future__ import annotations

import tempfile
import unittest
import os
import subprocess
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_experiment_connect_only_flag_reaches_fresh_and_resume(self):
        result = SimpleNamespace(run_dir=Path("run"), completed_generation=0)
        for arguments in (["--config-dir", "config.yaml"], ["--resume", "run"]):
            with self.subTest(arguments=arguments), patch(
                "eagle.cli.experiment.ExperimentOrchestrator"
            ) as orchestrator:
                orchestrator.return_value.run.return_value = result
                self.assertEqual(eagle_main(["experiment", *arguments, "--connect-only"]), 0)
                self.assertTrue(orchestrator.return_value.run.call_args.kwargs["connect_only"])

    def test_default_routing_uses_only_local_primary(self):
        config = ExperimentConfig.from_mapping({"model": {"name": "local"}})
        self.assertFalse(config.use_remote_llm)
        self.assertEqual(config.llm_base_url, "http://127.0.0.1:8080")
        self.assertEqual(config.active_primary_model.additional_endpoints, ())
        self.assertIs(config.resolved_generation_model, config.model)

    def test_experiment_shell_is_thin_and_noninteractive(self):
        script = (Path(__file__).resolve().parents[1] / "experiment.sh").read_text(encoding="utf-8")
        self.assertNotIn("llama-server", script)
        self.assertNotIn("read -r -p", script)
        self.assertIn("python -m eagle experiment", script)
        self.assertIn("--no-capture-output -n eagle", script)
        self.assertIn("-m eagle experiment", script)
        self.assertNotIn("find", script)
        self.assertNotIn("mapfile -t CONFIG_PATHS", script)

    def test_experiment_shell_batches_directory_configs(self):
        script = (Path(__file__).resolve().parents[1] / "experiment.sh").read_text(encoding="utf-8")
        self.assertNotIn("if [[ -d \"$CONFIG_TARGET\" ]]", script)
        self.assertNotIn("for config_path in", script)
        self.assertNotIn("mapfile -t CONFIG_PATHS", script)

    @unittest.skipUnless(shutil.which("bash"), "Bash is required")
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
            environment["PATH"] = os.pathsep.join((str(fake_bin), environment["PATH"]))
            completed = subprocess.run(
                [shutil.which("bash"), str(repository / "experiment.sh"), "folder", "--mock", "--skip-final-test"],
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

    @unittest.skipUnless(shutil.which("bash"), "Bash is required")
    def test_experiment_shell_passes_folder_resume_to_python(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            conda = fake_bin / "conda"
            conda.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
            conda.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = os.pathsep.join((str(fake_bin), environment["PATH"]))
            completed = subprocess.run(
                [shutil.which("bash"), str(repository / "experiment.sh"), "--resume", "folder", "--skip-final-test"],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), [
            "run", "--no-capture-output", "-n", "eagle", "python", "-m", "eagle",
            "experiment", "--resume", "folder", "--skip-final-test",
        ])
