"""Tests for MicroRTS Java command construction."""

from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
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
            self.assertIn("-Deagle.skip_same_behavior_state=true", command)
            self.assertFalse(any(str(arg).startswith("-Dmicrorts.llm_call_limit=") for arg in command))
            self.assertEqual(captured["cwd"], microrts_root)

    def test_launch_java_match_can_disable_same_behavior_skip(self) -> None:
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
                return FakeProcess()

            with (
                patch.object(runner, "locate_microrts_root", return_value=microrts_root),
                patch.object(runner.subprocess, "Popen", side_effect=fake_popen),
            ):
                runner.launch_java_match(
                    project_root=tmp_path,
                    tick_limit=10,
                    log_path=tmp_path / "match.log",
                    skip_same_behavior_state=False,
                )

            self.assertIn("-Deagle.skip_same_behavior_state=false", captured["command"])

    def test_prompt_based_game_uses_configured_agent_class(self) -> None:
        config = SimpleNamespace(agent_class="ai.eagle.EAGLERepair")
        captured: dict[str, object] = {}

        def fake_run_java_agent_game(**kwargs):
            captured.update(kwargs)
            return {}, {}

        with patch.object(runner, "run_java_agent_game", side_effect=fake_run_java_agent_game):
            runner.run_prompt_based_game(
                project_root=Path("."),
                config=config,
                prompt="prompt",
                opponent="ai.abstraction.HeavyRush",
            )

        self.assertEqual(captured["ai1_class"], "ai.eagle.EAGLERepair")

    def test_prompt_based_game_defaults_missing_agent_class(self) -> None:
        captured: dict[str, object] = {}

        def fake_run_java_agent_game(**kwargs):
            captured.update(kwargs)
            return {}, {}

        with patch.object(runner, "run_java_agent_game", side_effect=fake_run_java_agent_game):
            runner.run_prompt_based_game(
                project_root=Path("."),
                config=SimpleNamespace(),
                prompt="prompt",
                opponent="ai.abstraction.HeavyRush",
            )

        self.assertEqual(captured["ai1_class"], "ai.eagle.EAGLE")


if __name__ == "__main__":
    unittest.main()
