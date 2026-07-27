import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from eagle.llm_profiles import load_role_profiles
from eagle.runtime.server_manager import (
    LLMServerManager,
    ServerLifecycleError,
    ServerSpec,
)
from eagle_ui.controllers.llm_controller import LLMConfigController


FAKE_SERVER = r"""#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPTIONS = "--model --alias --reasoning --parallel --threads --threads-batch --ctx-size --gpu-layers --device --host --port"
if "--help" in sys.argv:
    print(OPTIONS)
    raise SystemExit(0)
if "--list-devices" in sys.argv:
    print("Available devices:")
    if os.environ.get("FAKE_GPU") == "1":
        print("CUDA0: fake GPU")
    raise SystemExit(0)

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--model")
parser.add_argument("--alias")
parser.add_argument("--host")
parser.add_argument("--port", type=int)
args, _ = parser.parse_known_args()
mode = os.environ.get("FAKE_MODE", "ready")
print("stdout: fake server starting", flush=True)
print("\x1b[31mstderr: fake server starting\x1b[0m", file=sys.stderr, flush=True)
if mode == "exit":
    print("fatal: synthetic startup failure", file=sys.stderr, flush=True)
    raise SystemExit(int(os.environ.get("FAKE_EXIT_CODE", "7")))
if mode == "never":
    while True:
        time.sleep(1)

started = time.monotonic()
delay = float(os.environ.get("FAKE_READY_DELAY", "0"))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            if time.monotonic() - started < delay:
                self.send_response(503)
                body = b'{"status":"loading"}'
            else:
                self.send_response(200)
                body = b'{"status":"ok"}'
        elif self.path == "/v1/models":
            self.send_response(200)
            body = json.dumps({"data": [{"id": args.alias}]}).encode()
        else:
            self.send_response(404)
            body = b'{}'
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass

ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
"""


