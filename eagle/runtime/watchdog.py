"""Watch exactly one local LLM server."""
from __future__ import annotations
import argparse,time
from collections import deque
from datetime import datetime,timezone
from .config import load_runtime_config
from .endpoints import health_check
from .processes import RuntimeManager,build_server_command,command_matches,process_alive

def monitor_once(runtime,manager,restart_history,*,now=None):
    if runtime.llm.mode=="remote": return
    current=time.monotonic() if now is None else now
    pid=manager.read_pid("llm-server")
    alive=bool(pid and process_alive(pid) and command_matches(pid,build_server_command(runtime)))
    healthy,detail=health_check(runtime,retries=1) if alive else (False,"process not alive")
    if healthy:return
    while restart_history and current-restart_history[0]>=runtime.watchdog.restart_window_seconds:restart_history.popleft()
    if len(restart_history)>=runtime.watchdog.max_consecutive_restarts:
        _log(runtime,f"restart limit reached; last failure: {detail}");return
    if alive:manager.stop_server()
    else:manager.remove_pid("llm-server")
    time.sleep(runtime.watchdog.restart_delay_seconds); restart_history.append(current)
    try:_log(runtime,f"restarted as PID {manager.start_server().pid}")
    except RuntimeError as exc:_log(runtime,f"restart failed: {exc}")

def _log(runtime,message):
    stamp=datetime.now(timezone.utc).isoformat()
    with (runtime.log_root/"watchdog.log").open("a",encoding="utf-8") as handle:handle.write(f"{stamp} {message}\n")

def main(argv=None):
    parser=argparse.ArgumentParser(description="Monitor the single local EAGLE LLM server.");parser.add_argument("--config",required=True);args=parser.parse_args(argv)
    runtime=load_runtime_config(args.config)
    if runtime.llm.mode=="remote": return 0
    manager=RuntimeManager(runtime);history=deque()
    while True:monitor_once(runtime,manager,history);time.sleep(runtime.watchdog.interval_seconds)
if __name__=="__main__":raise SystemExit(main())

