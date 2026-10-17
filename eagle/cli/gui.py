"""Loopback-only experiment editor, launcher, and candidate viewer."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

from eagle.config import (
    CANDIDATE_JAVA_MODES, EVALUATION_MODES, INITIAL_POPULATION_MODES,
    PARENT_EVALUATION_MODES, ExperimentConfig,
)
from eagle.gui_data import config_choices, inspect_run, list_runs, read_config, save_config, validate_config
from eagle.interrupts import install_interrupt_handlers
from eagle.operators.adaptive import ReflectionOperatorMode
from eagle.opponents import EVALUATION_ROSTER, GUI_ONLY_OPPONENTS, rooted_jar_path


ROOT = Path(__file__).resolve().parents[2]
HTML = Path(__file__).with_name("gui.html")
IS_WINDOWS = sys.platform == "win32"


def form_payload(payload: dict, root: Path) -> dict:
    """Expose legacy reflection probabilities with their effective meanings."""
    if "prompt_reflection_probability" not in payload and any(
        key in payload for key in ("code_reflection_probability", "prompt_compliance_reflection_probability", "balance_reflection_probability")
    ):
        try:
            config = ExperimentConfig.from_mapping(payload, base_dir=root)
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            return payload
        payload = dict(payload)
        payload["prompt_reflection_probability"] = config.prompt_reflection_probability
        payload["code_reflection_probability"] = config.code_reflection_probability
        payload.pop("prompt_compliance_reflection_probability", None)
        payload.pop("balance_reflection_probability", None)
    return payload


def form_options() -> dict:
    """Use canonical enum values and defaults for the common optional controls."""
    choices = {
        "java_materialization_mode": ["llm", "deterministic_dsl", "framework_slots"],
        "candidate_java_mode": list(CANDIDATE_JAVA_MODES),
        "initial_population_mode": list(INITIAL_POPULATION_MODES),
        "parent_evaluation_mode": list(PARENT_EVALUATION_MODES),
        "reflection_operator_mode": [item.value for item in ReflectionOperatorMode],
        "evaluation.mode": list(EVALUATION_MODES),
        "framework.evolution_mode": ["local", "llm_coach"],
        "execution_mode": ["openai", "mock"],
        "match_artifact_mode": ["compact", "full"],
        "algorithm": ["lexicase", "game_performance_semantic_tiebreak"],
        "survivor_selection": ["mu_plus_lambda"],
        "application": ["microrts"],
        "schema_version": ["experiment-v1", "experiment-v2"],
    }
    common = [
        "experiment_name", "generations", "population_size", "runs", "random_seed",
        "crossover_rate", "mutation_rate", "stagnation_generations",
        "java_materialization_mode", "candidate_java_mode", "initial_population_mode",
        "parent_evaluation_mode", "reflection_operator_mode", "execution_mode",
        "strategy_reflection_probability", "prompt_reflection_probability",
        "code_reflection_probability", "aos_minimum_probability", "tick_limit",
        "match_timeout_seconds", "match_artifact_mode", "runs_dir", "microrts_dir",
    ]
    defaults = {key: ExperimentConfig.__dataclass_fields__[key].default for key in common}
    defaults.update({
        "evaluation.mode": "fixed_roster", "evaluation.rounds_per_map": 3,
        "evaluation.swap_player_sides": True, "llm.temperature": 0.2,
        "llm.match_commentator.enabled": True,
    })
    return {"choices": choices, "defaults": {key: str(value) if isinstance(value, Path) else value for key, value in defaults.items()}}


class Job:
    """One owned CLI child; output lives on disk rather than in a pipe buffer."""

    def __init__(self, root: Path, kind: str):
        self.root, self.kind = root, kind
        self.process: subprocess.Popen | None = None
        self.log: Path | None = None
        self.stopping = False
        self.lock = threading.Lock()

    def start(self, command: list[str], folder: Path) -> dict:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise ValueError(f"{self.kind} is already running; wait or stop it first.")
            folder.mkdir(parents=True, exist_ok=True)
            log = folder / f"{self.kind}.log"
            process_options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if IS_WINDOWS else {"start_new_session": True}
            )
            environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            with log.open("wb") as stream:
                process = subprocess.Popen(
                    command, cwd=self.root, stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, env=environment, **process_options,
                )
            self.process, self.log, self.stopping = process, log, False
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            if self.process is not None and self.process.poll() is None and not self.stopping:
                try:
                    if IS_WINDOWS:
                        # Each child owns a console group; Ctrl+Break reaches its cleanup handlers.
                        self.process.send_signal(signal.CTRL_BREAK_EVENT)
                    elif self.kind == "experiment":
                        # The CLI handles SIGTERM and releases its owned llama.cpp runtime.
                        self.process.send_signal(signal.SIGTERM)
                    else:
                        os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                self.stopping = True
            return self.status()

    def status(self) -> dict:
        code = None if self.process is None else self.process.poll()
        running = self.process is not None and code is None
        output = ""
        if self.log is not None and self.log.exists():
            with self.log.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 32000))
                output = stream.read().decode("utf-8", errors="replace")
        return {
            "running": running, "stopping": running and self.stopping,
            "returncode": code, "pid": None if self.process is None else self.process.pid,
            "output": output, "log": None if self.log is None else str(self.log),
        }


class GuiApp:
    def __init__(self, root: Path, runs_root: Path):
        self.root = root.resolve()
        self.runs_roots = {runs_root.resolve()}
        self.token = secrets.token_urlsafe(32)
        self.experiment = Job(self.root, "experiment")
        self.match = Job(self.root, "match")

    def run_path(self, value: str) -> Path:
        path = Path(value).expanduser().resolve()
        if not any(path.parent == root for root in self.runs_roots):
            raise ValueError("Select a direct run folder from the configured runs root.")
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "eagle-run-v2":
            raise ValueError("Only canonical eagle-run-v2 runs are supported.")
        return path

    def metadata(self) -> dict:
        opponents = []
        for spec in (*EVALUATION_ROSTER, *GUI_ONLY_OPPONENTS):
            jar = rooted_jar_path(self.root, spec)
            opponents.append({"id": spec.opponent_id, "name": spec.display_name,
                              "available": jar is None or jar.is_file()})
        maps_root = self.root / "third_party/microrts"
        return {
            "configs": config_choices(self.root), "forms": form_options(),
            "opponents": opponents,
            "maps": sorted(path.relative_to(maps_root).as_posix() for path in (maps_root / "maps").rglob("*.xml")),
        }

    def get(self, path: str, query: dict) -> dict:
        if path == "/api/meta":
            return self.metadata()
        if path == "/api/config":
            result = read_config(self.root, query["path"][0])
            result["payload"] = form_payload(result["payload"], self.root)
            # Reading a config also discovers a custom runs_dir, without modifying it.
            runs = Path(result["payload"].get("runs_dir", "runs"))
            self.runs_roots.add((self.root / runs).resolve())
            return result
        if path == "/api/status":
            runs = [run for root in sorted(self.runs_roots) for run in list_runs(root)]
            return {"experiment": self.experiment.status(), "match": self.match.status(), "runs": runs}
        if path == "/api/run":
            return inspect_run(self.run_path(query["path"][0]))
        raise ValueError("Unknown API route.")

    def post(self, path: str, body: dict) -> dict:
        if path == "/api/parse":
            payload = yaml.safe_load(body["text"])
            if not isinstance(payload, dict):
                raise ValueError("Config must be a YAML mapping.")
            return {"payload": form_payload(payload, self.root)}
        if path == "/api/render":
            if not isinstance(body["payload"], dict):
                raise ValueError("Config must be a mapping.")
            return {"text": yaml.safe_dump(body["payload"], sort_keys=False, allow_unicode=True)}
        if path in {"/api/save", "/api/validate", "/api/start"}:
            text = body.get("text")
            if text is None:
                if not isinstance(body.get("payload"), dict):
                    raise ValueError("Config must be a mapping.")
                text = yaml.safe_dump(body["payload"], sort_keys=False, allow_unicode=True)
            config = validate_config(self.root, text)
            if path == "/api/validate":
                return {"message": "Config 驗證通過。模型檔案與對手依賴由實驗啟動檢查。"}
            if path == "/api/save":
                result = save_config(self.root, body["path"], text)
                result["payload"] = form_payload(result["payload"], self.root)
                return result
            folder = self.root / "logs/gui" / uuid.uuid4().hex
            folder.mkdir(parents=True)
            snapshot = folder / "config.yaml"
            snapshot.write_text(text, encoding="utf-8")
            self.runs_roots.add((self.root / config.runs_dir).resolve())
            command = [sys.executable, "-u", "-m", "eagle", "experiment", "--config-dir", str(snapshot)]
            if body.get("mock") is True:
                command.append("--mock")
            if body.get("skip_final_test") is True:
                command.append("--skip-final-test")
            return self.experiment.start(command, folder)
        if path == "/api/resume":
            run = self.run_path(body["run"])
            command = [sys.executable, "-u", "-m", "eagle", "experiment", "--resume", str(run)]
            if body.get("mock") is True:
                command.append("--mock")
            if body.get("skip_final_test") is True:
                command.append("--skip-final-test")
            return self.experiment.start(command, self.root / "logs/gui" / uuid.uuid4().hex)
        if path == "/api/watch":
            from scripts.run_gui_match import load_candidate_source, resolve_opponent

            run = self.run_path(body["run"])
            candidate = body["candidate"]
            if not isinstance(candidate, str) or Path(candidate).name != candidate or candidate in {".", ".."}:
                raise ValueError("Select a candidate ID from this run.")
            candidate_dir = (run / "candidates" / candidate).resolve()
            if candidate_dir.parent != (run / "candidates").resolve():
                raise ValueError("Candidate is outside the run.")
            load_candidate_source(run, candidate)
            known = {spec.opponent_id for spec in (*EVALUATION_ROSTER, *GUI_ONLY_OPPONENTS)}
            opponent = body["opponent"]
            if opponent not in known:
                raise ValueError("Select a registered opponent.")
            resolve_opponent(opponent)
            # Observation also supports old runs whose config cannot resume today.
            config = yaml.safe_load((run / "config.yaml").read_text(encoding="utf-8"))
            if not isinstance(config, dict) or not isinstance(config.get("microrts_dir", "third_party/microrts"), str):
                raise ValueError("Run config must specify a valid MicroRTS directory.")
            microrts = (self.root / config.get("microrts_dir", "third_party/microrts")).resolve()
            map_path = (microrts / body["map"]).resolve()
            if not map_path.is_relative_to(microrts / "maps") or map_path.suffix != ".xml" or not map_path.is_file():
                raise ValueError("Select an existing MicroRTS map.")
            cycles, interval, side = (int(body[key]) for key in ("cycles", "interval_ms", "side"))
            if cycles < 1 or interval < 0 or side not in {0, 1}:
                raise ValueError("Cycles must be positive, interval nonnegative, and side 0 or 1.")
            command = [
                sys.executable, "-u", str(self.root / "scripts/run_gui_match.py"),
                "--run-dir", str(run), "--candidate-id", candidate, "--opponent", opponent,
                "--microrts-dir", str(microrts), "--map-path", str(map_path),
                "--cycles", str(cycles), "--interval-ms", str(interval), "--candidate-player", str(side),
            ]
            return self.match.start(command, self.root / "logs/gui" / uuid.uuid4().hex)
        if path == "/api/stop-experiment":
            return self.experiment.stop()
        if path == "/api/stop-match":
            return self.match.stop()
        raise ValueError("Unknown API route.")


class GuiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: GuiApp):
        self.app = app
        super().__init__(address, GuiHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class GuiHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        pass

    def reply(self, code: int, payload, content_type="application/json; charset=utf-8"):
        data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def trusted_host(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.trusted_host():
            return self.reply(403, {"error": "Open the printed 127.0.0.1 URL."})
        url = urlsplit(self.path)
        if url.path == "/":
            return self.reply(200, HTML.read_text(encoding="utf-8").replace("__CSRF_TOKEN__", self.server.app.token), "text/html; charset=utf-8")
        try:
            self.reply(200, self.server.app.get(url.path, parse_qs(url.query)))
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
            self.reply(400, {"error": str(exc)})

    def do_POST(self):
        if not self.trusted_host() or self.headers.get("Origin") != self.server.origin or not secrets.compare_digest(
            self.headers.get("X-Eagle-Token", ""), self.server.app.token,
        ):
            return self.reply(403, {"error": "Request must originate from the local GUI."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("Request body must be between 1 byte and 2 MB.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Request must contain a JSON object.")
            self.reply(200, self.server.app.post(urlsplit(self.path).path, body))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
            self.reply(400, {"error": str(exc)})


def open_browser(url: str) -> None:
    if shutil.which("wslview"):
        subprocess.Popen(["wslview", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif os.environ.get("WSL_DISTRO_NAME") and shutil.which("cmd.exe"):
        subprocess.Popen(["cmd.exe", "/c", "start", "", url], cwd="/mnt/c", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, prog="python -m eagle gui")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--runs-root", type=Path, default=ROOT / "runs")
    parser.add_argument("--open", action="store_true", help="Open the local GUI in a browser.")
    args = parser.parse_args(argv)
    app = GuiApp(ROOT, args.runs_root)
    try:
        server = GuiServer(("127.0.0.1", args.port), app)
    except OSError as exc:
        print(f"Cannot start GUI: {exc}", file=sys.stderr)
        return 2
    print(f"EAGLE GUI: {server.origin}\nCtrl+C stops the server and requests cleanup of its owned jobs.", flush=True)
    if args.open:
        open_browser(server.origin)
    restore_interrupts = install_interrupt_handlers()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        restore_interrupts()
        app.experiment.stop()
        app.match.stop()
        server.server_close()
        if app.experiment.process is not None:
            try:
                app.experiment.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                print("Experiment is still cleaning up; see its GUI log before restarting.", file=sys.stderr)
    return 0
