"""Canonical offline analysis command."""
from __future__ import annotations

import argparse
import sys

from eagle.analysis.loader import load_run, resolve_explicit_run, resolve_latest_run
from eagle.analysis.report import generate_analysis
from eagle.runtime.config import load_runtime_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle analyze")
    parser.add_argument("--runtime-config", default="configs/runtime.yaml")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--latest", action="store_true")
    target.add_argument("--run-dir")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        runtime = load_runtime_config(args.runtime_config, validate_files=False)
        run_dir = resolve_latest_run(runtime.run_root) if args.latest else resolve_explicit_run(args.run_dir)
        print(f"Analyzing run: {run_dir}")
        output = generate_analysis(
            load_run(run_dir),
            output_name=runtime.analysis_output_directory_name,
            force=args.force,
        )
        print(f"Analysis written to: {output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
