"""Read-only local experiment status collection and HTTP serving.

The monitor deliberately reads only the canonical run manifest and generation
snapshots.  It does not inspect console output and it never starts, stops, or
mutates an experiment process.
"""
from __future__ import annotations

import hmac
import json
import os
import platform
import shutil
import socket
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from eagle.run_artifacts import GENERATION_SCHEMA_VERSION, RUN_SCHEMA_VERSION

MONITOR_SCHEMA_VERSION = "eagle-monitor-status-v1"
DEFAULT_STALE_AFTER_SECONDS = 180.0


class MonitorDataError(ValueError):
    """Raised when a run cannot be read as a supported canonical run."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MonitorDataError(f"required artifact is missing: {path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise MonitorDataError(f"cannot read artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise MonitorDataError(f"artifact must contain a JSON object: {path.name}")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _number(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _memory_info() -> dict[str, Any]:
    """Return Linux memory information without making psutil mandatory."""

    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return {"total_bytes": None, "available_bytes": None, "used_bytes": None, "percent": None}
    values: dict[str, int] = {}
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, separator, raw = line.partition(":")
            if not separator:
                continue
            fields = raw.strip().split()
            if fields and fields[0].isdigit():
                values[key] = int(fields[0]) * (1024 if len(fields) > 1 and fields[1].lower() == "kb" else 1)
    except OSError:
        return {"total_bytes": None, "available_bytes": None, "used_bytes": None, "percent": None}
    total = values.get("MemTotal")
    available = values.get("MemAvailable", values.get("MemFree"))
    used = None if total is None or available is None else max(0, total - available)
    percent = None if total in (None, 0) or used is None else round(100.0 * used / total, 3)
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "percent": percent,
    }


def _cpu_info() -> dict[str, Any]:
    try:
        load_1, load_5, load_15 = os.getloadavg()
    except (AttributeError, OSError):
        load_1 = load_5 = load_15 = None
    cpu_count = os.cpu_count() or 1
    load_percent = None if load_1 is None else round(min(100.0, 100.0 * load_1 / cpu_count), 3)
    return {
        "logical_cpus": cpu_count,
        "load_1": None if load_1 is None else round(load_1, 3),
        "load_5": None if load_5 is None else round(load_5, 3),
        "load_15": None if load_15 is None else round(load_15, 3),
        "load_percent": load_percent,
    }


def _disk_info(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return {
            "path": ".",
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "percent": None,
            "error": type(exc).__name__,
        }
    percent = None if usage.total == 0 else round(100.0 * usage.used / usage.total, 3)
    return {
        "path": ".",
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "percent": percent,
    }


def _gpu_info() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"available": False, "devices": [], "error": "nvidia-smi_not_found"}
    query = (
        "index,name,utilization.gpu,memory.used,memory.total,"
        "temperature.gpu,power.draw"
    )
    try:
        completed = subprocess.run(
            [executable, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "devices": [], "error": type(exc).__name__}
    if completed.returncode != 0:
        return {"available": False, "devices": [], "error": "nvidia_smi_failed"}
    devices: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 7:
            continue
        index, name, utilization, memory_used, memory_total, temperature, power = fields
        devices.append({
            "index": int(index) if index.isdigit() else index,
            "name": name,
            "utilization_percent": _parse_gpu_number(utilization),
            "memory_used_mib": _parse_gpu_number(memory_used),
            "memory_total_mib": _parse_gpu_number(memory_total),
            "temperature_c": _parse_gpu_number(temperature),
            "power_watts": _parse_gpu_number(power),
        })
    return {"available": True, "devices": devices, "error": None}


def _parse_gpu_number(value: str) -> float | int | None:
    if value in {"N/A", "-", ""}:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return int(number) if number.is_integer() else round(number, 3)


def _process_status(pid: int | None) -> dict[str, Any]:
    if pid is None:
        return {"pid": None, "running": None, "cmdline": None}
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {"pid": pid, "running": False, "cmdline": None}
    except PermissionError:
        return {"pid": pid, "running": None, "cmdline": None}
    cmdline = None
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        if proc_cmdline.is_file():
            cmdline = proc_cmdline.read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip() or None
    except OSError:
        pass
    return {"pid": pid, "running": True, "cmdline": cmdline}


def _load_error_memory(run_dir: Path, limit: int = 5) -> list[dict[str, Any]]:
    path = run_dir / "archives" / "error_memory.jsonl"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    except (OSError, json.JSONDecodeError):
        return []
    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        return (-count, str(item.get("signature") or ""))

    records.sort(key=sort_key)
    return records[:limit]


class ExperimentStatusCollector:
    """Build a bounded, JSON-safe status snapshot for one canonical run."""

    def __init__(self, run_dir: str | Path, *, stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS, pid: int | None = None):
        self.run_dir = Path(run_dir).expanduser().resolve()
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        self.stale_after_seconds = float(stale_after_seconds)
        self.pid = pid

    def collect(self, run_id: str | None = None) -> dict[str, Any]:
        if run_id is not None and run_id != self.run_dir.name:
            raise MonitorDataError(f"run is not available from this monitor: {run_id}")
        manifest = _read_json(self.run_dir / "manifest.json")
        if manifest.get("schema_version") != RUN_SCHEMA_VERSION:
            raise MonitorDataError(f"unsupported run manifest schema: {manifest.get('schema_version')!r}")
        latest_generation = manifest.get("latest_generation")
        generation: dict[str, Any] | None = None
        if latest_generation is not None:
            try:
                generation_number = int(latest_generation)
            except (TypeError, ValueError) as exc:
                raise MonitorDataError("manifest latest_generation is invalid") from exc
            generation = _read_json(self.run_dir / "generations" / f"generation_{generation_number:04d}.json")
            if generation.get("schema_version") != GENERATION_SCHEMA_VERSION:
                raise MonitorDataError(
                    f"unsupported generation snapshot schema: {generation.get('schema_version')!r}"
                )

        observed_at = _utc_now()
        updated_at = _parse_timestamp(manifest.get("updated_at"))
        if updated_at is None:
            try:
                updated_at = datetime.fromtimestamp(
                    (self.run_dir / "manifest.json").stat().st_mtime, tz=timezone.utc
                )
            except OSError:
                updated_at = None
        age = None if updated_at is None else max(0.0, (observed_at - updated_at).total_seconds())
        run_status = str(manifest.get("status") or "unknown")
        metrics = generation.get("metrics") if generation else {}
        metrics = metrics if isinstance(metrics, dict) else {}
        game_performance = metrics.get("game_performance") or {}
        game_performance = game_performance if isinstance(game_performance, dict) else {}
        objectives = metrics.get("objectives") or {}
        objectives = objectives if isinstance(objectives, dict) else {}
        progress = _progress_payload(generation, metrics, game_performance, objectives)
        return {
            "schema_version": MONITOR_SCHEMA_VERSION,
            "observed_at": observed_at.isoformat(),
            "host": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(aliased=True),
                "cpu": _cpu_info(),
                "memory": _memory_info(),
                "disk": _disk_info(self.run_dir),
                "gpu": _gpu_info(),
            },
            "experiment": {
                "run_id": str(manifest.get("run_id") or self.run_dir.name),
                "experiment_name": manifest.get("experiment_name"),
                "status": run_status,
                "created_at": manifest.get("created_at"),
                "updated_at": manifest.get("updated_at"),
                "latest_generation": latest_generation,
                "resumable": manifest.get("resumable"),
                "failure_reason": manifest.get("failure_reason"),
                "stop_reason": manifest.get("stop_reason"),
                "last_update_age_seconds": None if age is None else round(age, 3),
                "stale": run_status in {"initialized", "running"} and age is not None and age > self.stale_after_seconds,
            },
            "process": _process_status(self.pid),
            "progress": progress,
            "errors": _load_error_memory(self.run_dir),
        }


class RunsRootStatusCollector:
    """Discover canonical runs below a root so one daemon covers new runs."""

    def __init__(
        self,
        runs_root: str | Path,
        *,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        max_runs: int = 100,
    ):
        self.runs_root = Path(runs_root).expanduser().resolve()
        if max_runs <= 0:
            raise ValueError("max_runs must be positive")
        self.stale_after_seconds = stale_after_seconds
        self.max_runs = max_runs

    def _run_dirs(self) -> list[Path]:
        if not self.runs_root.is_dir():
            return []
        candidates = [
            path for path in self.runs_root.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        ]
        candidates.sort(key=lambda path: path.name, reverse=True)
        return candidates[: self.max_runs]

    def collect(self, run_id: str | None = None) -> dict[str, Any]:
        run_dirs = self._run_dirs()
        if run_id is not None:
            if Path(run_id).name != run_id or "/" in run_id or "\\" in run_id:
                raise MonitorDataError("run_id must be one direct child of the runs root")
            run_dirs = [path for path in run_dirs if path.name == run_id]
            if not run_dirs:
                raise MonitorDataError(f"run was not found below {self.runs_root}: {run_id}")
        snapshots: list[dict[str, Any]] = []
        for run_dir in run_dirs:
            try:
                snapshots.append(
                    ExperimentStatusCollector(
                        run_dir,
                        stale_after_seconds=self.stale_after_seconds,
                    ).collect()
                )
            except MonitorDataError as exc:
                snapshots.append({
                    "schema_version": MONITOR_SCHEMA_VERSION,
                    "experiment": {"run_id": run_dir.name, "status": "unavailable"},
                    "error": str(exc),
                })
        if run_id is not None:
            return snapshots[0]
        return {
            "schema_version": MONITOR_SCHEMA_VERSION,
            "observed_at": _utc_now().isoformat(),
            "run_count": len(snapshots),
            "runs": snapshots,
        }


def _progress_payload(
    generation: dict[str, Any] | None,
    metrics: dict[str, Any],
    game_performance: dict[str, Any],
    objectives: dict[str, Any],
) -> dict[str, Any]:
    population = generation.get("population") if generation else []
    population = population if isinstance(population, list) else []
    expected = _number(metrics.get("expected_match_count"))
    completed = _number(metrics.get("completed_match_count"))
    ratio = None if not expected or completed is None else round(min(1.0, max(0.0, float(completed) / float(expected))), 6)
    best_fitness = _number(game_performance.get("best"))
    if best_fitness is None:
        best_values = [_number(item.get("best")) for item in objectives.values() if isinstance(item, dict)]
        best_fitness = max((float(value) for value in best_values if value is not None), default=None)
    return {
        "population_size": len(population),
        "best_candidate_id": generation.get("best_candidate_id") if generation else None,
        "expected_match_count": expected,
        "completed_match_count": completed,
        "completion_ratio": ratio,
        "best_fitness": best_fitness,
        "mean_fitness": _number(game_performance.get("mean")),
        "failure_count": _number(metrics.get("failure_count")),
        "objectives": {
            str(name): {
                "best": _number(value.get("best")),
                "mean": _number(value.get("mean")),
                "valid_count": _number(value.get("valid_count")),
                "failure_count": _number(value.get("failure_count")),
            }
            for name, value in objectives.items()
            if isinstance(value, dict)
        },
        "opponent_scores": _opponent_summary(metrics),
        "operator_state": _operator_state(generation, metrics),
    }


def _opponent_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    payload = metrics.get("opponent_scores") or {}
    if not isinstance(payload, dict):
        return {}
    by_opponent = payload.get("by_opponent") or {}
    return {
        str(name): {
            "game_performance": _number(value.get("game_performance")),
            "sample_count": _number(value.get("sample_count")),
            "failure_count": _number(value.get("failure_count")),
        }
        for name, value in by_opponent.items()
        if isinstance(value, dict)
    }


def _operator_state(generation: dict[str, Any] | None, metrics: dict[str, Any]) -> dict[str, Any] | None:
    value = (generation or {}).get("aos") or metrics.get("aos")
    return dict(value) if isinstance(value, dict) else None


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def write_status_snapshot(path: str | Path, payload: dict[str, Any]) -> None:
    """Atomically publish one derived JSON snapshot for external consumers."""

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def create_status_server(
    collector: ExperimentStatusCollector | RunsRootStatusCollector,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
) -> ThreadingHTTPServer:
    """Create a read-only status server; callers own its lifecycle."""

    if not 0 <= int(port) <= 65535:
        raise ValueError("port must be between 0 and 65535")
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise ValueError("a token is required when the monitor is not loopback-bound")

    class Handler(BaseHTTPRequestHandler):
        server_version = "EAGLEMonitor/1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path == "/health":
                _json_response(self, 200, {"status": "ok", "schema_version": MONITOR_SCHEMA_VERSION})
                return
            if path in {"/status", "/status.json", "/runs"}:
                run_id = None
            elif path.startswith("/status/"):
                run_id = path.removeprefix("/status/")
            else:
                _json_response(self, 404, {"error": "not_found"})
                return
            if token and not _authorized(self, token):
                _json_response(self, 401, {"error": "unauthorized"})
                return
            try:
                payload = collector.collect(run_id=run_id)
            except MonitorDataError as exc:
                _json_response(self, 503, {"error": "run_unavailable", "detail": str(exc)})
                return
            _json_response(self, 200, payload)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            _json_response(self, 405, {"error": "read_only"})

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ThreadingHTTPServer((host, int(port)), Handler)


def _authorized(handler: BaseHTTPRequestHandler, token: str) -> bool:
    authorization = handler.headers.get("Authorization", "")
    supplied = authorization.removeprefix("Bearer ").strip()
    if supplied == authorization.strip():
        supplied = handler.headers.get("X-EAGLE-Monitor-Token", "").strip()
    return hmac.compare_digest(supplied, token)


def serve_status(
    collector: ExperimentStatusCollector | RunsRootStatusCollector,
    *,
    host: str,
    port: int,
    token: str | None,
    stop_event: threading.Event | None = None,
    snapshot_path: str | Path | None = None,
    snapshot_interval: float = 30.0,
) -> None:
    """Serve status until interrupted or an optional stop event is set."""

    if snapshot_interval <= 0:
        raise ValueError("snapshot_interval must be positive")
    server = create_status_server(collector, host=host, port=port, token=token)
    writer_stop = threading.Event()
    writer_thread: threading.Thread | None = None
    if snapshot_path is not None:
        def publish_snapshot() -> None:
            while not writer_stop.is_set():
                try:
                    payload = collector.collect()
                except MonitorDataError as exc:
                    payload = {
                        "schema_version": MONITOR_SCHEMA_VERSION,
                        "observed_at": _utc_now().isoformat(),
                        "error": "run_unavailable",
                        "detail": str(exc),
                    }
                try:
                    write_status_snapshot(snapshot_path, payload)
                except OSError:
                    # The HTTP endpoint remains available if a configured
                    # snapshot destination temporarily becomes unwritable.
                    pass
                writer_stop.wait(snapshot_interval)

        writer_thread = threading.Thread(
            target=publish_snapshot,
            name="eagle-monitor-snapshot",
            daemon=True,
        )
        writer_thread.start()

    def close() -> None:
        writer_stop.set()
        if writer_thread is not None:
            writer_thread.join(timeout=max(1.0, snapshot_interval + 1.0))
        server.server_close()

    if stop_event is None:
        try:
            server.serve_forever()
        finally:
            close()
        return
    server.timeout = 0.5
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        close()
