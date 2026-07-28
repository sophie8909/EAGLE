"""Canonical EAGLE command dispatcher."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: python -m eagle {runtime|run|analyze|migrate-run} ...")
        return 2
    command, rest = args[0], args[1:]
    if command == "runtime":
        from eagle.cli.runtime import main as runtime_main
        return runtime_main(rest)
    if command == "run":
        from eagle.cli.run import main as run_main
        return run_main(rest)
    if command == "analyze":
        from eagle.cli.analyze import main as analyze_main
        return analyze_main(rest)
    if command == "migrate-run":
        from eagle.cli.migrate_run import main as migrate_main
        return migrate_main(rest)
    print(f"Unknown EAGLE command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
