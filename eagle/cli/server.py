"""Start a local model server independently of experiment runs."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.interrupts import install_interrupt_handlers
from eagle.runtime.config import runtime_config_from_experiment
from eagle.runtime.processes import RuntimeManager


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle server")
    parser.add_argument(
        "--config", type=Path, required=True,
        help="One experiment YAML defining the local primary model.",
    )
    args = parser.parse_args(argv)
    manager = None
    restore_interrupts = install_interrupt_handlers()
    try:
        config = ExperimentConfig.from_file(args.config.expanduser().resolve())
        config.validate()
        if not config.model.manages_runtime:
            raise ValueError(
                "This config uses an external primary endpoint. Start that service separately; "
                "local startup requires both model.path and model.llama_server."
            )
        config.model.validate(require_files=True)
        runtime = runtime_config_from_experiment(config)
        manager = RuntimeManager(runtime)
        print(f"LLM server: starting {config.model.name} at {config.model.base_url}", flush=True)
        status = manager.start()
        if status.state != "healthy":
            raise RuntimeError(f"LLM server startup failed: {status.detail}")
        print(
            f"LLM server ready · PID {status.pid}\nLog: {runtime.log_path}\n"
            "Keep this terminal open. Start experiments in another terminal; Ctrl+C stops the server.",
            flush=True,
        )
        while True:
            time.sleep(2)
            status = manager.status()
            if status.state != "healthy":
                raise RuntimeError(f"LLM server is no longer healthy: {status.detail}")
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        try:
            if manager is not None:
                manager.stop_owned()
        finally:
            restore_interrupts()
