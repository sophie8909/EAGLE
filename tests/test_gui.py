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
from eagle.cli.gui_launcher import INSTANCE_PATH, SHUTDOWN_PATH, _request, supervise_gui
from eagle.config import ExperimentConfig


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
        self.assertEqual(options["defaults"]["evaluation.parallel_match_workers"], 10)
        self.assertEqual(options["choices"]["evaluation.match_execution"], ["parallel", "serial"])

    def test_match_worker_count_is_saved_and_passed_to_the_experiment_snapshot(self):
        payload = {"evaluation": {"parallel_match_workers": 3}}
        saved = self.app.post("/api/save", {"path": "configs/example.yaml", "payload": payload})
        self.assertEqual(saved["payload"], payload)

        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/start", {"payload": saved["payload"]})

        snapshot = Path(start.call_args.args[0][6]) / "config.yaml"
        config = ExperimentConfig.from_file(snapshot)
        self.assertEqual(config.match_workers, 3)
        self.assertEqual(ExperimentConfig.from_mapping(config.to_mapping()).match_workers, 3)

    def test_start_rejects_invalid_match_worker_counts(self):
        with patch.object(self.app.experiment, "start") as start:
            for workers in (0, -1, 1.5, True, "3"):
                payload = {"evaluation": {"parallel_match_workers": workers}}
                with self.subTest(workers=workers), self.assertRaisesRegex(
                    ValueError, "evaluation.parallel_match_workers must be a positive integer"
                ):
                    self.app.post("/api/start", {"payload": payload})
            start.assert_not_called()

    def test_server_start_uses_separate_job_and_snapshot(self):
        text = "model: {name: local, path: model.gguf, llama_server: llama-server}\n"
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/start-server", {"text": text})
        command = start.call_args.args[0]
        self.assertEqual(command[:6], [sys.executable, "-u", "-m", "eagle", "server", "--config"])
        self.assertEqual(Path(command[6]).read_text(encoding="utf-8"), text)
        self.assertIsNone(self.app.experiment.process)
        self.assertTrue(self.app.get("/api/status", {})["server"]["running"])
        self.app.post("/api/stop-experiment", {})
        self.process.send_signal.assert_not_called()
        with patch("eagle.cli.gui.IS_WINDOWS", False):
            self.app.post("/api/stop-server", {})
        self.process.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_server_controls_reject_changes_during_experiment(self):
        self.app.experiment.process = self.process
        text = "model: {name: local, path: model.gguf, llama_server: llama-server}\n"
        with patch("eagle.cli.gui.subprocess.Popen") as start:
            for route in ("/api/start-server", "/api/stop-server"):
                with self.subTest(route=route), self.assertRaises(ValueError):
                    self.app.post(route, {"text": text})
        start.assert_not_called()

    def test_server_start_rejects_external_endpoint(self):
        with patch("eagle.cli.gui.subprocess.Popen") as start:
            with self.assertRaisesRegex(ValueError, "endpoint"):
                self.app.post("/api/start-server", {"text": "model: {name: remote, host: example.test, port: 1234}"})
        start.assert_not_called()

    def test_server_start_rejects_selected_remote_endpoint_with_retained_local_profile(self):
        text = """\
model: {name: local, path: model.gguf, llama_server: llama-server}
remote_model: {name: remote, host: example.test, port: 1234}
use_remote_llm: true
"""
        with patch("eagle.cli.gui.subprocess.Popen") as start:
            with self.assertRaisesRegex(ValueError, "endpoint"):
                self.app.post("/api/start-server", {"text": text})
        start.assert_not_called()

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
        snapshot = Path(command[6]) / "config.yaml"
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
        self.assertEqual(start.call_args.kwargs["env"]["PYTHONUNBUFFERED"], "1")
        self.assertEqual(start.call_args.kwargs["cwd"], self.root)

    def test_jobs_refresh_tracks_seed_and_generation_without_scanning_runs(self):
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process):
            self.app.post("/api/start", {"text": "random_seeds: [8, 9]\ngenerations: 50\n"})
        log = self.app.experiment.log
        log.write_text(
            "Run [1/2] random_seed=8\nGeneration 0: checkpoint complete\n"
            + ("match output\n" * 3000)
            + "Generation 1/50: started\n",
            encoding="utf-8",
        )
        with patch("eagle.cli.gui.list_runs", side_effect=AssertionError("jobs must not scan runs")):
            status = self.app.get("/api/jobs", {})["experiment"]
            self.assertNotIn("random_seed=8", status["output"])
            self.assertEqual(status["progress"], {
                "phase": "evolution", "seed": 8, "run_number": 1, "run_total": 2,
                "generation": 1, "total_generations": 50, "completed_generation": 0,
            })
            with log.open("a", encoding="utf-8") as stream:
                stream.write("starting generation=0 candidate=gen_0000_123 (2/110)\n")
            progress = self.app.get("/api/jobs", {})["experiment"]["progress"]
            self.assertEqual((progress["phase"], progress["generation"], progress["benchmark_number"]),
                             ("cross_generation", 0, 2))
            self.assertEqual(progress["benchmark_complete"], 1)
            with log.open("a", encoding="utf-8") as stream:
                stream.write("generation=0 candidate=gen_0000_123 status=complete\n")
            progress = self.app.get("/api/jobs", {})["experiment"]["progress"]
            self.assertEqual(progress["benchmark_complete"], 2)
            with log.open("a", encoding="utf-8") as stream:
                stream.write("Run [2/2] random_seed=9\nGeneration 0: initializing population\n")
            progress = self.app.get("/api/jobs", {})["experiment"]["progress"]
            self.assertEqual((progress["seed"], progress["generation"], progress["phase"]), (9, 0, "initialization"))
            self.assertNotIn("benchmark_number", progress)

    def test_jobs_refresh_reads_resume_checkpoint_and_waits_for_complete_progress_line(self):
        run, _ = self.run_fixture()
        (run / "config.yaml").write_text(
            "random_seed: 9\nrandom_seeds: [8, 9]\ngenerations: 50\n", encoding="utf-8",
        )
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process):
            status = self.app.post("/api/resume", {"run": str(run)})
        self.assertEqual(status["progress"], {"phase": "starting", "seed": 9, "total_generations": 50})
        log = self.app.experiment.log
        log.write_bytes(b"Generation 12/50: resuming from checkpoint\r\nGeneration 13/50: star")
        status = self.app.get("/api/jobs", {})["experiment"]
        self.assertTrue(status["output"].endswith("star"))
        self.assertEqual(status["progress"], {
            "phase": "resuming", "seed": 9, "generation": 12,
            "total_generations": 50, "completed_generation": 12,
        })
        with log.open("ab") as stream:
            stream.write(b"ted\r\n")
        progress = self.app.get("/api/jobs", {})["experiment"]["progress"]
        self.assertEqual((progress["phase"], progress["generation"], progress["completed_generation"]),
                         ("evolution", 13, 12))

    def test_connect_only_is_forwarded_for_start_and_resume(self):
        run, _ = self.run_fixture()
        for route, body in (
            ("/api/start", {"text": "{}"}),
            ("/api/resume", {"run": str(run)}),
        ):
            with self.subTest(route=route), patch.object(self.app.experiment, "start") as start:
                self.app.post(route, {**body, "connect_only": True})
                self.assertIn("--connect-only", start.call_args.args[0])
                self.assertNotIn("--llm-server-port", start.call_args.args[0])
                self.app.post(route, {**body, "connect_only": True, "llm_server_port": 12345})
                self.assertEqual(start.call_args.args[0][-3:], ["--connect-only", "--llm-server-port", "12345"])
                address = "http://192.168.1.136:1234"
                self.app.post(route, {**body, "connect_only": True, "llm_server_address": address})
                self.assertEqual(start.call_args.args[0][-3:], ["--connect-only", "--llm-server-url", address])

    def test_llm_server_address_persists_in_the_local_workspace(self):
        self.assertIsNone(self.app.metadata()["llm_server_address"])
        legacy = self.root / "logs/gui/llm-server-port.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("12345", encoding="utf-8")
        self.assertEqual(self.app.metadata()["llm_server_address"], 12345)
        address = "http://192.168.1.136:1234/v1"
        self.app.post("/api/llm-server-address", {"address": address})
        reopened = GuiApp(self.root, self.runs)
        self.assertEqual(reopened.metadata()["llm_server_address"], address)
        for invalid in (0, 65536, True, "12345", 12345.5, "http://host:65536",
                        "ftp://host:1234", "http://", "http://host/path?query", "http://user@host"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                reopened.post("/api/llm-server-address", {"address": invalid})
        self.assertEqual(reopened.metadata()["llm_server_address"], address)
        reopened.post("/api/llm-server-address", {"address": None})
        self.assertIsNone(self.app.metadata()["llm_server_address"])

    def test_llm_server_address_requires_connect_only_and_a_valid_address(self):
        with patch.object(self.app.experiment, "start") as start:
            with self.assertRaisesRegex(ValueError, "requires connect-only"):
                self.app.post("/api/start", {"text": "{}", "llm_server_address": "http://localhost:12345"})
            with self.assertRaisesRegex(ValueError, "valid HTTP"):
                self.app.post("/api/start", {"text": "{}", "connect_only": True, "llm_server_address": "http://"})
        start.assert_not_called()

    def test_duplicate_experiment_is_rejected_without_launching_second_process(self):
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/start", {"text": "{}"})
            with self.assertRaisesRegex(ValueError, "already running"):
                self.app.post("/api/start", {"text": "{}"})
        self.assertEqual(start.call_count, 1)

    def test_flag_values_must_be_actual_booleans(self):
        with patch("eagle.cli.gui.subprocess.Popen", return_value=self.process) as start:
            self.app.post("/api/start", {"text": "{}", "mock": "true", "skip_final_test": 1, "connect_only": "true"})
        command = start.call_args.args[0]
        self.assertNotIn("--connect-only", command)
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

    def test_resume_lists_and_launches_indexed_batches(self):
        batch_names = ["configs/experiments/batch", "logs/gui/job"]
        for name in batch_names:
            folder = self.root / name
            folder.mkdir(parents=True)
            (folder / "experiment.yaml").write_text(
                "schema_version: eagle-experiment-index-v1\nruns: {}\n", encoding="utf-8",
            )
        self.assertEqual(self.app.get("/api/meta", {})["batches"], sorted(batch_names, reverse=True))
        for name in batch_names:
            with self.subTest(name=name), patch.object(self.app.experiment, "start") as start:
                self.app.post("/api/resume", {"batch": name, "connect_only": True})
                self.assertEqual(start.call_args.args[0], [
                    sys.executable, "-u", "-m", "eagle", "experiment", "--resume",
                    str(self.root / name), "--connect-only",
                ])

    def test_resume_rejects_a_folder_without_an_index(self):
        folder = self.root / "configs/batch"
        folder.mkdir(parents=True)
        (folder / "experiment.yaml").write_text("experiment_name: test\n", encoding="utf-8")
        self.assertEqual(self.app.get("/api/meta", {})["batches"], [])
        with self.assertRaisesRegex(ValueError, "generated experiment.yaml"):
            self.app.post("/api/resume", {"batch": "configs/batch"})

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

    def test_launcher_treats_a_connect_timeout_as_no_running_gui(self):
        with patch("eagle.cli.gui_launcher.HTTPConnection") as connection:
            connection.return_value.connect.side_effect = TimeoutError
            self.assertIsNone(_request(8877, INSTANCE_PATH))
        connection.return_value.request.assert_not_called()

    def test_launcher_handles_a_probe_racing_service_shutdown(self):
        with patch("eagle.cli.gui_launcher.HTTPConnection") as connection:
            connection.return_value.request.side_effect = ConnectionResetError
            self.assertIsNone(_request(8877, INSTANCE_PATH))
            with self.assertRaises(ConnectionResetError):
                _request(8877, SHUTDOWN_PATH, token="token")


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

    def test_launcher_reattaches_and_ctrl_c_requests_authenticated_shutdown(self):
        port = self.server.server_port
        self.assertEqual(self.request("POST", SHUTDOWN_PATH, {}, {"X-Eagle-Token": ""})[0], 403)
        self.assertTrue(self.thread.is_alive())
        code, instance = self.request("GET", INSTANCE_PATH)
        self.assertEqual(code, 200)
        self.assertEqual(instance["root"], str(self.app.root))
        with (
            patch("eagle.cli.gui_launcher._start_service") as start,
            patch("eagle.cli.gui_launcher.time.sleep", side_effect=KeyboardInterrupt),
        ):
            self.assertEqual(supervise_gui(self.app.root, port, [], None), 0)
        start.assert_not_called()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def test_shutdown_refuses_new_experiment_jobs(self):
        self.server.stopping = True
        with patch.object(self.app.experiment, "start") as start:
            code, response = self.request("POST", "/api/start", {"text": "{}"})
        self.assertEqual(code, 400)
        self.assertIn("stopping", response["error"])
        start.assert_not_called()

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
