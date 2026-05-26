"""Subprocess-safe CLI for EAGLE analysis plotting."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .evolution_result_analysis import analyze_evolution_run, analyze_final_test_run


SUPPORTED_ANALYSIS_TYPES = {"evolution", "mo", "final_test"}
FINAL_TEST_METRICS = {
    "win_rate",
    "score",
    "ally_resources",
    "enemy_resources",
    "total_ally_resources",
    "total_enemy_resources",
    "resource_difference",
    "weighted_resource_score",
}


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI for subprocess-safe analysis plotting."""
    parser = argparse.ArgumentParser(description="Run EAGLE analysis plotting in a subprocess.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Target EAGLE run directory.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated analysis files.")
    parser.add_argument(
        "--type",
        dest="analysis_type",
        default="evolution",
        help="Analysis type to run. Supported values: evolution, mo, final_test.",
    )
    parser.add_argument(
        "--metric",
        default="win_rate",
        choices=sorted(FINAL_TEST_METRICS),
        help="Final-test analysis metric.",
    )
    parser.add_argument(
        "--aggregation",
        default="mean",
        choices=["mean", "best", "worst"],
        help="Final-test aggregation strategy.",
    )
    parser.add_argument("--weight-resources", default="1.0", help="Weighted resource score resource weight.")
    parser.add_argument("--weight-base", default="1.0", help="Weighted resource score base weight.")
    parser.add_argument("--weight-barracks", default="1.0", help="Weighted resource score barracks weight.")
    parser.add_argument("--weight-worker", default="1.0", help="Weighted resource score worker weight.")
    parser.add_argument("--weight-light", default="1.0", help="Weighted resource score light weight.")
    parser.add_argument("--weight-heavy", default="1.0", help="Weighted resource score heavy weight.")
    parser.add_argument("--weight-ranged", default="1.0", help="Weighted resource score ranged weight.")
    parser.add_argument("--individual", default="all", help="Final-test individual id filter, or all.")
    parser.add_argument("--x-objective", default=None, help="MO scatter X-axis objective key.")
    parser.add_argument("--y-objective", default=None, help="MO scatter Y-axis objective key.")
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


def run_analysis(
    *,
    run_dir: Path,
    output_dir: Path | None,
    analysis_type: str,
    metric: str = "win_rate",
    aggregation: str = "mean",
    individual: str = "all",
    weights: dict[str, float] | None = None,
    x_objective: str | None = None,
    y_objective: str | None = None,
) -> dict[str, Any]:
    """Run one supported analysis type and return a JSON-serializable result."""
    normalized_type = str(analysis_type or "").strip().lower()
    if normalized_type not in SUPPORTED_ANALYSIS_TYPES:
        raise ValueError(f"Unsupported analysis type: {analysis_type!r}")

    resolved_output_dir = _resolve_output_dir(run_dir, output_dir)
    if normalized_type == "final_test":
        analysis_result = analyze_final_test_run(
            run_dir=run_dir,
            output_dir=resolved_output_dir,
            metric=str(metric or "win_rate"),
            aggregation=str(aggregation or "mean"),
            individual=str(individual or "all"),
            weights=weights,
        )
    else:
        analysis_result = analyze_evolution_run(
            run_dir=run_dir,
            output_dir=resolved_output_dir,
            x_objective=x_objective,
            y_objective=y_objective,
        )
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
    weights = {
        "resources": float(args.weight_resources),
        "base": float(args.weight_base),
        "barracks": float(args.weight_barracks),
        "worker": float(args.weight_worker),
        "light": float(args.weight_light),
        "heavy": float(args.weight_heavy),
        "ranged": float(args.weight_ranged),
    }

    try:
        result = run_analysis(
            run_dir=run_dir,
            output_dir=output_dir,
            analysis_type=analysis_type,
            metric=str(args.metric),
            aggregation=str(args.aggregation),
            individual=str(args.individual),
            weights=weights,
            x_objective=args.x_objective,
            y_objective=args.y_objective,
        )
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
