"""Explicit legacy-run migration command boundary."""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle migrate-run")
    parser.add_argument("run_dir")
    parser.parse_args(argv)
    print("Legacy migration is explicit but no legacy schema is enabled in this release.")
    return 2
