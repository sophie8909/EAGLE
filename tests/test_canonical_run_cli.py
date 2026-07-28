from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from eagle.cli.run import _resolve_and_check_roles, _validate_experiment_document
from eagle.config import ExperimentConfig
from eagle.runtime.config import load_runtime_config


class CanonicalRunCliTests(unittest.TestCase):
    def experiment(self, root: Path) -> Path:
        path = root / "experiment.yaml"
        path.write_text(
            yaml.safe_dump({
                "schema_version": "experiment-v1",
                "algorithm": "nsga2",
                "application": "microrts",
                "objectives": {"game_performance": "maximize", "code_quality": "maximize"},
                "required_llm_roles": ["generator", "reflector", "rewriter"],
                "seed_prompt_template": "microrts_blank_strategy_agent",
            }),
            encoding="utf-8",
        )
        return path

    def runtime(self, root: Path):
        binary = root / "llama-server"
        model = root / "model.gguf"
        binary.write_text("", encoding="utf-8")
        model.write_text("", encoding="utf-8")
        path = root / "runtime.yaml"
        path.write_text(yaml.safe_dump({
            "schema_version": "runtime-v1",
            "environment": {
                "conda_env": "eagle", "project_root": str(root),
                "run_root": str(root / "runs"), "log_root": str(root / "runtime" / "logs"),
                "pid_root": str(root / "runtime" / "pids"),
            },
            "llama_cpp": {"server_binary": str(binary)},
            "servers": {
                "all": {
                    "enabled": True, "mode": "local", "host": "0.0.0.0",
                    "client_host": "127.0.0.1", "port": 8081, "model": str(model),
                    "roles": ["generator", "reflector", "rewriter"], "arguments": {},
                }
            },
            "watchdog": {
                "enabled": True, "interval_seconds": 1, "startup_timeout_seconds": 1,
                "health_timeout_seconds": 1, "restart_delay_seconds": 1,
                "max_consecutive_restarts": 1, "restart_window_seconds": 1,
            },
            "health_check": {"path": "/health", "fallback_path": "/v1/models", "retries": 1, "retry_delay_seconds": 1},
            "analysis": {"output_directory_name": "analysis", "latest_run_strategy": "modified_time"},
        }), encoding="utf-8")
        return load_runtime_config(path)

    def test_explicit_experiment_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.experiment(Path(directory))
            payload = _validate_experiment_document(path)
            ExperimentConfig.from_file(path).validate()
            self.assertEqual(payload["algorithm"], "nsga2")
            self.assertEqual(payload["application"], "microrts")

    def test_missing_required_role_and_unhealthy_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.runtime(Path(directory))
            with self.assertRaisesRegex(ValueError, "Missing required LLM role"):
                _resolve_and_check_roles(runtime, ("critic",))
            with patch("eagle.cli.run.health_check", return_value=(False, "connection refused")):
                with self.assertRaisesRegex(RuntimeError, "health-check failure"):
                    _resolve_and_check_roles(runtime, ("generator",))

    def test_default_config_selection_is_plain_terminal_list(self):
        script = (Path(__file__).resolve().parents[1] / "run.sh").read_text(encoding="utf-8")
        self.assertIn("mapfile -t CONFIGS", script)
        self.assertIn('read -r -p "Select experiment: "', script)
        self.assertNotIn("questionnaire", script.lower())
