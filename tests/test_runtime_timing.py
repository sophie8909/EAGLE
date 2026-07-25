import json
import tempfile
import unittest
from pathlib import Path

from eagle.analysis.timing import summarize_run_timing
from eagle.runtime.server_manager import LLMServerManager, ServerSpec


class RuntimeTimingTests(unittest.TestCase):
    def test_server_command_uses_one_canonical_shape(self):
        command = LLMServerManager.build_command(
            ServerSpec("local", Path("model.gguf"), Path("llama-server"), "model", "127.0.0.1", 8080)
        )
        self.assertIn(["--reasoning", "off"], [command[index:index + 2] for index in range(len(command) - 1)])
        self.assertIn(["--parallel", "1"], [command[index:index + 2] for index in range(len(command) - 1)])
        self.assertIn("--threads", command)
        self.assertIn("--threads-batch", command)
        self.assertEqual(command[-6:], ["--ctx-size", "32768", "--host", "127.0.0.1", "--port", "8080"])

    def test_model_discovery_returns_only_unique_supported_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_root = root / "experiment_env" / "model"
            for name in (
                "qwen3-8b-q4-k-m/model.gguf",
                "qwen3-8b-q4-k-m-duplicate/model.gguf",
                "qwen3-5-9b/model.gguf",
                "meta-llama-3-1-8b/model.gguf",
                "llama.cpp/models/ggml-vocab-qwen35.gguf",
                "llama3-2/model.gguf",
            ):
                target = model_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()

            discovered = LLMServerManager(root).discover_models()

            self.assertEqual([path.parent.name for path in discovered], [
                "qwen3-8b-q4-k-m",
                "qwen3-5-9b",
                "meta-llama-3-1-8b",
            ])

    def test_project_server_discovery_only_matches_repo_owned_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            proc_root = root / "proc"
            server = root / "experiment_env" / "model" / "llama.cpp" / "bin" / "llama-server"
            model = root / "experiment_env" / "model" / "qwen3" / "model.gguf"
            cached_model = root.parent / "cache" / "qwen3.gguf"
            server.parent.mkdir(parents=True)
            model.parent.mkdir(parents=True)
            cached_model.parent.mkdir(parents=True)
            server.touch()
            cached_model.touch()
            model.symlink_to(cached_model)
            commands = {
                101: (str(server), "--model", str(model), "--port", "8080"),
                102: ("/usr/bin/llama-server", "--model", str(model), "--port", "8081"),
                103: (str(server), "--model", "/tmp/unrelated.gguf", "--port", "8082"),
            }
            for pid, command in commands.items():
                process_dir = proc_root / str(pid)
                process_dir.mkdir(parents=True)
                (process_dir / "cmdline").write_bytes(b"\0".join(part.encode() for part in command) + b"\0")

            discovered = LLMServerManager(root).discover_project_server_pids(proc_root=proc_root)

            self.assertEqual(discovered, (101,))

    def test_timing_analysis_reads_generation_and_operation_records(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "candidates" / "child").mkdir(parents=True)
            (run_dir / "timing.jsonl").write_text(
                json.dumps({"event": "generation", "generation": 0, "duration_seconds": 2.5}) + "\n",
                encoding="utf-8",
            )
            (run_dir / "candidates" / "child" / "timing.json").write_text(
                json.dumps({"mutation": {"generation_only_duration_seconds": 1.25, "status": "success"}}),
                encoding="utf-8",
            )
            summary = summarize_run_timing(run_dir)
            self.assertEqual(summary["total_run_duration_seconds"], 2.5)
            self.assertEqual(summary["operation_records"][0]["duration_seconds"], 1.25)


if __name__ == "__main__":
    unittest.main()
