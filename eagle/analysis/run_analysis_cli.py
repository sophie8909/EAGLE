"""Subprocess-safe CLI for EAGLE analysis plotting."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .evolution_result_analysis import analyze_evolution_run


SUPPORTED_ANALYSIS_TYPES = {"evolution", "mo"}


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI for subprocess-safe analysis plotting."""
    parser = argparse.ArgumentParser(description="Run EAGLE analysis plotting in a subprocess.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Target EAGLE run directory.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated analysis files.")
    parser.add_argument(
        "--type",
        dest="analysis_type",
        default="evolution",
        help="Analysis type to run. Supported values: evolution, mo.",
    )
    return parser


def _resolve_output_dir(run_dir: Path, output_dir: Path | None) -> Path:
    """Resolve and create the output directory."""
    resolved = output_dir.resolve() if output_dir is not None else (run_dir / "analysis" / "evolution").resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _build_success_result(
    *, run_dir: Path, output_dir: Path, analysis_type: str, output_files: dict[str, Any]
) -> dict[str, Any]:
    """Build a stable JSON result for a successful analysis run."""
    return {
        "ok": True,
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "analysis_type": analysis_type,
        "output_files": output_files,
        "error": "",
    }


def _build_failure_result(
    *, run_dir: Path | None, output_dir: Path | None, analysis_type: str, error: str
) -> dict[str, Any]:
    """Build a stable JSON result for a failed analysis run."""
    return {
        "ok": False,
        "run_dir": str(run_dir) if run_dir is not None else "",
        "output_dir": str(output_dir) if output_dir is not None else "",
        "analysis_type": analysis_type,
        "output_files": {},
        "error": error,
    }


def run_analysis(*, run_dir: Path, output_dir: Path | None, analysis_type: str) -> dict[str, Any]:
    """Run one supported analysis type and return a JSON-serializable result."""
    normalized_type = str(analysis_type or "").strip().lower()
    if normalized_type not in SUPPORTED_ANALYSIS_TYPES:
        raise ValueError(f"Unsupported analysis type: {analysis_type!r}")

    resolved_output_dir = _resolve_output_dir(run_dir, output_dir)
    analysis_result = analyze_evolution_run(run_dir=run_dir, output_dir=resolved_output_dir)
    return _build_success_result(
        run_dir=run_dir,
        output_dir=resolved_output_dir,
        analysis_type=normalized_type,
        output_files=analysis_result,
    )


def main() -> int:
    """CLI entry point for analysis plotting."""
    parser = build_argument_parser()
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir is not None else None
    analysis_type = str(args.analysis_type or "").strip().lower()

    try:
        result = run_analysis(run_dir=run_dir, output_dir=output_dir, analysis_type=analysis_type)
    except Exception as exc:
        result = _build_failure_result(
            run_dir=run_dir,
            output_dir=output_dir,
            analysis_type=analysis_type,
            error=str(exc),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
