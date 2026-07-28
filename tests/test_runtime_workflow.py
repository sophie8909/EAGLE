from __future__ import annotations

import json
import tempfile
import unittest
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from eagle.runtime.config import load_runtime_config
from eagle.runtime.endpoints import endpoint_payload
from eagle.runtime.processes import RuntimeManager, build_server_command
from eagle.runtime.watchdog import monitor_once


class RuntimeWorkflowTests(unittest.TestCase):
    def make_config(self, root: Path, *, duplicate_port: bool = False, missing_model: bool = False) -> Path:
        binary = root / "llama-server"
        binary.write_text("", encoding="utf-8")
        coder = root / "coder.gguf"
        general = root / "general.gguf"
        coder.write_text("", encoding="utf-8")
        general.write_text("", encoding="utf-8")
        if missing_model:
            coder.unlink()
        payload = {
            "schema_version": "runtime-v1",
            "environment": {
                "conda_env": "eagle",
                "project_root": str(root),
                "run_root": str(root / "runs"),
                "log_root": str(root / "runtime" / "logs"),
                "pid_root": str(root / "runtime" / "pids"),
            },
            "llama_cpp": {"server_binary": str(binary)},
            "servers": {
                "coder": {
                    "enabled": True, "mode": "local", "host": "0.0.0.0",
                    "client_host": "127.0.0.1", "port": 8081, "model": str(coder),
                    "model_id": "coder-model",
                    "roles": ["generator"], "arguments": {},
                },
                "general": {
                    "enabled": True, "mode": "remote", "client_host": "127.0.0.1",
                    "port": 8081 if duplicate_port else 8082,
                    "roles": ["reflector", "rewriter"],
                },
            },
            "watchdog": {
                "enabled": True, "interval_seconds": 10, "startup_timeout_seconds": 1,
                "health_timeout_seconds": 1, "restart_delay_seconds": 0.01,
                "max_consecutive_restarts": 2, "restart_window_seconds": 60,
            },
            "health_check": {"path": "/health", "fallback_path": "/v1/models", "retries": 1, "retry_delay_seconds": 0.01},
            "analysis": {"output_directory_name": "analysis", "latest_run_strategy": "modified_time"},
        }
        path = root / "runtime.yaml"
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return path

    def test_parsing_endpoint_resolution_and_command(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_runtime_config(self.make_config(Path(directory)))
            self.assertEqual(runtime.conda_env, "eagle")
            self.assertEqual(endpoint_payload(runtime)["roles"]["generator"]["base_url"], "http://127.0.0.1:8081")
            self.assertEqual(endpoint_payload(runtime)["roles"]["reflector"]["base_url"], "http://127.0.0.1:8082")
            command = build_server_command(runtime, runtime.local_servers()[0])
            self.assertIn("--ctx-size", command)
            self.assertIn("--n-gpu-layers", command)
            self.assertIn("--cache-ram", command)
            self.assertEqual(command[command.index("--cache-ram") + 1], "0")
            self.assertIn("--no-cache-prompt", command)
            self.assertEqual(command[-2:], ["--alias", "coder-model"])

    def test_unknown_schema_duplicate_local_port_and_missing_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.make_config(root, missing_model=True)
            with self.assertRaisesRegex(ValueError, "Model file"):
                load_runtime_config(path)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["schema_version"] = "runtime-v999"
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported runtime schema"):
                load_runtime_config(path)

    def test_duplicate_local_ports_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.make_config(root)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["servers"]["general"]["mode"] = "local"
            payload["servers"]["general"]["host"] = "0.0.0.0"
            payload["servers"]["general"]["model"] = str(root / "general.gguf")
            payload["servers"]["general"]["port"] = 8081
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate local port"):
                load_runtime_config(path)

    def test_stale_pid_status_and_stop_refuses_unrelated_process(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_runtime_config(self.make_config(Path(directory)))
            manager = RuntimeManager(runtime)
            manager.write_pid("coder", 999999)
            with patch("eagle.runtime.processes.health_check", return_value=(False, "down")):
                self.assertEqual(manager.statuses()[0].state, "stopped")
            manager.write_pid("coder", 123)
            with patch("eagle.runtime.processes.process_alive", return_value=True), patch(
                "eagle.runtime.processes.command_matches", return_value=False
            ):
                with self.assertRaisesRegex(RuntimeError, "unrelated"):
                    manager.stop_server(runtime.local_servers()[0])

    def test_watchdog_restart_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_runtime_config(self.make_config(Path(directory)))
            manager = Mock()
            manager.read_pid.return_value = None
            manager.start_server.return_value = Mock(pid=42)
            history = defaultdict(deque)
            with patch("eagle.runtime.watchdog.time.sleep"), patch("eagle.runtime.watchdog._log"):
                monitor_once(runtime, manager, history, now=1.0)
                self.assertTrue(manager.start_server.called)
                history["coder"].extend([2.0, 3.0])
                manager.start_server.reset_mock()
                monitor_once(runtime, manager, history, now=4.0)
                self.assertFalse(manager.start_server.called)