class _RemoteHandler(BaseHTTPRequestHandler):
    model_id = "remote-model"

    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
        elif self.path == "/v1/models":
            body = json.dumps({"data": [{"id": self.model_id}]}).encode()
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class _Response:
    def __init__(self, body=b"{}", status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class ServerManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.model = self.root / "models" / "model.gguf"
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(b"GGUF")
        self.executable = self.root / "bin" / "llama-server"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_text(FAKE_SERVER, encoding="utf-8")
        self.executable.chmod(0o755)
        self.manager = LLMServerManager(self.root)

    def tearDown(self):
        self.manager.stop_all()
        self.temporary.cleanup()

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def spec(self, **changes):
        values = {
            "server_id": "local",
            "model_path": self.model,
            "server_path": self.executable,
            "model_id": "fake-model",
            "host": "127.0.0.1",
            "port": self.free_port(),
            "context_size": 128,
            "roles": ("reflector", "rewriter", "generator"),
            "environment_overrides": (),
        }
        values.update(changes)
        return ServerSpec(**values)

    def test_missing_executable_is_a_retained_failed_state(self):
        spec = self.spec(server_path=self.root / "missing-server")
        with self.assertRaisesRegex(ServerLifecycleError, "not found|does not exist"):
            self.manager.start(spec)
        status = self.manager.status("local")
        self.assertEqual(status.state, "FAILED")
        self.assertIsNone(status.pid)
        self.assertIn("executable", status.error)
        self.assertTrue(Path(status.log_path).is_file())

    def test_missing_model_is_a_retained_failed_state(self):
        spec = self.spec(model_path=self.root / "missing.gguf")
        with self.assertRaisesRegex(ServerLifecycleError, "model path"):
            self.manager.start(spec)
        self.assertEqual(self.manager.status("local").state, "FAILED")

    def test_model_registry_symlink_keeps_gguf_identity(self):
        blob = self.root / "cache" / "content-addressed-blob"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"GGUF")
        linked_model = self.root / "models" / "linked-model.gguf"
        linked_model.symlink_to(blob)
        resolved = self.manager.resolve_spec(self.spec(model_path=linked_model))
        self.assertEqual(resolved.model_path, linked_model)
        self.assertTrue(Path(resolved.model_path).is_file())

    def test_child_exit_includes_exit_code_and_recent_stderr(self):
        spec = self.spec(
            environment_overrides=(
                ("FAKE_MODE", "exit"),
                ("FAKE_EXIT_CODE", "7"),
            )
        )
        with self.assertRaisesRegex(ServerLifecycleError, "code 7"):
            self.manager.start(spec, readiness_timeout=2)
        status = self.manager.status("local")
        self.assertEqual(status.state, "FAILED")
        self.assertEqual(status.exit_code, 7)
        self.assertIn("synthetic startup failure", status.error)
        persisted = Path(status.log_path).read_text(encoding="utf-8")
        self.assertIn("synthetic startup failure", persisted)

    def test_alive_child_that_never_listens_reaches_bounded_failure(self):
        spec = self.spec(environment_overrides=(("FAKE_MODE", "never"),))
        started = time.monotonic()
        with self.assertRaisesRegex(ServerLifecycleError, "readiness deadline"):
            self.manager.start(spec, readiness_timeout=0.3)
        self.assertLess(time.monotonic() - started, 3)
        status = self.manager.status("local")
        self.assertEqual(status.state, "FAILED")
        self.assertIsNone(status.pid)
        self.assertIsNotNone(status.exit_code)

    def test_readiness_succeeds_after_retries_and_is_not_ready_on_creation(self):
        spec = self.spec(
            environment_overrides=(("FAKE_READY_DELAY", "0.35"),)
        )
        result = {}

        def start():
            result["status"] = self.manager.start(spec, readiness_timeout=3)

        thread = threading.Thread(target=start)
        thread.start()
        deadline = time.monotonic() + 2
        observed = None
        while time.monotonic() < deadline:
            statuses = self.manager.statuses()
            if statuses:
                observed = statuses[0]
                if observed.pid is not None:
                    break
            time.sleep(0.01)
        self.assertIsNotNone(observed)
        self.assertEqual(observed.state, "STARTING")
        self.assertIsNotNone(observed.pid)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["status"].state, "READY")
        self.assertIn("model 'fake-model' is served", result["status"].last_health_check)

    def test_occupied_port_is_not_silently_replaced(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(ServerLifecycleError, "already occupied"):
                self.manager.start(self.spec(port=port))
        status = self.manager.status("local")
        self.assertEqual(status.port, port)
        self.assertEqual(status.state, "FAILED")

    def test_bind_host_and_client_host_have_one_canonical_local_url(self):
        spec = self.spec(host="0.0.0.0", client_host="127.0.0.1")
        self.assertEqual(spec.endpoint, f"http://127.0.0.1:{spec.port}/v1")
        status = self.manager.start(spec, readiness_timeout=3)
        self.assertEqual(status.bind_host, "0.0.0.0")
        self.assertEqual(status.client_host, "127.0.0.1")
        self.assertEqual(status.base_url, spec.endpoint)

    def test_remote_endpoint_does_not_spawn_local_process(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RemoteHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        spec = ServerSpec(
            server_id="remote",
            model_path=None,
            server_path=None,
            model_id="remote-model",
            host="lan-server.example",
            client_host="127.0.0.1",
            port=server.server_address[1],
            roles=("generator",),
            location_type="remote",
        )
        try:
            with patch(
                "eagle.runtime.server_manager.subprocess.Popen",
                side_effect=AssertionError("remote configuration spawned a process"),
            ):
                status = self.manager.start(spec, readiness_timeout=2)
            self.assertEqual(status.state, "READY")
            self.assertIsNone(status.pid)
            self.assertEqual(status.location_type, "remote")
        finally:
            server.shutdown()
            server.server_close()

    def test_remote_failures_distinguish_network_http_and_api_shape(self):
        spec = ServerSpec(
            "remote",
            None,
            None,
            "remote-model",
            "lan-server.example",
            8123,
            location_type="remote",
            client_host="lan-server.example",
        )
        with patch(
            "eagle.runtime.server_manager.urllib.request.urlopen",
            side_effect=urllib.error.URLError(
                socket.gaierror(-2, "Name or service not known")
            ),
        ):
            self.assertIn("unreachable host", self.manager._probe_endpoint(spec, 1)[1])
        with patch(
            "eagle.runtime.server_manager.urllib.request.urlopen",
            side_effect=urllib.error.URLError(ConnectionRefusedError()),
        ):
            self.assertIn("connection refused", self.manager._probe_endpoint(spec, 1)[1])
        with patch(
            "eagle.runtime.server_manager.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                spec.health_url, 500, "failure", {}, None
            ),
        ):
            self.assertIn("HTTP failure", self.manager._probe_endpoint(spec, 1)[1])
        with patch(
            "eagle.runtime.server_manager.urllib.request.urlopen",
            side_effect=[
                _Response(),
                _Response(b"not-json"),
            ],
        ):
            self.assertIn(
                "incompatible API response",
                self.manager._probe_endpoint(spec, 1)[1],
            )

    def test_stdout_and_stderr_are_consumed_stripped_and_retained(self):
        status = self.manager.start(self.spec(), readiness_timeout=3)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = self.manager.status("local")
            text = "\n".join(status.output)
            if "stdout: fake" in text and "stderr: fake" in text:
                break
            time.sleep(0.01)
        text = "\n".join(status.output)
        self.assertIn("stdout: fake server starting", text)
        self.assertIn("stderr: fake server starting", text)
        self.assertNotIn("\x1b[", text)
        persisted = Path(status.log_path).read_text(encoding="utf-8")
        self.assertIn("STDOUT", persisted)
        self.assertIn("STDERR", persisted)

    def test_stop_reaps_only_the_managed_process(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            ready = self.manager.start(self.spec(), readiness_timeout=3)
            managed_pid = ready.pid
            stopped = self.manager.stop("local")
            self.assertEqual(stopped.state, "STOPPED")
            self.assertIsNone(stopped.pid)
            self.assertIsNotNone(stopped.exit_code)
            self.assertIsNone(unrelated.poll())
            with self.assertRaises(ProcessLookupError):
                os.kill(managed_pid, 0)
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=3)

    def test_topology_and_eagle_profiles_use_resolved_port_and_base_url(self):
        topology = self.root / "experiment_env/config/llm_topology.json"
        topology.parent.mkdir(parents=True)
        topology.write_text(
            json.dumps({"version": 1, "servers": {}, "roles": {}}),
            encoding="utf-8",
        )
        controller = LLMConfigController(self.root)
        controller.server_manager = self.manager
        spec = self.spec()
        status = controller.start_server(
            server_id=spec.server_id,
            model_path=Path(spec.model_path),
            server_path=spec.server_path,
            model_id=spec.model_id,
            host=spec.host,
            client_host=spec.client_host,
            port=spec.port,
            context_size=spec.context_size,
            roles=spec.roles,
        )
        profiles = load_role_profiles(topology)
        payload = json.loads(topology.read_text(encoding="utf-8"))
        saved = payload["servers"]["local"]
        self.assertEqual(saved["port"], status.port)
        self.assertEqual(saved["base_url"], status.base_url)
        self.assertEqual(profiles["generator"].base_url, status.base_url)

    def test_gpu_requirement_fails_before_launch_for_cpu_only_binary(self):
        spec = self.spec(gpu_layers="auto", gpu_required=True)
        with self.assertRaisesRegex(ServerLifecycleError, "no usable GPU backend"):
            self.manager.start(spec)
        status = self.manager.status("local")
        self.assertEqual(status.state, "FAILED")
        self.assertIsNone(status.pid)

    def test_cpu_backend_emits_no_gpu_arguments(self):
        command = self.manager.build_command(self.spec(backend="cpu"))
        self.assertNotIn("--gpu-layers", command)
        self.assertNotIn("--fit", command)
        self.assertNotIn("--device", command)

    def test_cuda_backend_maps_logical_fit_setting_to_versioned_arguments(self):
        command = self.manager.build_command(
            self.spec(backend="cuda", gpu_required=True, fit_to_vram=True)
        )
        self.assertIn(["--gpu-layers", "auto"], [command[index:index + 2] for index in range(len(command) - 1)])
        self.assertIn(["--fit", "on"], [command[index:index + 2] for index in range(len(command) - 1)])

    def test_binary_capability_check_parses_cuda_device_list(self):
        with patch.dict(os.environ, {"FAKE_GPU": "1"}):
            capabilities = self.manager.binary_capabilities(self.executable)
        self.assertTrue(capabilities["cuda_backend_available"])
        self.assertEqual(capabilities["devices"], ("CUDA0: fake GPU",))

    def test_explicit_cpu_backend_rejects_gpu_settings(self):
        with self.assertRaisesRegex(ServerLifecycleError, "CPU backend cannot"):
            self.manager.resolve_spec(self.spec(backend="cpu", fit_to_vram=True))

    def test_diagnostic_reports_resolved_endpoint_and_gpu_state(self):
        spec = self.spec(gpu_layers=0)
        report = self.manager.diagnose_spec(spec, timeout=0.05)
        self.assertTrue(report["configuration_valid"])
        self.assertTrue(report["executable_valid"])
        self.assertTrue(report["model_valid"])
        self.assertFalse(report["gpu_backend_available"])
        self.assertEqual(report["port"], spec.port)
        self.assertIn("--model", report["command"])

    def test_diagnostic_reads_cross_process_runtime_state(self):
        spec = self.spec(gpu_layers=0)
        log_path = self.root / "server.log"
        log_path.write_text("ggml_cuda_init: found CUDA device\n", encoding="utf-8")
        state_path = self.manager.runtime_state_path
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "server_id": spec.server_id,
                    "pid": os.getpid(),
                    "log_path": str(log_path),
                }
            ),
            encoding="utf-8",
        )
        report = self.manager.diagnose_spec(spec, timeout=0.05)
        self.assertEqual(report["process_state"], "running")
        self.assertEqual(report["pid"], os.getpid())
        self.assertTrue(report["cuda_startup_evidence"])


if __name__ == "__main__":
    unittest.main()
