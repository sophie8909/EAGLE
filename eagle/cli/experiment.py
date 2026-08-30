"""CLI for the canonical self-contained EAGLE experiment lifecycle."""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from eagle.experiment import ExperimentOrchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle experiment")
    parser.add_argument(
        "--config-dir",
        help="Directory of top-level YAML configs, or one direct YAML path.",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="Resume one run, or a config-folder batch using its experiment.yaml index.",
    )
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--skip-final-test", action="store_true")
    args = parser.parse_args(argv)
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def interrupt_on_sigterm(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt_on_sigterm)
    try:
        if args.config_dir is None and args.resume is None:
            parser.error("--config-dir is required unless --resume is supplied")
        config_path = Path(args.config_dir).expanduser().resolve() if args.config_dir else None
        result = ExperimentOrchestrator().run(
            config_path=config_path,
            resume_dir=None if args.resume is None else args.resume.expanduser().resolve(),
            mock=args.mock,
            skip_final_test=args.skip_final_test,
        )
        print(f"run_dir={result.run_dir}")
        print(f"completed_generation={result.completed_generation}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nEAGLE interrupted; completed generations remain resumable.", file=sys.stderr)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
