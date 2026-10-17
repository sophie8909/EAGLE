from __future__ import annotations

import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from eagle.runtime import processes


class WindowsProcessTests(unittest.TestCase):
    def test_identity_uses_one_windows_snapshot_and_native_arguments(self):
        record = {
            "start_time": 123456789, "executable": "C:/llama/llama-server.exe",
            "command": '"C:/llama/llama-server.exe" --model "C:/models/a b.gguf"',
            "parent_pid": 42,
        }
        command = (record["executable"], "--model", "C:/models/a b.gguf")
        with patch.object(processes, "_WINDOWS", True), patch.object(
            processes, "_windows_process_record", return_value=record
        ) as snapshot, patch.object(processes, "_windows_command_args", return_value=command):
            identity = processes.process_identity(100)
        self.assertEqual(identity, processes.ProcessIdentity(100, 123456789, record["executable"], command))
        snapshot.assert_called_once_with(100)

    def test_unreadable_windows_identity_is_not_owned(self):
        with patch.object(processes, "_WINDOWS", True), patch.object(
            processes, "_windows_process_record", return_value={"start_time": 1, "executable": None}
        ):
            self.assertIsNone(processes.process_identity(100))

    def test_windows_listener_lookup_rejects_non_listening_connections(self):
        output = (
            "  TCP  127.0.0.1:18080  127.0.0.1:9000  ESTABLISHED  15\n"
            "  TCP  [::]:18080  [::]:0  LISTENING  42\n"
        )
        with patch.object(processes, "_WINDOWS", True), patch.object(
            processes.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")
        ):
            self.assertEqual(processes.discover_listening_server_pid("127.0.0.1", 18080), 42)

    def test_failed_windows_inspection_returns_no_identity(self):
        for failure in (OSError("unavailable"), subprocess.TimeoutExpired("powershell.exe", 5)):
            with self.subTest(failure=failure), patch.object(processes.subprocess, "run", side_effect=failure):
                self.assertIsNone(processes._windows_process_record(100))

    def test_windows_termination_does_not_use_sigkill(self):
        with patch.object(processes, "_WINDOWS", True), patch.object(
            processes.os, "kill"
        ) as kill, patch.object(processes, "process_alive", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "did not exit"):
                processes.terminate_pid(100, 0)
        kill.assert_called_once_with(100, processes.signal.SIGTERM)

    def test_windows_server_name_preserves_ownership_checks(self):
        root = Path.cwd()
        runtime = SimpleNamespace(project_root=root, llm=SimpleNamespace(host="127.0.0.1", port=18080))
        command = ("llama-server.exe", "--host", "127.0.0.1", "--port", "18080")
        for filename, trusted in (("llama-server.exe", True), ("python.exe", False)):
            identity = processes.ProcessIdentity(100, 123, str(root / filename), command)
            record = {
                "project_root": str(root), "pid": 100, "process_start_time": 123,
                "executable": identity.executable, "command": list(command),
            }
            with self.subTest(filename=filename):
                self.assertEqual(processes._record_is_trusted(record, runtime), trusted)
                self.assertEqual(processes._legacy_identity_is_trusted(identity, runtime), trusted)

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows")
    def test_native_windows_argument_parser_preserves_quotes_unicode_and_backslashes(self):
        arguments = (sys.executable, "", 'argument with "quotes"', "模型 路徑", "C:\\models with spaces\\")
        self.assertEqual(processes._windows_command_args(subprocess.list2cmdline(arguments)), arguments)

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows")
    def test_live_windows_child_identity_and_termination(self):
        marker = "a quoted argument with spaces"
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", marker])
        try:
            identity = processes.process_identity(child.pid)
            self.assertIsNotNone(identity)
            assert identity is not None
            self.assertEqual(identity.command[-1], marker)
            self.assertEqual(Path(identity.executable).resolve(), Path(sys.executable).resolve())
            self.assertEqual(processes.read_parent_pid(child.pid), os.getpid())
            self.assertTrue(processes.identity_matches_process(identity))
            changed = processes.ProcessIdentity(identity.pid, identity.start_time + 1, identity.executable, identity.command)
            self.assertFalse(processes.identity_matches_process(changed))
            processes.terminate_pid(child.pid, 5)
            child.wait(timeout=5)
            self.assertFalse(processes.process_alive(child.pid))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows")
    def test_live_windows_listener_pid(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            self.assertTrue(processes.port_occupied("127.0.0.1", listener.getsockname()[1]))
            self.assertEqual(
                processes.discover_listening_server_pid("127.0.0.1", listener.getsockname()[1]),
                os.getpid(),
            )


if __name__ == "__main__":
    unittest.main()
