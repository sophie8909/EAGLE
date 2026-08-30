"""Canonical EAGLE command dispatcher."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: python -m eagle {experiment|analyze} ...")
        return 2
    command, rest = args[0], args[1:]
    if command == "experiment":
        from eagle.cli.experiment import main as experiment_main
        return experiment_main(rest)
    if command == "analyze":
        from eagle.cli.analyze import main as analyze_main
        return analyze_main(rest)
    print(f"Unknown EAGLE command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
