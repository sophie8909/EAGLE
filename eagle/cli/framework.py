"""CLI for generating an immutable Gemini Java-framework bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eagle.generation.gemini_framework import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    GeminiFrameworkError,
    generate_framework_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m eagle framework",
        description=(
            "Ask Gemini once for a structured Java framework and persist an "
            "immutable slot-control bundle."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True, help="Gemini model identifier")
    brief = parser.add_mutually_exclusive_group(required=True)
    brief.add_argument("--brief", help="framework design brief")
    brief.add_argument("--brief-file", type=Path, help="UTF-8 framework design brief")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        design_brief = (
            args.brief_file.read_text(encoding="utf-8")
            if args.brief_file is not None
            else str(args.brief)
        )
        result = generate_framework_bundle(
            args.output,
            model=args.model,
            design_brief=design_brief,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            max_attempts=args.max_attempts,
            timeout_seconds=args.timeout_seconds,
        )
        print(f"Framework bundle written to: {result.bundle_path}")
        print(f"framework_id={result.bundle['framework_id']}")
        return 0
    except (GeminiFrameworkError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
