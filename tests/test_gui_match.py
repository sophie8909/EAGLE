from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from eagle.opponents import GUI_ONLY_OPPONENTS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "run_gui_match.py"
SPEC = importlib.util.spec_from_file_location("run_gui_match", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gui)


class GuiMatchOpponentTests(unittest.TestCase):
    def test_allibot_is_gui_only(self):
        self.assertEqual([item.opponent_id for item in GUI_ONLY_OPPONENTS], ["allibot"])

    def test_allibot_resolution_uses_upstream_runtime_first_and_disables_llm_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jar = root / "third_party" / "gui_opponents" / "jars" / "allibot.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"allibot")
            library = root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib" / "gson.jar"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"library")
            resolved_path = root / "third_party" / "gui_opponents" / "resolved_allibot.json"
            resolved_path.write_text(json.dumps({
                "schema_version": "eagle-allibot-v2",
                "class_name": "ai.abstraction.submissions.allibot.alli",
                "jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            with patch.object(gui, "REPOSITORY_ROOT", root), patch.object(
                gui, "ALLIBOT_RESOLVED_MANIFEST", resolved_path
            ):
                opponent = gui.resolve_opponent("allibot")
                safe_opponent = gui.resolve_opponent("allinbot")
                enabled = gui.resolve_opponent(
                    "allibot",
                    enable_allibot_runtime_llm=True,
                    allibot_llama_cpp_url="http://llama.example:8080/",
                    allibot_llama_cpp_model="test-model",
                )

        self.assertEqual(opponent.class_name, "ai.abstraction.submissions.allibot.alli")
        self.assertEqual(opponent.classpath_before_runtime, (jar, library))
        self.assertEqual(safe_opponent.class_name, "ai.eagle.SafeAllInBot")
        self.assertEqual(safe_opponent.classpath_before_runtime, ())
        self.assertEqual(safe_opponent.classpath_after_runtime, (jar, library))
        self.assertEqual(safe_opponent.environment, opponent.environment)
        self.assertEqual(
            opponent.environment,
            {"ALLI_USE_SEARCH_LLM": "false", "ALLI_SMALLMAP_LLM_ADVISOR": "false"},
        )
        self.assertEqual(
            enabled.environment,
            {"LLAMA_CPP_BASE_URL": "http://llama.example:8080", "LLAMA_CPP_MODEL": "test-model"},
        )

    def test_allibot_jar_precedes_candidate_and_vendored_runtime(self):
        command = gui.build_command(
            classes_dir=Path("/candidate/classes"),
            microrts_dir=Path("/microrts"),
            opponent_class="ai.abstraction.submissions.allibot.alli",
            classpath_before_runtime=(Path("/allibot.jar"),),
            classpath_after_runtime=(),
            map_path="maps/8x8/basesWorkers8x8.xml",
            cycles=100,
            interval_ms=20,
            candidate_player=0,
            workspace=Path("/workspace"),
        )
        classpath = command[command.index("-cp") + 1].split(os.pathsep)
        self.assertEqual(classpath[:3], ["/allibot.jar", "/candidate/classes", "/microrts/bin"])

    def test_default_opponent_resolves(self):
        args = gui.build_parser().parse_args(["--run-dir", "run", "--candidate-id", "candidate"])
        self.assertEqual(gui.resolve_opponent(args.opponent).class_name, "ai.abstraction.LightRush")

    def test_main_prepares_canonical_adapters_in_temporary_workspace(self):
        for opponent_id, helper_name in (
            ("allinbot", "_prepare_safe_allinbot_opponent"),
            ("workerrush", "_prepare_worker_rush_opponent"),
        ):
            with self.subTest(opponent=opponent_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "CandidateAgent.java"
                source.write_text("package ai.generated; public class CandidateAgent {}")
                jar = root / "upstream.jar"
                adapter = root / "adapter"
                resolved = gui.ResolvedOpponent("ai.test.Opponent", classpath_after_runtime=(jar,))
                with (
                    patch.object(gui, "load_candidate_source", return_value=source),
                    patch.object(gui, "resolve_opponent", return_value=resolved),
                    patch.object(gui, "compile_generated_agent", return_value=SimpleNamespace(ok=True)),
                    patch.object(gui, "integrate_microrts_agent", return_value=SimpleNamespace(ok=True)),
                    patch.object(gui, helper_name, return_value=adapter) as prepare,
                    patch.object(gui.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run,
                ):
                    result = gui.main([
                        "--run-dir", str(root), "--candidate-id", "candidate",
                        "--microrts-dir", str(root), "--opponent", opponent_id,
                    ])
                self.assertEqual(result, 0)
                self.assertEqual(prepare.call_args.args[0].microrts_dir, root.resolve())
                self.assertFalse(prepare.call_args.kwargs["classes_dir"].exists())
                command = run.call_args.args[0]
                classpath = command[command.index("-cp") + 1].split(os.pathsep)
                self.assertEqual(classpath[-2:], [str(adapter), str(jar)])


    def test_canonical_candidate_source_does_not_require_generation_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "candidates/current"
            (folder / "phenotype").mkdir(parents=True)
            (folder / "candidate.json").write_text(json.dumps({"candidate_id": "current"}))
            source = folder / "phenotype/CandidateAgent.java"
            source.write_text("package ai.generated; public class CandidateAgent {}")
            self.assertEqual(gui.load_candidate_source(root, "current"), source)


if __name__ == "__main__":
    unittest.main()
