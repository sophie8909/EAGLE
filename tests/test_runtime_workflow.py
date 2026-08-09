from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from eagle.runtime.config import (
    LEGACY_RUNTIME_ERROR,
    load_runtime_config,
    platform_executable_names,
    resolve_executable,
)
from eagle.runtime.processes import RuntimeManager, build_server_command


class RuntimeWorkflowTests(unittest.TestCase):
    def make_config(self, root: Path, *, model_name="qwen3.5-9b", missing_model=False) -> Path:
        binary = root / "llama-server"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
        model = root / "qwen3.5-9b.gguf"
        if not missing_model:
            model.write_bytes(b"model")
        else:
            model.unlink(missing_ok=True)
        payload = {
            "schema_version": "runtime-v1",
            "conda_env": "eagle",
            "llm": {
                "model_name": model_name,
                "model_path": str(model),
                "server_binary": str(binary),
                "host": "127.0.0.1",
                "port": 8080,
                "context_size": 32768,
                "gpu_layers": 0,
                "parallel": 1,
                "threads": 8,
                "batch_size": 512,
                "startup_timeout_seconds": 5,
                "health_timeout_seconds": 1,
            },
            "runtime": {"log_path": "runtime/logs/llm-server.log", "pid_path": "runtime/pids/llm-server.pid"},
        }
        path = root / "runtime.yaml"
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return path

    def test_valid_qwen_runtime_and_command(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_runtime_config(self.make_config(Path(directory)))
            self.assertEqual(runtime.llm.model_name, "qwen3.5-9b")
            command = build_server_command(runtime)
            self.assertEqual(command[1:5], ["--model", str(runtime.llm.model_path), "--host", "127.0.0.1"])
            self.assertIn("--n-gpu-layers", command)

    def test_wrong_model_missing_model_and_legacy_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "exactly 'qwen3.5-9b'"):
                load_runtime_config(self.make_config(root, model_name="qwen2.5"))
            with self.assertRaisesRegex(ValueError, "does not exist"):
                load_runtime_config(self.make_config(root, missing_model=True))
            path = self.make_config(root)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["servers"] = {}
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported legacy multi-model"):
                load_runtime_config(path)

    def test_unknown_schema_invalid_port_and_non_executable_binary_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.make_config(root)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["schema_version"] = "runtime-v999"
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported runtime schema"):
                load_runtime_config(path)
            path = self.make_config(root)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["llm"]["port"] = 70000
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
                load_runtime_config(path)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["llm"]["server_binary"] = str(root / "missing-llama-server.exe")
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not exist or is not a file"):
                load_runtime_config(path)


    def test_executable_resolution_uses_explicit_path_before_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / ("llama-server.exe" if os.name == "nt" else "llama-server")
            explicit.write_text("fake", encoding="utf-8")
            with patch("eagle.runtime.config.shutil.which", return_value=None):
                resolved = resolve_executable(
                    explicit,
                    default_names=platform_executable_names("llama-server"),
                    label="llama.cpp server",
                )
            self.assertEqual(resolved, explicit.resolve())

    def test_named_executable_resolves_from_path(self):
        with tempfile.TemporaryDirectory() as directory:
            found = Path(directory) / "llama-server.exe"
            found.write_text("fake", encoding="utf-8")
            with patch("eagle.runtime.config.shutil.which", return_value=str(found)):
                resolved = resolve_executable(
                    "llama-server",
                    default_names=platform_executable_names("llama-server"),
                    label="llama.cpp server",
                )
            self.assertEqual(resolved, found.resolve())

    def test_runtime_defaults_to_active_python(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_runtime_config(self.make_config(Path(directory)))
            self.assertEqual(runtime.tools.python, Path(sys.executable).resolve())

    def test_missing_named_executable_fails_with_actionable_error(self):
        with patch("eagle.runtime.config.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "llama.cpp server executable not found"):
                resolve_executable(
                    "llama-server.exe",
                    default_names=platform_executable_names("llama-server"),
                    label="llama.cpp server",
                )

    def test_server_arguments_are_forwarded_without_a_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.make_config(root)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["llm"]["arguments"] = ["--flash-attn", "on"]
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            runtime = load_runtime_config(path)
            command = build_server_command(runtime)
            self.assertEqual(command[-2:], ["--flash-attn", "on"])
            self.assertNotIn("bash", command)

    def test_stale_pid_is_removed_and_unrelated_managed_pid_is_not_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_runtime_config(self.make_config(Path(directory)))
            manager = RuntimeManager(runtime)
            manager.write_pid(999999)
            with patch("eagle.runtime.processes.process_alive", return_value=False):
                self.assertEqual(manager.status().state, "stopped")
            manager.write_pid(123)
            with patch("eagle.runtime.processes.process_alive", return_value=True), patch(
                "eagle.runtime.processes.command_matches", return_value=False
            ):
                with self.assertRaisesRegex(RuntimeError, "unrelated"):
                    manager.stop()

    def test_start_reuses_matching_healthy_server(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_runtime_config(self.make_config(Path(directory)))
            manager = RuntimeManager(runtime)
            manager.write_pid(123)
            with patch("eagle.runtime.processes.process_alive", return_value=True), patch(
                "eagle.runtime.processes.command_matches", return_value=True
            ), patch("eagle.runtime.processes.health_check", return_value=(True, "ok")):
                status = manager.start()
            self.assertEqual(status.state, "healthy")
            self.assertEqual(status.pid, 123)
