"""Runtime command implementation."""
from __future__ import annotations
import argparse
from eagle.runtime.config import load_runtime_config
from eagle.runtime.processes import RuntimeManager

def main(argv=None):
    parser=argparse.ArgumentParser(prog="python -m eagle runtime");parser.add_argument("operation",choices=("start","stop","restart","status","check"));parser.add_argument("--config",default="configs/runtime.yaml");args=parser.parse_args(argv)
    try:
        runtime=load_runtime_config(args.config);manager=RuntimeManager(runtime)
        if args.operation=="stop":manager.stop();print("EAGLE runtime stopped.");return 0
        if args.operation=="restart":manager.stop();statuses=manager.start()
        elif args.operation=="start":statuses=manager.start()
        elif args.operation=="status":statuses=manager.statuses()
        else:statuses=manager.check()
        _print_status(runtime,manager,statuses,show_watchdog=args.operation!="check")
        return 0 if all(item.state=="healthy" for item in statuses) else 1
    except (OSError,ValueError,RuntimeError) as exc: print(f"ERROR: {exc}");return 1

def _print_status(runtime,manager,statuses,*,show_watchdog):
    item=statuses[0]
    print(f"Environment: {runtime.conda_env}")
    print(f"Runtime config: {runtime.source_path}\n")
    print(f"LLM server   {runtime.llm.mode:<7} {runtime.llm.client_host}:{runtime.llm.port:<5} {item.state:<9}"+(f"PID {item.pid}" if item.pid else ""))
    if runtime.llm.model:print(f"Model        {runtime.llm.model}")
    if show_watchdog:
        if runtime.llm.mode=="remote": print("Watchdog                              disabled")
        else:
            pid=manager.read_pid("watchdog");print(f"Watchdog                              {'running' if pid else 'stopped':<9}"+(f"PID {pid}" if pid else ""))

