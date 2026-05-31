"""Tests for MicroRTS Java command construction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.envs.microrts import runner


class MicroRTSRunnerCommandTests(unittest.TestCase):
    def test_launch_java_match_omits_call_limit_when_unlimited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            captured: dict[str, object] = {}
            microrts_root = tmp_path / "microrts"
            microrts_root.mkdir()

            class FakeProcess:
                def wait(self, timeout: int | None = None) -> int:
                    return 0

                def kill(self) -> None:
                    return None

            def fake_popen(command, **kwargs):
                captured["command"] = list(command)
                captured["cwd"] = kwargs.get("cwd")
                return FakeProcess()

            with (
                patch.object(runner, "locate_microrts_root", return_value=microrts_root),
                patch.object(runner.subprocess, "Popen", side_effect=fake_popen),
            ):
                runner.launch_java_match(
                    project_root=tmp_path,
                    tick_limit=10,
                    log_path=tmp_path / "match.log",
                    ai1_class="ai.eagle.EAGLE",
                    ai2_class="ai.abstraction.HeavyRush",
                    llm_interval=5,
                    llm_call_limit=None,
                )

            command = captured["command"]
            self.assertIn("-Dmicrorts.llm_interval=5", command)
            self.assertFalse(any(str(arg).startswith("-Dmicrorts.llm_call_limit=") for arg in command))
            self.assertEqual(captured["cwd"], microrts_root)


if __name__ == "__main__":
    unittest.main()
