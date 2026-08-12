"""CLI for the single local llama.cpp runtime."""
from __future__ import annotations

import argparse

from eagle.runtime.config import load_runtime_config
from eagle.runtime.processes import RuntimeManager


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m eagle runtime")
    parser.add_argument("operation", choices=("start", "stop", "restart", "status", "check"))
    parser.add_argument("--config", default="configs/runtime.yaml")
    parser.add_argument(
        "--model",
        help="Direct path to the GGUF model for this server operation; defaults to the configured model.",
    )
    args = parser.parse_args(argv)
    try:
        runtime = load_runtime_config(args.config, model_override=args.model)
        manager = RuntimeManager(runtime)
        if args.operation == "stop":
            manager.stop()
            print("EAGLE runtime stopped.")
            return 0
        if args.operation == "restart":
            manager.stop()
            status = manager.start()
        elif args.operation == "start":
            status = manager.start()
        elif args.operation == "status":
            status = manager.status()
        else:
            status = manager.check()
        _print_status(runtime, status)
        return 0 if status.state == "healthy" else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1


def _print_status(runtime, status):
    print(f"Environment: {runtime.conda_env}")
    print(f"Model: {runtime.llm.model_path}")
    if status.state != "stopped":
        print(f"Model file: {runtime.llm.model_path}")
    print(f"Endpoint: {runtime.llm.base_url}")
    print(f"Server: {status.state}")
    if status.pid:
        print(f"PID: {status.pid}")
