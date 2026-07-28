"""One watchdog for all managed local EAGLE LLM servers."""
from __future__ import annotations

import argparse
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from .config import load_runtime_config
from .endpoints import health_check
from .processes import RuntimeManager, build_server_command, command_matches, process_alive


def monitor_once(runtime, manager, restart_history, *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    for server in runtime.local_servers():
        pid = manager.read_pid(server.name)
        alive = bool(pid and process_alive(pid) and command_matches(pid, build_server_command(runtime, server)))
        healthy, detail = health_check(server, runtime, retries=1) if alive else (False, "process not alive")
        if healthy:
            continue
        history = restart_history[server.name]
        while history and current - history[0] >= runtime.watchdog.restart_window_seconds:
            history.popleft()
        if len(history) >= runtime.watchdog.max_consecutive_restarts:
            _log(runtime, f"{server.name}: restart limit reached; last failure: {detail}")
            continue
        if alive:
            manager.stop_server(server)
        else:
            manager.remove_pid(server.name)
        time.sleep(runtime.watchdog.restart_delay_seconds)
        history.append(current)
        try:
            status = manager.start_server(server)
            _log(runtime, f"{server.name}: restarted as PID {status.pid}")
        except RuntimeError as exc:
            _log(runtime, f"{server.name}: restart failed: {exc}")


def _log(runtime, message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    with (runtime.log_root / "watchdog.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor EAGLE local LLM servers.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    runtime = load_runtime_config(args.config)
    manager = RuntimeManager(runtime)
    history = defaultdict(deque)
    while True:
        monitor_once(runtime, manager, history)
        time.sleep(runtime.watchdog.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
