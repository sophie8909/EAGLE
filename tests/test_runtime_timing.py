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
        self.assertEqual(command[-6:], ["--ctx-size", "32768", "--host", "127.0.0.1", "--port", "8080"])

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
