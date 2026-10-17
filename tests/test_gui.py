from __future__ import annotations

import http.client
import json
import signal
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from eagle.cli.gui import IS_WINDOWS, GuiApp, GuiServer, Job, form_options


class GuiAppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runs = self.root / "runs"
        self.app = GuiApp(self.root, self.runs)
        self.process = Mock(pid=12345)
        self.process.poll.return_value = None

    def run_fixture(self):
        run = self.runs / "example"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text('{"schema_version":"eagle-run-v2"}', encoding="utf-8")
        # Observation must not reject historical runtime fields as resume would.
        (run / "config.yaml").write_text("model: {gpu_layers: 999, threads: 8, parallel: 2}", encoding="utf-8")
        map_file = self.root / "third_party/microrts/maps/8x8/test.xml"
        map_file.parent.mkdir(parents=True)
        map_file.write_text("<map/>", encoding="utf-8")
        return run, map_file

    def test_form_options_serialize_and_use_canonical_values(self):
        options = json.loads(json.dumps(form_options()))
        self.assertIn("framework_slots", options["choices"]["java_materialization_mode"])
        self.assertEqual(options["choices"]["survivor_selection"], ["mu_plus_lambda"])
        self.assertTrue(options["defaults"]["evaluation.swap_player_sides"])

    def test_start_uses_immutable_snapshot_and_canonical_experiment_flags(self):
        config_dir = self.root / "configs"
        config_dir.mkdir()
        original = config_dir / "example.yaml"
        text = "experiment_name: initial\ngenerations: 2\n"
        original.write_text(text, encoding="utf-8")
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            result = self.app.post("/api/start", {"path": "configs/example.yaml", "text": text, "mock": True, "skip_final_test": True})
        command = start.call_args.args[0]
        self.assertEqual(command[:6], [sys.executable, "-u", "-m", "eagle", "experiment", "--config-dir"])
        snapshot = Path(command[6])
        self.assertNotEqual(snapshot, original)
        self.assertEqual(command[7:], ["--mock", "--skip-final-test"])
        self.assertEqual(snapshot.read_text(encoding="utf-8"), text)
        original.write_text("experiment_name: modified", encoding="utf-8")
        self.assertEqual(snapshot.read_text(encoding="utf-8"), text)
        self.assertTrue(result["running"])
        if IS_WINDOWS:
            self.assertIn("creationflags", start.call_args.kwargs)
        else:
            self.assertTrue(start.call_args.kwargs["start_new_session"])
        self.assertEqual(start.call_args.kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(start.call_args.kwargs["cwd"], self.root)

    def test_duplicate_experiment_is_rejected_without_launching_second_process(self):
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/start", {"text": "{}"})
            with self.assertRaisesRegex(ValueError, "already running"):
                self.app.post("/api/start", {"text": "{}"})
        self.assertEqual(start.call_count, 1)

    def test_flag_values_must_be_actual_booleans(self):
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/start", {"text": "{}", "mock": "true", "skip_final_test": 1})
        command = start.call_args.args[0]
        self.assertNotIn("--mock", command)
        self.assertNotIn("--skip-final-test", command)

    def test_read_config_discovers_custom_runs_root(self):
        config = self.root / "configs" / "custom.yaml"
        config.parent.mkdir()
        config.write_text("runs_dir: alternate_runs", encoding="utf-8")
        result = self.app.get("/api/config", {"path": ["configs/custom.yaml"]})
        self.assertEqual(result["payload"]["runs_dir"], "alternate_runs")
        self.assertIn(self.root / "alternate_runs", self.app.runs_roots)

    def test_parse_render_and_validate_preserve_unknown_payload(self):
        payload = {"experiment_name": "測試", "custom": {"future": [1, True]}}
        text = self.app.post("/api/render", {"payload": payload})["text"]
        self.assertEqual(self.app.post("/api/parse", {"text": text})["payload"], payload)
        self.assertIn("message", self.app.post("/api/validate", {"text": text}))
        for path, body in (("/api/parse", {"text": "[]"}), ("/api/render", {"payload": []}), ("/api/validate", {"text": "generations: 0"})):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.app.post(path, body)
        with self.assertRaises(yaml.YAMLError):
            self.app.post("/api/parse", {"text": "value: ["})

    def test_legacy_probabilities_keep_effective_meaning_when_form_is_edited(self):
        from eagle.config import ExperimentConfig

        original = {"strategy_reflection_probability": 0.4, "code_reflection_probability": 0.6}
        parsed = self.app.post("/api/parse", {"text": yaml.safe_dump(original)})["payload"]
        parsed["experiment_name"] = "edited"
        config = ExperimentConfig.from_mapping(parsed, base_dir=self.root)
        self.assertEqual(config.prompt_reflection_probability, 0.6)
        self.assertEqual(config.code_reflection_probability, 0.0)
        self.assertNotIn("population_size", parsed)
        saved = self.app.post("/api/save", {"path": "configs/legacy.yaml", "text": yaml.safe_dump(original)})
        self.assertEqual(saved["payload"]["prompt_reflection_probability"], 0.6)
        self.assertEqual(saved["payload"]["code_reflection_probability"], 0.0)

    def test_watch_constructs_command_without_modifying_run_or_fitness(self):
        run, map_file = self.run_fixture()
        before = {str(path.relative_to(run)): path.read_bytes() for path in run.rglob("*") if path.is_file()}
        with patch("scripts.run_gui_match.load_candidate_source") as source, patch("scripts.run_gui_match.resolve_opponent") as opponent, patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/watch", {"run": str(run), "candidate": "candidate_1", "opponent": "workerrush", "map": "maps/8x8/test.xml", "cycles": 321, "interval_ms": 4, "side": 1})
        command = start.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-u", str(self.root / "scripts/run_gui_match.py")])
        flags = dict(zip(command[3::2], command[4::2]))
        self.assertEqual(flags["--run-dir"], str(run))
        self.assertEqual(flags["--candidate-id"], "candidate_1")
        self.assertEqual(flags["--opponent"], "workerrush")
        self.assertEqual(flags["--map-path"], str(map_file))
        self.assertEqual(flags["--cycles"], "321")
        self.assertEqual(flags["--interval-ms"], "4")
        self.assertEqual(flags["--candidate-player"], "1")
        source.assert_called_once_with(run, "candidate_1")
        opponent.assert_called_once_with("workerrush")
        after = {str(path.relative_to(run)): path.read_bytes() for path in run.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_watch_and_run_reject_traversal_before_launch(self):
        run, _ = self.run_fixture()
        body = {"run": str(run), "candidate": "candidate_1", "opponent": "workerrush", "map": "maps/8x8/test.xml", "cycles": 1, "interval_ms": 0, "side": 0}
        with patch("scripts.run_gui_match.load_candidate_source"), patch("scripts.run_gui_match.resolve_opponent"), patch("eagle.cli.gui.subprocess.Popen") as start:
            for change in ({"candidate": "../escape"}, {"candidate": ".."}, {"map": "../../../escape.xml"}, {"run": str(self.root / "other")}, {"opponent": "java.unregistered.Agent"}, {"cycles": 0}, {"side": 2}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.app.post("/api/watch", {**body, **change})
        start.assert_not_called()

    def test_resume_uses_canonical_run_and_flags(self):
        run, _ = self.run_fixture()
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/resume", {"run": str(run), "mock": True, "skip_final_test": True})
        self.assertEqual(start.call_args.args[0], [sys.executable, "-u", "-m", "eagle", "experiment", "--resume", str(run), "--mock", "--skip-final-test"])

    @unittest.skipIf(IS_WINDOWS, "POSIX process groups")
    def test_stop_targets_experiment_process_and_match_process_group(self):
        self.app.experiment.process = self.process
        match_process = Mock(pid=54321)
        match_process.poll.return_value = None
        self.app.match.process = match_process
        with patch("eagle.cli.gui.os.killpg", create=True) as kill_group:
            self.app.post("/api/stop-experiment", {})
            self.app.post("/api/stop-experiment", {})
            self.app.post("/api/stop-match", {})
            self.app.post("/api/stop-match", {})
        self.process.send_signal.assert_called_once_with(signal.SIGTERM)
        match_process.send_signal.assert_not_called()
        kill_group.assert_called_once_with(54321, signal.SIGTERM)
        self.assertTrue(self.app.experiment.status()["stopping"])

    def test_windows_jobs_use_owned_console_group_and_break_signal(self):
        with (
            patch("eagle.cli.gui.IS_WINDOWS", True),
            patch("eagle.cli.gui.subprocess.CREATE_NEW_PROCESS_GROUP", 512, create=True),
            patch("eagle.cli.gui.signal.CTRL_BREAK_EVENT", 1, create=True),
            patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start,
        ):
            self.app.experiment.start(["python", "-m", "eagle", "experiment"], self.root / "job")
            self.app.experiment.stop()
            self.app.match.process = self.process
            self.app.match.stop()
        self.assertEqual(start.call_args.kwargs["creationflags"], 512)
        self.assertNotIn("start_new_session", start.call_args.kwargs)
        self.assertEqual(self.process.send_signal.call_count, 2)
        self.process.send_signal.assert_called_with(1)

    def test_job_log_tail_is_bounded_and_reports_failure(self):
        job = Job(self.root, "match")
        job.process = self.process
        job.log = self.root / "match.log"
        job.log.write_bytes(b"old" * 12000 + b"tail")
        self.process.poll.return_value = 7
        result = job.status()
        self.assertEqual(len(result["output"]), 32000)
        self.assertTrue(result["output"].endswith("tail"))
        self.assertEqual(result["returncode"], 7)
        self.assertFalse(result["running"])
        self.assertFalse(result["stopping"])


class GuiHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.app = GuiApp(root, root / "runs")
        self.server = GuiServer(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.host = f"127.0.0.1:{self.server.server_port}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        self.addCleanup(connection.close)
        data = None if body is None else json.dumps(body)
        request_headers = {"Host": self.host, "Origin": self.server.origin, "X-Eagle-Token": self.app.token}
        request_headers.update(headers or {})
        connection.request(method, path, body=data, headers=request_headers)
        response = connection.getresponse()
        content = response.read()
        return response.status, json.loads(content)

    def test_post_rejects_cross_origin_missing_token_and_untrusted_host_without_mutation(self):
        for headers in ({"Origin": "https://untrusted.example"}, {"Origin": "null"}, {"Origin": ""}, {"X-Eagle-Token": ""}, {"X-Eagle-Token": "wrong"}, {"Host": "untrusted.example"}):
            with self.subTest(headers=headers), patch.object(self.app, "post") as mutate:
                code, result = self.request("POST", "/api/start", {"text": "{}"}, headers)
                self.assertEqual(code, 403)
                self.assertIn("error", result)
                mutate.assert_not_called()

    def test_get_rejects_untrusted_host(self):
        with patch.object(self.app, "get") as read:
            code, _ = self.request("GET", "/api/status", headers={"Host": "localhost.evil"})
        self.assertEqual(code, 403)
        read.assert_not_called()

    def test_invalid_json_and_body_size_are_rejected_before_dispatch(self):
        for data, length in (("{", "1"), ("{}", "-1"), ("{}", "2000001")):
            with self.subTest(length=length), patch.object(self.app, "post") as dispatch:
                connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
                try:
                    connection.request("POST", "/api/start", body=data, headers={
                        "Host": self.host, "Origin": self.server.origin,
                        "X-Eagle-Token": self.app.token, "Content-Length": length,
                    })
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400)
                    self.assertIn("error", json.loads(response.read()))
                finally:
                    connection.close()
                dispatch.assert_not_called()

    def test_valid_api_requests_and_malformed_payloads_return_json(self):
        code, result = self.request("POST", "/api/parse", {"text": "experiment_name: 測試\ncustom: 9"})
        self.assertEqual(code, 200)
        self.assertEqual(result["payload"]["custom"], 9)
        code, result = self.request("POST", "/api/render", {"payload": {"experiment_name": "測試"}})
        self.assertEqual(code, 200)
        self.assertEqual(yaml.safe_load(result["text"])["experiment_name"], "測試")
        for path, body in (("/api/parse", {"text": "value: ["}), ("/api/parse", {"text": "[]"}), ("/api/render", {"payload": []}), ("/api/validate", {"text": "generations: 0"}), ("/api/validate", {}), ("/api/start", [])):
            with self.subTest(path=path, body=body):
                code, result = self.request("POST", path, body)
                self.assertEqual(code, 400)
                self.assertIn("error", result)
        code, result = self.request("POST", "/api/validate", {"text": "{}"})
        self.assertEqual(code, 200)
        self.assertIn("message", result)


if __name__ == "__main__":
    unittest.main()
