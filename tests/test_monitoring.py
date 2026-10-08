from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from eagle.monitoring import (
    GENERATION_SCHEMA_VERSION,
    MONITOR_SCHEMA_VERSION,
    MONITOR_SUMMARY_SCHEMA_VERSION,
    ExperimentStatusCollector,
    MonitorDataError,
    RunsRootStatusCollector,
    create_status_server,
    write_status_snapshot,
)
from eagle.run_artifacts import RUN_SCHEMA_VERSION


class MonitoringTests(unittest.TestCase):
    def run_fixture(self, root: Path, name: str = "run", *, run_id: str = "test-run") -> Path:
        run = root / name
        (run / "generations").mkdir(parents=True)
        (run / "archives").mkdir()
        (run / "manifest.json").write_text(json.dumps({
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "experiment_name": "monitor fixture",
            "status": "running",
            "experiment_pid": os.getpid(),
            "created_at": "2026-10-08T00:00:00+00:00",
            "updated_at": "2026-10-08T00:00:01+00:00",
            "latest_generation": 2,
        }), encoding="utf-8")
        (run / "config.yaml").write_text("generations: 20\n", encoding="utf-8")
        (run / "generations" / "generation_0002.json").write_text(json.dumps({
            "schema_version": GENERATION_SCHEMA_VERSION,
            "generation": 2,
            "best_candidate_id": "gen_0002_best",
            "population": [{"candidate_id": "gen_0002_best"}, {"candidate_id": "other"}],
            "metrics": {
                "expected_match_count": 360,
                "completed_match_count": 180,
                "failure_count": 1,
                "game_performance": {"best": 0.75, "mean": 0.5},
                "objectives": {"workerrush": {"best": 1.0, "mean": 0.5, "valid_count": 2, "failure_count": 0}},
                "opponent_scores": {"by_opponent": {"workerrush": {"game_performance": 0.5, "sample_count": 2, "failure_count": 0}}},
            },
            "aos": {"mode": "static", "probabilities": {"Strategy": 0.2}},
        }), encoding="utf-8")
        (run / "archives" / "error_memory.jsonl").write_text(
            json.dumps({"signature": "compile_failure:x", "count": 2}) + "\n", encoding="utf-8"
        )
        return run

    def test_collector_reads_canonical_progress_and_error_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.run_fixture(Path(directory))
            payload = ExperimentStatusCollector(run, stale_after_seconds=1).collect()
            self.assertEqual(payload["schema_version"], MONITOR_SCHEMA_VERSION)
            self.assertEqual(payload["experiment"]["latest_generation"], 2)
            self.assertEqual(payload["progress"]["best_candidate_id"], "gen_0002_best")
            self.assertEqual(payload["progress"]["completed_match_count"], 180)
            self.assertEqual(payload["progress"]["completion_ratio"], 0.5)
            self.assertEqual(payload["progress"]["best_fitness"], 0.75)
            self.assertEqual(payload["errors"][0]["signature"], "compile_failure:x")
            self.assertEqual(payload["process"]["pid"], os.getpid())
            self.assertTrue(payload["process"]["alive"])
            self.assertEqual(payload["experiment"]["status"], "running")

    def test_collector_rejects_unsupported_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            (run / "manifest.json").write_text(json.dumps({"schema_version": "old"}), encoding="utf-8")
            with self.assertRaises(MonitorDataError):
                ExperimentStatusCollector(run).collect()

    def test_runs_root_collector_discovers_new_runs_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs"
            self.run_fixture(root, "run-a", run_id="run-a")
            collector = RunsRootStatusCollector(root)
            self.assertEqual(collector.collect()["run_count"], 1)
            self.run_fixture(root, "run-b", run_id="run-b")
            payload = collector.collect()
            self.assertEqual(payload["run_count"], 2)
            self.assertEqual(
                {item["experiment"]["run_id"] for item in payload["runs"]},
                {"run-a", "run-b"},
            )
            self.assertEqual(collector.collect(run_id="run-a")["experiment"]["run_id"], "run-a")

    def test_summary_distinguishes_completed_and_unexpected_termination(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.run_fixture(Path(directory), run_id="run-a")
            manifest_path = run / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(status="complete")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            completed = ExperimentStatusCollector(run).collect_summary()
            self.assertEqual(completed["current_status"], "complete")
            self.assertFalse(completed["current_alive"])

            manifest.update(status="running", experiment_pid=999999)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            unexpected = ExperimentStatusCollector(run).collect_summary()
            self.assertEqual(unexpected["current_status"], "unexpected_termination")
            self.assertFalse(unexpected["current_alive"])

            manifest.pop("experiment_pid")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            no_process = ExperimentStatusCollector(run).collect_summary()
            self.assertEqual(no_process["current_status"], "complete")
            self.assertFalse(no_process["current_alive"])

    def test_empty_runs_root_is_complete_and_not_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = RunsRootStatusCollector(Path(directory) / "runs").collect_summary()
            self.assertEqual(summary["total_runs"], 0)
            self.assertEqual(summary["current_status"], "complete")
            self.assertFalse(summary["current_alive"])

    def test_status_snapshot_is_written_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "nested" / "monitor_status.json"
            write_status_snapshot(path, {"schema_version": MONITOR_SCHEMA_VERSION, "run_count": 2})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["run_count"], 2)
            self.assertEqual(list(path.parent.glob("*.tmp.*")), [])

    def test_non_loopback_server_can_run_without_token(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.run_fixture(Path(directory))
            try:
                server = create_status_server(ExperimentStatusCollector(run), host="0.0.0.0", port=0)
            except PermissionError as exc:
                self.skipTest(f"sandbox does not permit non-loopback sockets: {exc}")
            server.server_close()

    def test_status_endpoint_requires_token_but_health_is_public(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.run_fixture(Path(directory))
            try:
                server = create_status_server(
                    ExperimentStatusCollector(run), host="127.0.0.1", port=0, token="secret"
                )
            except PermissionError as exc:
                self.skipTest(f"sandbox does not permit loopback sockets: {exc}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(f"{base_url}/health") as response:
                    self.assertEqual(json.loads(response.read())["status"], "ok")
                with self.assertRaises(HTTPError) as context:
                    urlopen(f"{base_url}/status")
                self.assertEqual(context.exception.code, 401)
                request = Request(f"{base_url}/status", headers={"Authorization": "Bearer secret"})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["experiment"]["run_id"], "test-run")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_root_status_endpoint_picks_up_a_run_created_after_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs"
            self.run_fixture(root, "run-a", run_id="run-a")
            try:
                server = create_status_server(
                    RunsRootStatusCollector(root), host="127.0.0.1", port=0
                )
            except PermissionError as exc:
                self.skipTest(f"sandbox does not permit loopback sockets: {exc}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(f"{base_url}/status") as response:
                    self.assertEqual(json.loads(response.read())["run_count"], 1)
                with urlopen(f"{base_url}/status.json") as response:
                    summary = json.loads(response.read())
                    self.assertEqual(summary["schema_version"], MONITOR_SUMMARY_SCHEMA_VERSION)
                    self.assertEqual(summary["total_runs"], 1)
                    self.assertEqual(summary["total_generations"], 20)
                    self.assertEqual(summary["current_run_id"], "run-a")
                    self.assertEqual(summary["current_generation"], 2)
                    self.assertTrue(summary["current_alive"])
                self.run_fixture(root, "run-b", run_id="run-b")
                with urlopen(f"{base_url}/status") as response:
                    self.assertEqual(json.loads(response.read())["run_count"], 2)
                with urlopen(f"{base_url}/status/run-a") as response:
                    self.assertEqual(json.loads(response.read())["experiment"]["run_id"], "run-a")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
