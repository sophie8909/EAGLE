import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from eagle_ui.controllers.run_controller import RunController
from eagle_ui.state import RunState


class RunControllerCaptureTests(unittest.TestCase):
    def test_candidate_started_progress_updates_identity_without_incrementing_counts(self):
        state = RunState()
        controller = RunController(Path.cwd(), state)

        controller._apply_progress(
            "[gen 0 cand 1/10] candidate-a stage=generation status=started"
        )

        self.assertEqual(state.current_generation, 0)
        self.assertEqual(state.current_candidate, "candidate-a")
        self.assertEqual(state.completed_candidates, 0)
        self.assertEqual(state.failed_candidates, 0)

    def test_resolves_the_llm_port_used_by_the_selected_ea_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "llm_topology.json"
            topology.write_text(
                """{
  "version": 1,
  "servers": {
    "local": {
      "base_url": "http://127.0.0.1:8123/v1",
      "model_id": "qwen3.5"
    }
  },
  "roles": {
    "reflector": {"server_id": "local"},
    "rewriter": {"server_id": "local"},
    "generator": {"server_id": "local"}
  }
}
""",
                encoding="utf-8",
            )
            config = root / "eagle.yaml"
            config.write_text(
                "\n".join(
                    (
                        "seed_prompts:",
                        '  - "seed"',
                        'generation_backend: "openai"',
                        f'llm_role_topology_path: "{topology}"',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            controller = RunController(root, RunState())

            connection = controller.resolve_llm_connection(config)

            self.assertEqual(connection.port_text, "8123")
            self.assertEqual(connection.endpoint_text, "http://127.0.0.1:8123/v1")
            self.assertEqual(connection.model_text, "qwen3.5")
            self.assertEqual(connection.topology_path, topology)

    def test_mock_ea_displays_mock_instead_of_a_stale_llm_port(self):
        controller = RunController(Path.cwd(), RunState())

        connection = controller.resolve_llm_connection(
            Path("configs/eagle_10x50.yaml"),
            mock=True,
        )

        self.assertEqual(connection.port_text, "mock")
        self.assertEqual(connection.endpoint_text, "mock")

    def test_drains_stdout_and_stderr_and_keeps_nonzero_exit(self):
        state = RunState()
        controller = RunController(Path.cwd(), state)
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        controller._process = process
        readers = [
            threading.Thread(target=controller._read_stream, args=(process.stdout, "stdout")),
            threading.Thread(target=controller._read_stream, args=(process.stderr, "stderr")),
        ]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join()
        controller._wait_for_exit()
        records = state.logs.snapshot()
        self.assertEqual(set(record.stream for record in records), {"stdout", "stderr", "system"})
        self.assertEqual(records[-1].stream, "system")
        self.assertIn("code 3", records[-1].message)
        self.assertNotIn("llm server error", [record.message for record in records])
        process.stdout.close(); process.stderr.close()

    def test_exit_code_two_is_shown_as_llm_server_error(self):
        state = RunState()
        controller = RunController(Path.cwd(), state)
        controller._process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(2)"])

        controller._wait_for_exit()

        self.assertIn("llm server error", [record.message for record in state.logs.snapshot()])


if __name__ == "__main__":
    unittest.main()
