#!/usr/bin/env python3
"""Read Codex rate-limit meters and choose a bounded workload mode.

The meters are percentages from Codex's rate-limit service, not token counts.
This module has no dependency outside Python's standard library so the sibling
``codex-budget`` executable works on Linux and WSL installations.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


WEEKLY_DAILY_RESERVE_PERCENT = 12.0
# Local JSONL records are normally written after each turn. Older records can
# no longer safely represent the active account meter, so they do not drive a
# workload recommendation after this age.
LOCAL_SNAPSHOT_STALE_SECONDS = 30 * 60
LIVE_RPC_TIMEOUT_SECONDS = 5.0
REVERSE_READ_BLOCK_BYTES = 64 * 1024
MAX_RECENT_FALLBACK_FILES = 48
CONTROL_FILENAME = "codex-budget-control.json"

# Workload thresholds operate on Codex's percentage rate-limit meters. Weekly
# mode preserves 12 percentage points for every day until reset; the shorter
# window can only make that recommendation more conservative.
WEEKLY_CRITICAL_USABLE_PERCENT = 3.0
WEEKLY_CRITICAL_HEADROOM_DAYS = 0.35
WEEKLY_CONSERVATIVE_HEADROOM_DAYS = 0.75
WEEKLY_AGGRESSIVE_HEADROOM_DAYS = 1.35
FIVE_HOUR_STOP_REMAINING_PERCENT = 2.0
FIVE_HOUR_CRITICAL_REMAINING_PERCENT = 10.0
FIVE_HOUR_CONSERVATIVE_REMAINING_PERCENT = 25.0

MODE_ORDER = {"AGGRESSIVE": 0, "NORMAL": 1, "CONSERVATIVE": 2, "CRITICAL": 3, "STOP": 4}
DISABLED_MODE = "UNLIMITED"


@dataclass(frozen=True)
class Meter:
    used_percent: float | None
    duration_minutes: float | None
    resets_at: datetime | None
    raw: dict[str, Any]
    metadata: dict[str, Any]

    @property
    def remaining_percent(self) -> float | None:
        if self.used_percent is None:
            return None
        return clamp(100.0 - self.used_percent, 0.0, 100.0)


@dataclass(frozen=True)
class Snapshot:
    five_hour: Meter | None
    weekly: Meter | None
    timestamp: datetime | None
    metadata: dict[str, Any]
    meters: tuple[Meter, ...]


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def get_any(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if abs(seconds) > 100_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def iso_timestamp(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def normalize_meter(value: Any, metadata: dict[str, Any] | None = None) -> Meter | None:
    if not isinstance(value, dict):
        return None
    used = number(get_any(value, "usedPercent", "used_percent"))
    duration = number(get_any(value, "windowDurationMins", "window_duration_mins", "window_duration_minutes", "window_minutes"))
    reset = parse_timestamp(get_any(value, "resetsAt", "resets_at", "resetAt", "reset_at"))
    if used is None and duration is None and reset is None:
        return None
    return Meter(clamp(used, 0.0, 100.0) if used is not None else None, duration, reset, value, metadata or {})


def meter_kind(meter: Meter) -> str | None:
    if meter.duration_minutes is None:
        return None
    # Codex exposes exact durations today. Small ranges make the reader robust
    # to harmless server rounding while avoiding guessing unrelated windows.
    if 240 <= meter.duration_minutes <= 360:
        return "five_hour"
    if 9_000 <= meter.duration_minutes <= 11_000:
        return "weekly"
    return None


def metadata_from(container: dict[str, Any]) -> dict[str, Any]:
    return {
        "limit_id": get_any(container, "limitId", "limit_id"),
        "limit_name": get_any(container, "limitName", "limit_name"),
        "plan_type": get_any(container, "planType", "plan_type"),
        "rate_limit_reached_type": get_any(container, "rateLimitReachedType", "rate_limit_reached_type"),
        "spend_control_reached": get_any(container, "spendControlReached", "spend_control_reached"),
    }


def normalize_snapshot(container: Any, timestamp: datetime | None = None) -> Snapshot | None:
    if not isinstance(container, dict):
        return None
    metadata = metadata_from(container)
    candidates = [normalize_meter(container, metadata)]
    candidates.extend(normalize_meter(container.get(name), metadata) for name in ("primary", "secondary"))
    five_hour = weekly = None
    for meter in candidates:
        if meter is None:
            continue
        if meter_kind(meter) == "five_hour" and five_hour is None:
            five_hour = meter
        elif meter_kind(meter) == "weekly" and weekly is None:
            weekly = meter
    if five_hour is None and weekly is None:
        return None
    return Snapshot(five_hour, weekly, timestamp, metadata, tuple(meter for meter in candidates if meter is not None))


def snapshots_from_live_result(result: Any) -> Iterable[Snapshot]:
    if not isinstance(result, dict):
        return []
    snapshots: list[Snapshot] = []
    default = normalize_snapshot(get_any(result, "rateLimits", "rate_limits"))
    if default:
        snapshots.append(default)
    by_limit = get_any(result, "rateLimitsByLimitId", "rate_limits_by_limit_id")
    if isinstance(by_limit, dict):
        for key in sorted(by_limit):
            snapshot = normalize_snapshot(by_limit[key])
            if snapshot:
                snapshots.append(snapshot)
    return snapshots


def combine_snapshots(snapshots: Iterable[Snapshot], timestamp: datetime | None = None) -> Snapshot | None:
    """Combine live buckets so a model-specific constrained meter is not hidden."""
    options = list(snapshots)
    if not options:
        return None
    meters: list[Meter] = []
    seen: set[tuple[Any, ...]] = set()
    for snapshot in options:
        for meter in snapshot.meters:
            key = (meter_kind(meter), meter.duration_minutes, meter.used_percent, meter.resets_at, meter.metadata.get("limit_id"))
            if key not in seen:
                seen.add(key)
                meters.append(meter)
    first = options[0]
    return Snapshot(first.five_hour, first.weekly, timestamp, first.metadata, tuple(meters))


def _read_line_worker(stream: Any, result_queue: queue.Queue[str | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            result_queue.put(line)
    finally:
        result_queue.put(None)


def find_codex() -> str | None:
    command = shutil.which("codex") or shutil.which("codex.exe")
    if command or os.name == "nt" or not Path("/proc/version").exists():
        return command
    # Python's POSIX path lookup does not always inherit WSL's .exe command
    # resolution. Let the WSL shell resolve the Windows-installed CLI.
    try:
        result = subprocess.run(
            ["sh", "-lc", "command -v codex 2>/dev/null || command -v codex.exe 2>/dev/null"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def live_snapshot() -> tuple[Snapshot | None, str | None]:
    codex = find_codex()
    if not codex:
        return None, "codex executable was not found"
    try:
        process = subprocess.Popen(
            [codex, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError as exc:
        return None, f"could not start codex app-server: {exc}"

    lines: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_read_line_worker, args=(process.stdout, lines), daemon=True)
    reader.start()

    def send(request: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()

    def await_response(request_id: int) -> dict[str, Any] | None:
        deadline = time.monotonic() + LIVE_RPC_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                return message
        return None

    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-budget", "version": "1"}, "capabilities": {"experimentalApi": True}}})
        initialized = await_response(1)
        if not initialized or "error" in initialized:
            return None, "codex app-server did not initialize"
        send({"id": 2, "method": "account/rateLimits/read", "params": None})
        response = await_response(2)
        if not response or "error" in response:
            return None, "codex app-server did not return rate limits"
        snapshot = combine_snapshots(snapshots_from_live_result(response.get("result")), datetime.now(timezone.utc))
        return snapshot, None if snapshot else "codex app-server returned no recognized rate-limit meter"
    except (BrokenPipeError, OSError) as exc:
        return None, f"codex app-server communication failed: {exc}"
    finally:
        if process.stdin:
            process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()


def state_directories(explicit: str | None = None) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    directories: list[Path] = []
    configured = os.environ.get("CODEX_HOME")
    if configured:
        directories.append(Path(configured).expanduser())
    directories.append(Path.home() / ".codex")
    if os.name != "nt" and Path("/proc/version").exists():
        profile = os.environ.get("USERPROFILE", "")
        if not profile:
            # WSL sessions commonly omit USERPROFILE even when they inherit a
            # Windows Codex installation. Ask Windows for its own home rather
            # than hardcoding a Windows user name.
            try:
                profile = subprocess.run(
                    ["sh", "-lc", "cmd.exe /d /s /c 'echo %USERPROFILE%'"],
                    check=False,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=2,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                profile = ""
        if len(profile) > 3 and profile[1:3] == ":\\":
            directories.append(Path("/mnt") / profile[0].lower() / Path(profile[3:].replace("\\", "/")) / ".codex")
        username = os.environ.get("USERNAME")
        if username:
            directories.append(Path("/mnt/c/Users") / username / ".codex")
        if not profile and not username:
            # Some locked-down WSL installations disable Windows process
            # interop, leaving no profile variables at all. Discover only
            # existing Codex state directories under the standard mount.
            try:
                directories.extend(Path("/mnt/c/Users").glob("*/.codex"))
            except OSError:
                pass
    unique: list[Path] = []
    for directory in directories:
        if directory not in unique:
            unique.append(directory)
    return unique


def control_file(state_dir: str | None = None) -> Path:
    """Return the shared persistent controller-state file."""
    if state_dir is None:
        installed_home = Path(__file__).resolve().parent.parent
        if installed_home.name == ".codex":
            return installed_home / CONTROL_FILENAME
    directories = state_directories(state_dir)
    root = directories[0] if directories else Path.home() / ".codex"
    for directory in directories:
        candidate = directory / CONTROL_FILENAME
        if candidate.is_file():
            return candidate
    return root / CONTROL_FILENAME


def read_control_enabled(state_dir: str | None = None) -> tuple[bool, Path, str | None]:
    path = control_file(state_dir)
    if not path.exists():
        return True, path, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        enabled = data.get("enabled") if isinstance(data, dict) else None
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        return enabled, path, None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return True, path, f"invalid controller state; defaulting to enabled: {exc}"


def write_control_enabled(enabled: bool, state_dir: str | None = None) -> Path:
    path = control_file(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps({"enabled": enabled, "version": 1}, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def reverse_jsonl_lines(path: Path) -> Iterable[str]:
    """Yield UTF-8 JSONL lines from the file tail without loading its history."""
    with path.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        remainder = b""
        while position:
            read_size = min(REVERSE_READ_BLOCK_BYTES, position)
            position -= read_size
            handle.seek(position)
            chunks = (handle.read(read_size) + remainder).split(b"\n")
            remainder = chunks[0]
            for chunk in reversed(chunks[1:]):
                if chunk:
                    yield chunk.decode("utf-8", errors="replace").rstrip("\r")
        if remainder:
            yield remainder.decode("utf-8", errors="replace").rstrip("\r")


def latest_snapshot_in_file(path: Path) -> tuple[datetime, Snapshot] | None:
    for line in reverse_jsonl_lines(path):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        timestamp = parse_timestamp(event.get("timestamp"))
        snapshot = normalize_snapshot(get_any(payload, "rate_limits", "rateLimits"), timestamp)
        if snapshot and timestamp:
            return timestamp, snapshot
    return None


def fallback_snapshot(state_dir: str | None = None) -> tuple[Snapshot | None, str | None]:
    files: list[tuple[float, Path]] = []
    for root in state_directories(state_dir):
        for relative in ("sessions", "archived_sessions"):
            directory = root / relative
            if not directory.is_dir():
                continue
            try:
                for path in directory.rglob("*.jsonl"):
                    try:
                        files.append((path.stat().st_mtime, path))
                    except OSError:
                        continue
            except OSError:
                continue
    newest: tuple[datetime, Snapshot, Path] | None = None
    for index, (modified_at, path) in enumerate(sorted(files, reverse=True, key=lambda item: item[0])):
        # Do not let a damaged or unrelated state tree turn a planning helper
        # into an unbounded archival scan. Current session records are newest.
        if index >= MAX_RECENT_FALLBACK_FILES:
            break
        # A JSONL event cannot normally postdate its file modification time.
        # Once this bound is older than our best event, older files cannot win.
        if newest is not None and modified_at <= newest[0].timestamp():
            break
        try:
            candidate = latest_snapshot_in_file(path)
        except (OSError, UnicodeError):
            continue
        if candidate and (newest is None or candidate[0] > newest[0]):
            newest = (candidate[0], candidate[1], path)
    if newest is None:
        return None, "no valid Codex rate-limit snapshot was found in local session state"
    return newest[1], str(newest[2])


def meter_output(meter: Meter | None, now: datetime) -> dict[str, Any]:
    if not meter:
        return {"used_percent": None, "remaining_percent": None, "resets_at": None, "limit_id": None, "limit_name": None}
    reset = meter.resets_at if meter.resets_at and meter.resets_at > now else None
    return {"used_percent": rounded(meter.used_percent), "remaining_percent": rounded(meter.remaining_percent), "resets_at": iso_timestamp(reset), "limit_id": meter.metadata.get("limit_id"), "limit_name": meter.metadata.get("limit_name")}


def rounded(value: float | None) -> int | float | None:
    if value is None:
        return None
    rounded_value = round(value, 2)
    return int(rounded_value) if rounded_value.is_integer() else rounded_value


def valid_meter(meter: Meter | None, now: datetime) -> bool:
    return bool(meter and meter.remaining_percent is not None and meter.duration_minutes and meter.resets_at and meter.resets_at > now)


def most_constrained_meter(meters: Iterable[Meter], kind: str, now: datetime) -> Meter | None:
    matching = [meter for meter in meters if meter_kind(meter) == kind]
    valid = [meter for meter in matching if valid_meter(meter, now)]
    if valid:
        return min(valid, key=lambda meter: meter.remaining_percent if meter.remaining_percent is not None else 101)
    return matching[0] if matching else None


def weekly_mode(meter: Meter | None, now: datetime, stale: bool) -> tuple[str, float | None, float | None, float | None, str]:
    if stale:
        return "UNKNOWN", None, None, None, "the newest local snapshot is stale"
    if not valid_meter(meter, now):
        return "UNKNOWN", None, None, None, "weekly rate-limit data is unavailable or has an invalid reset time"
    assert meter is not None and meter.resets_at is not None and meter.duration_minutes is not None
    remaining = meter.remaining_percent
    assert remaining is not None
    days = max(0.0, (meter.resets_at - now).total_seconds() / 86400)
    reserve = clamp(days * WEEKLY_DAILY_RESERVE_PERCENT, 0.0, 100.0)
    usable = max(0.0, remaining - reserve)
    if remaining <= reserve:
        return "STOP", usable, days, reserve, f"weekly remaining is at or below the {reserve:.2f}% reserve ({days:.2f} days x 12%)"
    headroom_days = usable / WEEKLY_DAILY_RESERVE_PERCENT
    if usable <= WEEKLY_CRITICAL_USABLE_PERCENT or headroom_days < WEEKLY_CRITICAL_HEADROOM_DAYS:
        mode = "CRITICAL"
    elif headroom_days < WEEKLY_CONSERVATIVE_HEADROOM_DAYS:
        mode = "CONSERVATIVE"
    elif headroom_days <= WEEKLY_AGGRESSIVE_HEADROOM_DAYS:
        mode = "NORMAL"
    else:
        mode = "AGGRESSIVE"
    return mode, usable, days, reserve, f"weekly headroom is {headroom_days:.2f} days above the {reserve:.2f}% reserve"


def effective_mode(weekly: str, five_hour: Meter | None, now: datetime, stale: bool) -> tuple[str, str | None]:
    if stale or not valid_meter(five_hour, now):
        return weekly, None
    assert five_hour is not None and five_hour.remaining_percent is not None
    remaining = five_hour.remaining_percent
    if remaining <= FIVE_HOUR_STOP_REMAINING_PERCENT:
        window_mode = "STOP"
    elif remaining <= FIVE_HOUR_CRITICAL_REMAINING_PERCENT:
        window_mode = "CRITICAL"
    elif remaining <= FIVE_HOUR_CONSERVATIVE_REMAINING_PERCENT:
        window_mode = "CONSERVATIVE"
    else:
        return weekly, None
    if weekly == "UNKNOWN":
        return window_mode, f"5-hour remaining is {rounded(remaining)}%"
    return (window_mode if MODE_ORDER[window_mode] > MODE_ORDER[weekly] else weekly), f"5-hour remaining is {rounded(remaining)}%"


def build_report(snapshot: Snapshot | None, source: str | None, source_error: str | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    age: float | None = None
    if snapshot and snapshot.timestamp:
        age = max(0.0, (now - snapshot.timestamp).total_seconds())
    stale = bool(age is not None and age > LOCAL_SNAPSHOT_STALE_SECONDS)
    meters = snapshot.meters if snapshot else ()
    five_hour = most_constrained_meter(meters, "five_hour", now)
    weekly = most_constrained_meter(meters, "weekly", now)
    weekly_decision, usable, days, reserve, reason = weekly_mode(weekly, now, stale)
    mode, five_hour_reason = effective_mode(weekly_decision, five_hour, now, stale)
    if snapshot is None:
        reason = source_error or "Codex rate-limit telemetry is unavailable"
    elif five_hour_reason:
        reason = f"{reason}; {five_hour_reason}"
    return {
        "five_hour": meter_output(five_hour, now),
        "weekly": meter_output(weekly, now),
        "snapshot_age_seconds": rounded(age),
        "source": source,
        "stale": stale,
        "metadata": weekly.metadata if weekly else (snapshot.metadata if snapshot else {}),
        "meters": [{"window": meter_kind(meter), **meter_output(meter, now), "metadata": meter.metadata} for meter in meters],
        "budget": {
            "reserve_percent": rounded(reserve),
            "reserve_percent_per_day": int(WEEKLY_DAILY_RESERVE_PERCENT),
            "usable_percent": rounded(usable),
            "days_until_reset": rounded(days),
            "recommended_mode": mode,
            "reason": reason,
        },
    }


def read_usage(state_dir: str | None = None, no_live: bool = False, now: datetime | None = None) -> dict[str, Any]:
    if not no_live and state_dir is None:
        snapshot, error = live_snapshot()
        if snapshot:
            return build_report(snapshot, "codex app-server account/rateLimits/read", error, now)
    else:
        error = "live Codex app-server read was disabled"
    snapshot, fallback_source = fallback_snapshot(state_dir)
    if snapshot:
        return build_report(snapshot, fallback_source, None, now)
    reasons = [message for message in (error, fallback_source) if message]
    return build_report(None, None, "; ".join(reasons) or None, now)


def read_controlled_usage(state_dir: str | None = None, no_live: bool = False, now: datetime | None = None) -> dict[str, Any]:
    enabled, path, control_error = read_control_enabled(state_dir)
    controller = {"enabled": enabled, "source": str(path), "error": control_error}
    if not enabled:
        report = build_report(None, None, None, now)
        report["controller"] = controller
        report["budget"]["recommended_mode"] = DISABLED_MODE
        report["budget"]["reason"] = "usage controller is disabled; telemetry was not read"
        return report
    report = read_usage(state_dir, no_live, now)
    report["controller"] = controller
    return report


def human_output(report: dict[str, Any]) -> str:
    def display(value: Any, suffix: str = "") -> str:
        return "unavailable" if value is None else f"{value}{suffix}"

    controller = report.get("controller", {"enabled": True})
    if not controller.get("enabled", True):
        return "\n".join(
            [
                "Codex usage",
                "",
                "Controller: OFF",
                f"Mode: {DISABLED_MODE}",
                "Telemetry was not read.",
                f"State: {controller.get('source')}",
                "Run codex-budget on to restore usage-aware workload control.",
            ]
        )
    lines = ["Codex usage", "Controller: ON", "", "5-hour:"]
    for label, key in (("used", "used_percent"), ("remaining", "remaining_percent"), ("reset", "resets_at")):
        suffix = "%" if key.endswith("percent") else ""
        lines.append(f"  {label + ':':<11}{display(report['five_hour'][key], suffix)}")
    lines.extend(["", "Weekly:"])
    for label, key in (("used", "used_percent"), ("remaining", "remaining_percent"), ("reset", "resets_at")):
        suffix = "%" if key.endswith("percent") else ""
        lines.append(f"  {label + ':':<11}{display(report['weekly'][key], suffix)}")
    age = report["snapshot_age_seconds"]
    lines.extend(["", "Snapshot age:", f"  {display(age, 's')}", f"Source: {display(report['source'])}", f"Mode: {report['budget']['recommended_mode']}", f"Reason: {report['budget']['reason']}"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read Codex rate-limit meters and recommend a workload mode.")
    parser.add_argument("action", nargs="?", choices=("on", "off", "toggle"), help="persistently enable, disable, or toggle workload control")
    parser.add_argument("--json", action="store_true", help="emit stable machine-readable JSON")
    parser.add_argument("--state-dir", help="override the discovered Codex state and controller directory")
    parser.add_argument("--no-live", action="store_true", help="skip the Codex app-server and read only local state")
    arguments = parser.parse_args(argv)
    if arguments.action:
        enabled, _, _ = read_control_enabled(arguments.state_dir)
        requested = not enabled if arguments.action == "toggle" else arguments.action == "on"
        write_control_enabled(requested, arguments.state_dir)
    report = read_controlled_usage(arguments.state_dir, arguments.no_live)
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(human_output(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
