from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from eagle.config import ExperimentConfig
from eagle.runtime.config import runtime_config_from_experiment
from eagle.runtime.processes import (
    ProcessIdentity,
    ProcessStatus,
    RuntimeManager,
    build_server_command,
)


class RuntimeWorkflowTests(unittest.TestCase):
    def make_config(
        self,
        root: Path,
        *,
        model_name: str = "runtime-test",
        model_filename: str = "model.gguf",
        missing_model: bool = False,
        executable: bool = True,
        port: int = 18080,
    ) -> ExperimentConfig:
        binary = root / "llama-server"
        if not binary.exists():
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755 if executable else 0o644)
        model = root / model_filename
        if not missing_model:
            model.write_bytes(b"model")
        return ExperimentConfig.from_mapping({
            "model": {
                "name": model_name,
                "path": str(model),
                "llama_server": str(binary),
                "host": "127.0.0.1",
                "port": port,
                "context_size": 32768,
                "gpu_layers": 0,
                "parallel": 1,
                "threads": 8,
                "batch_size": 512,
                "startup_timeout_seconds": 5,
                "health_timeout_seconds": 1,
            },
        })

    def make_runtime(self, root: Path, **kwargs):
        runtime = runtime_config_from_experiment(self.make_config(root, **kwargs))
        return replace(
            runtime,
            log_path=root / "runtime" / "logs" / "server.log",
            ownership_path=root / "runtime" / "ownership" / "127.0.0.1-18080.json",
        )

    @staticmethod
    def identity(runtime, pid: int = 123, start_time: int = 456) -> ProcessIdentity:
        return ProcessIdentity(
            pid=pid,
            start_time=start_time,
            executable=str(runtime.llm.server_binary),
            command=tuple(build_server_command(runtime)),
        )

    def write_state(self, manager: RuntimeManager, identity: ProcessIdentity) -> None:
        manager._owned_identity = identity
        manager._write_ownership_state(identity)

    def test_experiment_model_builds_server_command_and_endpoint_state_path(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            command = build_server_command(runtime)
            self.assertEqual(
                command[1:5],
                ["--model", str(runtime.llm.model_path), "--host", "127.0.0.1"],
            )
            self.assertIn("--n-gpu-layers", command)
            self.assertIn("--no-cache-prompt", command)
            self.assertEqual(runtime.ownership_path.name, "127.0.0.1-18080.json")

    def test_runtime_compatibility_key_uses_every_launch_critical_field(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = self.make_runtime(root)
            fields = {
                "model_path": root / "other.gguf",
                "server_binary": root / "other-llama-server",
                "host": "0.0.0.0",
                "port": 18081,
                "context_size": 4096,
                "gpu_layers": 1,
                "parallel": 2,
                "threads": 9,
                "batch_size": 256,
            }
            for field, value in fields.items():
                with self.subTest(field=field):
                    self.assertNotEqual(runtime.spec, replace(runtime.spec, **{field: value}))

    def test_distinct_generation_model_has_its_own_runtime_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "llama-server"
            server.write_text("#!/bin/sh\n", encoding="utf-8")
            server.chmod(0o755)
            reflection_model = root / "ministral.gguf"
            generation_model = root / "qwen.gguf"
            reflection_model.write_bytes(b"reflection")
            generation_model.write_bytes(b"generation")
            common = {
                "llama_server": str(server),
                "host": "127.0.0.1",
                "port": 18080,
            }
            config = ExperimentConfig.from_mapping({
                "model": {
                    **common,
                    "name": "ministral",
                    "path": str(reflection_model),
                },
                "generation_model": {
                    **common,
                    "name": "qwen3.5-9b",
                    "path": str(generation_model),
                },
            })

            reflection = runtime_config_from_experiment(config, phase="reflection")
            generation = runtime_config_from_experiment(config, phase="generation")

            self.assertTrue(config.uses_distinct_generation_model)
            self.assertEqual(reflection.llm.model_path, reflection_model)
            self.assertEqual(generation.llm.model_path, generation_model)
            self.assertNotEqual(reflection.spec, generation.spec)
            self.assertEqual(
                config.to_mapping()["generation_model"]["name"],
                "qwen3.5-9b",
            )

    def test_missing_model_and_non_executable_binary_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "model.path"):
                runtime_config_from_experiment(self.make_config(root, missing_model=True))
            with self.assertRaisesRegex(ValueError, "not executable"):
                runtime_config_from_experiment(self.make_config(root, executable=False))

    def test_invalid_port_is_rejected_by_experiment_schema(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            ExperimentConfig.from_mapping({
                "model": {"name": "bad", "port": 70000},
            })

    def test_dead_or_pid_reused_ownership_state_is_removed_without_killing(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            identity = self.identity(runtime)
            self.write_state(manager, identity)
            manager._owned_identity = None
            with patch(
                "eagle.runtime.processes.identity_matches_process", return_value=False
            ), patch("eagle.runtime.processes.terminate_pid") as terminate:
                manager._reconcile_ownership_state()
            self.assertFalse(runtime.ownership_path.exists())
            terminate.assert_not_called()

    def test_verified_stale_eagle_process_is_stopped_and_state_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            identity = self.identity(runtime)
            self.write_state(manager, identity)
            manager._owned_identity = None
            with patch(
                "eagle.runtime.processes.identity_matches_process", return_value=True
            ), patch(
                "eagle.runtime.processes._launcher_is_alive", return_value=False
            ), patch("eagle.runtime.processes.terminate_pid") as terminate:
                manager._reconcile_ownership_state()
            terminate.assert_called_once_with(identity.pid, 5.0)
            self.assertFalse(runtime.ownership_path.exists())

    def test_active_eagle_process_is_not_stopped_by_another_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            identity = self.identity(runtime)
            self.write_state(manager, identity)
            manager._owned_identity = None
            with patch(
                "eagle.runtime.processes.identity_matches_process", return_value=True
            ), patch(
                "eagle.runtime.processes._launcher_is_alive", return_value=True
            ), patch("eagle.runtime.processes.terminate_pid") as terminate:
                with self.assertRaisesRegex(RuntimeError, "active EAGLE-owned"):
                    manager._reconcile_ownership_state()
            terminate.assert_not_called()
            self.assertTrue(runtime.ownership_path.exists())

    def test_legacy_generic_pid_state_recognizes_and_cleans_orphan(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            pid_root = runtime.runtime_root / "pids"
            pid_root.mkdir(parents=True)
            pid_path = pid_root / "llm-server.pid"
            model_path = pid_root / "llm-server.model"
            pid_path.write_text("1424274\n", encoding="ascii")
            model_path.write_text("old-model\n", encoding="utf-8")
            identity = self.identity(runtime, pid=1424274)
            with patch(
                "eagle.runtime.processes.process_alive", return_value=True
            ), patch(
                "eagle.runtime.processes.process_identity", return_value=identity
            ), patch(
                "eagle.runtime.processes._legacy_identity_is_trusted", return_value=True
            ), patch(
                "eagle.runtime.processes._legacy_launcher_is_alive", return_value=False
            ), patch("eagle.runtime.processes.terminate_pid") as terminate:
                RuntimeManager(runtime)._reconcile_legacy_pid_state()
            terminate.assert_called_once_with(1424274, 5.0)
            self.assertFalse(pid_path.exists())
            self.assertFalse(model_path.exists())

    def test_systemd_adoption_is_not_mistaken_for_an_active_legacy_launcher(self):
        systemd = ProcessIdentity(
            pid=3912,
            start_time=1,
            executable="/usr/lib/systemd/systemd",
            command=("/usr/lib/systemd/systemd", "--user"),
        )
        with patch(
            "eagle.runtime.processes.read_parent_pid", side_effect=[3912, 1]
        ), patch(
            "eagle.runtime.processes.process_identity", return_value=systemd
        ):
            from eagle.runtime.processes import _legacy_launcher_is_alive
            self.assertFalse(_legacy_launcher_is_alive(1424274))

    def test_actual_eagle_cli_ancestor_keeps_legacy_runtime_active(self):
        launcher = ProcessIdentity(
            pid=777,
            start_time=1,
            executable="/usr/bin/python",
            command=("python", "-m", "eagle", "experiment", "--config-dir", "configs"),
        )
        with patch(
            "eagle.runtime.processes.read_parent_pid", return_value=777
        ), patch(
            "eagle.runtime.processes.process_identity", return_value=launcher
        ):
            from eagle.runtime.processes import _legacy_launcher_is_alive
            self.assertTrue(_legacy_launcher_is_alive(123))

    def test_foreign_occupied_port_is_reported_and_never_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            with patch.object(manager, "_reconcile_ownership_state"), patch.object(
                manager, "_reconcile_legacy_pid_state"
            ), patch(
                "eagle.runtime.processes.discover_listening_server_pid", return_value=456
            ), patch(
                "eagle.runtime.processes.process_alive", return_value=True
            ), patch(
                "eagle.runtime.processes.read_executable", return_value="/usr/bin/python3"
            ), patch(
                "eagle.runtime.processes.read_command",
                return_value="python3 -m http.server 18080",
            ), patch("eagle.runtime.processes.terminate_pid") as terminate, patch(
                "eagle.runtime.processes.subprocess.Popen"
            ) as popen:
                with self.assertRaisesRegex(RuntimeError, "not EAGLE-owned") as caught:
                    manager.start()
            message = str(caught.exception)
            self.assertIn("127.0.0.1:18080", message)
            self.assertIn("PID: 456", message)
            self.assertIn("/usr/bin/python3", message)
            self.assertIn("python3 -m http.server 18080", message)
            terminate.assert_not_called()
            popen.assert_not_called()

    def test_same_runtime_is_reused_and_different_runtime_switches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_a = self.make_runtime(root, model_name="a", model_filename="a.gguf")
            runtime_b = self.make_runtime(root, model_name="b", model_filename="b.gguf")
            manager = RuntimeManager()
            events: list[str] = []

            def start():
                events.append(f"start:{manager.runtime.llm.model_path.name}")
                manager._owned_identity = self.identity(manager.runtime)
                return ProcessStatus("healthy", "ok", 123, action="started")

            def stop_owned():
                events.append(f"stop:{manager.runtime.llm.model_path.name}")
                manager._owned_identity = None

            with patch.object(manager, "start", side_effect=start), patch.object(
                manager, "stop_owned", side_effect=stop_owned
            ), patch.object(manager, "_verify_owned_process"), patch(
                "eagle.runtime.processes.health_check", return_value=(True, "ok")
            ):
                self.assertEqual(manager.ensure(runtime_a).action, "started")
                self.assertEqual(manager.ensure(runtime_a).action, "reused")
                self.assertEqual(manager.ensure(runtime_b).action, "started")
            self.assertEqual(events, ["start:a.gguf", "stop:a.gguf", "start:b.gguf"])

    def test_stop_owned_requires_token_and_full_identity_match(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            identity = self.identity(runtime)
            self.write_state(manager, identity)
            with patch(
                "eagle.runtime.processes.identity_matches_process", return_value=True
            ), patch("eagle.runtime.processes.terminate_pid") as terminate:
                manager.stop_owned()
            terminate.assert_called_once_with(identity.pid, 5.0)
            self.assertFalse(runtime.ownership_path.exists())

            other = RuntimeManager(runtime)
            other._owned_identity = identity
            manager._owned_identity = identity
            manager._write_ownership_state(identity)
            with patch("eagle.runtime.processes.terminate_pid") as terminate:
                with self.assertRaisesRegex(RuntimeError, "Refusing to stop"):
                    other.stop_owned()
            terminate.assert_not_called()
            self.assertTrue(runtime.ownership_path.exists())

    def test_dead_owned_process_removes_state_without_signalling_reused_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            identity = self.identity(runtime)
            self.write_state(manager, identity)
            with patch(
                "eagle.runtime.processes.identity_matches_process", return_value=False
            ), patch("eagle.runtime.processes.terminate_pid") as terminate:
                manager.stop_owned()
            terminate.assert_not_called()
            self.assertFalse(runtime.ownership_path.exists())

    def test_keyboard_interrupt_removes_state_when_controlled_owned_process_is_dead(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                start_new_session=True,
            )
            try:
                from eagle.runtime.processes import process_identity

                identity = None
                for _ in range(100):
                    identity = process_identity(process.pid)
                    if identity is not None:
                        break
                self.assertIsNotNone(identity)
                assert identity is not None
                self.write_state(manager, identity)

                def terminate_then_interrupt(pid: int, timeout: float) -> None:
                    self.assertEqual((pid, timeout), (identity.pid, 5.0))
                    process.terminate()
                    process.wait(timeout=5)
                    raise KeyboardInterrupt

                with patch(
                    "eagle.runtime.processes.terminate_pid",
                    side_effect=terminate_then_interrupt,
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        manager.stop_owned()
                self.assertFalse(runtime.ownership_path.exists())
                self.assertIsNone(manager._owned_identity)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def test_ownership_write_failure_terminates_new_child(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.make_runtime(Path(directory))
            manager = RuntimeManager(runtime)
            identity = self.identity(runtime)
            process = type("Process", (), {"pid": identity.pid, "poll": lambda self: None})()
            with patch.object(manager, "_reconcile_ownership_state"), patch.object(
                manager, "_reconcile_legacy_pid_state"
            ), patch(
                "eagle.runtime.processes.discover_listening_server_pid", return_value=None
            ), patch(
                "eagle.runtime.processes.port_occupied", return_value=False
            ), patch(
                "eagle.runtime.processes.subprocess.Popen", return_value=process
            ), patch(
                "eagle.runtime.processes._wait_for_process_identity", return_value=identity
            ), patch.object(
                manager, "_write_ownership_state", side_effect=OSError("disk full")
            ), patch("eagle.runtime.processes.terminate_pid") as terminate:
                with self.assertRaisesRegex(OSError, "disk full"):
                    manager.start()
            terminate.assert_called_once_with(identity.pid, 5.0)
            self.assertIsNone(manager._owned_identity)


if __name__ == "__main__":
    unittest.main()
