from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from eagle.__main__ import main as dispatch
from eagle.cli.server import main
from eagle.config import ExperimentConfig


_REAL_CONFIG_FROM_FILE = ExperimentConfig.from_file


class ServerCliTests(unittest.TestCase):
    def setUp(self):
        self.config = Mock()
        self.config.active_primary_model.manages_runtime = True
        self.runtime = SimpleNamespace(log_path="server.log")
        self.manager = Mock()
        self.manager.start.return_value = SimpleNamespace(state="healthy", pid=123)
        self.restore = Mock()
        for target, value in (
            ("ExperimentConfig.from_file", self.config),
            ("runtime_config_from_experiment", self.runtime),
            ("RuntimeManager", self.manager),
            ("install_interrupt_handlers", self.restore),
        ):
            patcher = patch("eagle.cli.server." + target, return_value=value)
            setattr(self, target.split(".")[0] + "_mock", patcher.start())
            self.addCleanup(patcher.stop)

    def test_dispatch_starts_server_and_interrupt_cleans_up_only_its_process(self):
        with patch("eagle.cli.server.time.sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(dispatch(["server", "--config", "example.yaml"]), 130)
        self.config.active_primary_model.validate.assert_called_once_with(require_files=True)
        self.RuntimeManager_mock.assert_called_once_with(self.runtime)
        self.manager.start.assert_called_once()
        self.manager.stop_owned.assert_called_once()
        self.manager.stop.assert_not_called()
        self.restore.assert_called_once()

    def test_startup_failure_still_cleans_up(self):
        self.manager.start.side_effect = RuntimeError("GPU unavailable")
        self.assertEqual(main(["--config", "example.yaml"]), 2)
        self.manager.stop_owned.assert_called_once()
        self.restore.assert_called_once()

    def test_server_death_returns_failure_and_cleans_up(self):
        self.manager.status.return_value = SimpleNamespace(state="stopped", detail="process exited")
        with patch("eagle.cli.server.time.sleep"):
            self.assertEqual(main(["--config", "example.yaml"]), 2)
        self.manager.stop_owned.assert_called_once()

    def test_external_endpoint_is_not_adopted(self):
        self.config.active_primary_model.manages_runtime = False
        self.assertEqual(main(["--config", "example.yaml"]), 2)
        self.RuntimeManager_mock.assert_not_called()
        self.restore.assert_called_once()

    def test_remote_selector_does_not_launch_retained_local_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "local.gguf"
            server_path = root / "llama-server"
            config_path = root / "experiment.yaml"
            model_path.write_bytes(b"model")
            server_path.write_text("#!/bin/sh\n", encoding="utf-8")
            server_path.chmod(0o755)
            config_path.write_text(
                "\n".join(
                    (
                        "model:",
                        "  name: local-model",
                        f"  path: {model_path}",
                        f"  llama_server: {server_path}",
                        "remote_model:",
                        "  name: remote-model",
                        "  host: llm.example.test",
                        "  port: 1234",
                        "use_remote_llm: true",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            self.ExperimentConfig_mock.side_effect = _REAL_CONFIG_FROM_FILE
            self.assertEqual(main(["--config", str(config_path)]), 2)
        self.RuntimeManager_mock.assert_not_called()

    def test_validation_failure_never_constructs_manager(self):
        self.config.active_primary_model.validate.side_effect = ValueError("missing GGUF")
        self.assertEqual(main(["--config", "example.yaml"]), 2)
        self.RuntimeManager_mock.assert_not_called()
        self.restore.assert_called_once()
