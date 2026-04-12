"""Run Java-vs-prompt consistency analysis from CSV inputs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from . import analysis_config as cfg
from .load_results import (
    BEHAVIOR_FIELD_ALIASES,
    aggregate_behavior_rows,
    aggregate_result_rows,
    collect_behavior_rows_from_results,
    merge_behavior_rows,
    merge_result_rows,
    normalize_behavior_rows,
    normalize_result_rows,
    read_csv_rows,
    split_surrogate_validation_matches,
)
from .metrics import compute_behavior_similarity, compute_consistency_summary, identify_largest_bias_prompts
from .plots import (
    plot_behavior_comparison,
    plot_bland_altman,
    plot_error_histogram,
    plot_fitness_3d,
    plot_scatter_consistency,
    plot_topk_overlap,
)
from .report import write_analysis_report


def _resolve_output_dir(cli_output_dir: Path | None, prompt_results_path: Path) -> Path:
    """Resolve the output directory for this analysis run."""
    if cli_output_dir is not None:
        output_dir = cli_output_dir.resolve()
    else:
        run_name = prompt_results_path.parent.name or prompt_results_path.stem
        output_dir = (cfg.RESULT_ROOT / run_name).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _resolve_paths_from_run_dir(run_dir: Path) -> tuple[Path, Path]:
    """Resolve prompt/java result sources from one surrogate-validation run directory."""
    matches_path = run_dir / "surrogate_validation_matches.csv"
    if not matches_path.exists():
        raise FileNotFoundError(f"Expected surrogate_validation_matches.csv under run directory: {run_dir}")
    return matches_path, matches_path


def _find_latest_surrogate_validation_run() -> Path:
    """Find the most recent surrogate-validation run under eagle/logs."""
    logs_root = (cfg.ANALYSIS_ROOT.parent / "logs").resolve()
    if not logs_root.exists():
        raise FileNotFoundError(f"Logs directory not found: {logs_root}")
    candidates = [
        path
        for path in logs_root.iterdir()
        if path.is_dir() and path.name.startswith("surrogate_validation_")
    ]
    if not candidates:
        raise FileNotFoundError(f"No surrogate_validation_* run directories found under {logs_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _write_rows_to_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> Path:
    """Write a list of row dicts to CSV with stable field order."""
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _behavior_missing_from_files(prompt_missing: list[str], java_missing: list[str]) -> list[str]:
    """Return the union of missing behavior metrics from both sources."""
    return sorted(set(prompt_missing) | set(java_missing))


def _write_config_snapshot(
    output_dir: Path,
    *,
    run_dir: Path | None,
    prompt_results_path: Path,
    java_results_path: Path,
    behavior_prompt_path: Path | None,
    behavior_java_path: Path | None,
) -> Path:
    """Persist the effective configuration for reproducibility."""
    snapshot = {
        "run_dir": str(run_dir) if run_dir else None,
        "prompt_results_path": str(prompt_results_path),
        "java_results_path": str(java_results_path),
        "behavior_prompt_path": str(behavior_prompt_path) if behavior_prompt_path else None,
        "behavior_java_path": str(behavior_java_path) if behavior_java_path else None,
        "result_root": str(cfg.RESULT_ROOT),
        "top_k_values": list(cfg.TOP_K_VALUES),
        "figures_dirname": cfg.FIGURES_DIRNAME,
        "summary_metrics_filename": cfg.SUMMARY_METRICS_FILENAME,
        "behavior_similarity_filename": cfg.BEHAVIOR_SIMILARITY_FILENAME,
        "report_filename": cfg.REPORT_FILENAME,
        "merged_results_filename": cfg.MERGED_RESULTS_FILENAME,
        "merged_behavior_filename": cfg.MERGED_BEHAVIOR_FILENAME,
        "behavior_metric_aliases": {key: list(value) for key, value in BEHAVIOR_FIELD_ALIASES.items()},
    }
    path = output_dir / cfg.CONFIG_SNAPSHOT_FILENAME
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_consistency_analysis(
    *,
    prompt_results_path: Path | None = None,
    java_results_path: Path | None = None,
    run_dir: Path | None = None,
    latest_run: bool = False,
    output_dir: Path | None = None,
    behavior_prompt_path: Path | None = None,
    behavior_java_path: Path | None = None,
) -> dict[str, Any]:
    """Run the full consistency-analysis pipeline and save outputs."""
    if latest_run:
        run_dir = _find_latest_surrogate_validation_run()
    if run_dir is not None:
        prompt_results_path, java_results_path = _resolve_paths_from_run_dir(run_dir)
    if prompt_results_path is None or java_results_path is None:
        raise ValueError("Either run_dir or both prompt_results_path and java_results_path must be provided.")

    resolved_output_dir = _resolve_output_dir(output_dir, prompt_results_path)
    figures_dir = resolved_output_dir / cfg.FIGURES_DIRNAME
    figures_dir.mkdir(parents=True, exist_ok=True)

    if run_dir is not None:
        run_rows = read_csv_rows(prompt_results_path)
        prompt_raw_rows, java_raw_rows = split_surrogate_validation_matches(run_rows)
        if not prompt_raw_rows or not java_raw_rows:
            raise ValueError(
                "surrogate_validation_matches.csv did not contain both eagle_final_test and surrogate_java_final_test rows."
            )
    else:
        prompt_raw_rows = read_csv_rows(prompt_results_path)
        java_raw_rows = read_csv_rows(java_results_path)

    prompt_result_rows = aggregate_result_rows(normalize_result_rows(prompt_raw_rows, "prompt_results"))
    java_result_rows = aggregate_result_rows(normalize_result_rows(java_raw_rows, "java_results"))
    merged_rows = merge_result_rows(prompt_result_rows, java_result_rows)
    if not merged_rows:
        raise ValueError("No aligned result rows were found between prompt and Java CSV inputs.")

    merged_behavior_rows: list[dict[str, Any]] = []
    missing_behavior_metrics: list[str] = sorted(BEHAVIOR_FIELD_ALIASES)
    if behavior_prompt_path:
        prompt_behavior_rows, prompt_missing = normalize_behavior_rows(read_csv_rows(behavior_prompt_path), "prompt_behavior")
    else:
        prompt_behavior_rows, prompt_missing = collect_behavior_rows_from_results(prompt_raw_rows)
    if behavior_java_path:
        java_behavior_rows, java_missing = normalize_behavior_rows(read_csv_rows(behavior_java_path), "java_behavior")
    else:
        java_behavior_rows, java_missing = collect_behavior_rows_from_results(java_raw_rows)

    aggregated_prompt_behavior = aggregate_behavior_rows(prompt_behavior_rows)
    aggregated_java_behavior = aggregate_behavior_rows(java_behavior_rows)
    if aggregated_prompt_behavior and aggregated_java_behavior:
        merged_behavior_rows = merge_behavior_rows(aggregated_prompt_behavior, aggregated_java_behavior)
    missing_behavior_metrics = _behavior_missing_from_files(prompt_missing, java_missing)

    summary_rows = compute_consistency_summary(merged_rows, cfg.TOP_K_VALUES)
    behavior_similarity_rows = compute_behavior_similarity(merged_behavior_rows) if merged_behavior_rows else []
    largest_bias_prompts = identify_largest_bias_prompts(merged_rows, limit=5)

    merged_results_path = _write_rows_to_csv(
        resolved_output_dir / cfg.MERGED_RESULTS_FILENAME,
        merged_rows,
        [
            "prompt_id",
            "seed",
            "map_name",
            "opponent",
            "prompt_score",
            "java_score",
            "prompt_win",
            "prompt_resource",
            "prompt_accuracy",
            "java_win",
            "java_resource",
            "java_accuracy",
            "prompt_sample_count",
            "java_sample_count",
        ],
    )
    summary_metrics_path = _write_rows_to_csv(
        resolved_output_dir / cfg.SUMMARY_METRICS_FILENAME,
        summary_rows,
        [
            "group_type",
            "group_value",
            "pair_count",
            "unique_prompt_count",
            "pearson",
            "spearman",
            "kendall_tau",
            "mae",
            "rmse",
            "mean_bias",
            "topk_overlap_5",
            "topk_overlap_10",
            "topk_overlap_20",
        ],
    )

    behavior_similarity_path: Path | None = None
    merged_behavior_path: Path | None = None
    if behavior_similarity_rows:
        behavior_similarity_path = _write_rows_to_csv(
            resolved_output_dir / cfg.BEHAVIOR_SIMILARITY_FILENAME,
            behavior_similarity_rows,
            [
                "group_type",
                "group_value",
                "behavior_metric",
                "pair_count",
                "prompt_mean",
                "java_mean",
                "prompt_mode",
                "java_mode",
                "exact_match_rate",
                "pearson",
                "mae",
                "rmse",
                "mean_bias",
            ],
        )
    if merged_behavior_rows:
        flattened_behavior_rows: list[dict[str, Any]] = []
        for row in merged_behavior_rows:
            flattened_behavior_rows.append(
                {
                    "prompt_id": row.get("prompt_id"),
                    "seed": row.get("seed"),
                    "map_name": row.get("map_name"),
                    "opponent": row.get("opponent"),
                    **{f"prompt_{metric}": value for metric, value in dict(row.get("prompt_metrics") or {}).items()},
                    **{f"java_{metric}": value for metric, value in dict(row.get("java_metrics") or {}).items()},
                }
            )
        fieldnames = sorted({key for row in flattened_behavior_rows for key in row.keys()})
        merged_behavior_path = _write_rows_to_csv(resolved_output_dir / cfg.MERGED_BEHAVIOR_FILENAME, flattened_behavior_rows, fieldnames)

    overall_summary = next((row for row in summary_rows if row.get("group_type") == "overall"), summary_rows[0])
    figure_paths = {
        "scatter_consistency": plot_scatter_consistency(merged_rows, figures_dir / cfg.SCATTER_FILENAME),
        "bland_altman": plot_bland_altman(merged_rows, figures_dir / cfg.BLAND_ALTMAN_FILENAME),
        "error_histogram": plot_error_histogram(merged_rows, figures_dir / cfg.ERROR_HISTOGRAM_FILENAME),
        "topk_overlap": plot_topk_overlap(overall_summary, figures_dir / cfg.TOPK_OVERLAP_FILENAME),
    }
    fitness_3d_path = plot_fitness_3d(merged_rows, figures_dir / cfg.FITNESS_3D_FILENAME)
    if fitness_3d_path is not None:
        figure_paths["fitness_3d"] = fitness_3d_path
    behavior_figure_path = plot_behavior_comparison(behavior_similarity_rows, figures_dir / cfg.BEHAVIOR_COMPARISON_FILENAME)
    if behavior_figure_path is not None:
        figure_paths["behavior_comparison"] = behavior_figure_path

    report_path = write_analysis_report(
        resolved_output_dir / cfg.REPORT_FILENAME,
        merged_rows=merged_rows,
        summary_rows=summary_rows,
        behavior_rows=behavior_similarity_rows,
        missing_behavior_metrics=missing_behavior_metrics,
        largest_bias_prompts=largest_bias_prompts,
        figures_dir=figures_dir,
    )
    config_snapshot_path = _write_config_snapshot(
        resolved_output_dir,
        run_dir=run_dir,
        prompt_results_path=prompt_results_path,
        java_results_path=java_results_path,
        behavior_prompt_path=behavior_prompt_path,
        behavior_java_path=behavior_java_path,
    )

    return {
        "output_dir": str(resolved_output_dir),
        "merged_results_path": str(merged_results_path),
        "summary_metrics_path": str(summary_metrics_path),
        "behavior_similarity_path": str(behavior_similarity_path) if behavior_similarity_path else None,
        "merged_behavior_path": str(merged_behavior_path) if merged_behavior_path else None,
        "figures": {name: str(path) for name, path in figure_paths.items()},
        "report_path": str(report_path),
        "config_snapshot_path": str(config_snapshot_path),
        "missing_behavior_metrics": missing_behavior_metrics,
    }


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI for consistency analysis."""
    parser = argparse.ArgumentParser(description="Analyze consistency between prompt-based and Java agent results.")
    parser.add_argument("--run_dir", type=Path, default=None, help="Optional surrogate-validation run directory under eagle/logs/<run>.")
    parser.add_argument("--latest-run", action="store_true", help="Use the most recent surrogate_validation_* run under eagle/logs.")
    parser.add_argument("--prompt_results", type=Path, default=cfg.DEFAULT_PROMPT_RESULTS_CSV, help="Prompt-based results CSV path.")
    parser.add_argument("--java_results", type=Path, default=cfg.DEFAULT_JAVA_RESULTS_CSV, help="Java agent results CSV path.")
    parser.add_argument("--output_dir", type=Path, default=None, help="Output directory for analysis artifacts.")
    parser.add_argument("--behavior_prompt", type=Path, default=cfg.DEFAULT_BEHAVIOR_PROMPT_CSV, help="Optional prompt-based behavior CSV path.")
    parser.add_argument("--behavior_java", type=Path, default=cfg.DEFAULT_BEHAVIOR_JAVA_CSV, help="Optional Java behavior CSV path.")
    return parser


def main() -> None:
    """CLI entry point for consistency analysis."""
    parser = build_argument_parser()
    args = parser.parse_args()
    if not args.latest_run and args.run_dir is None and (args.prompt_results is None or args.java_results is None):
        raise ValueError("Provide --latest-run, provide --run_dir, or provide both --prompt_results and --java_results.")

    outputs = run_consistency_analysis(
        prompt_results_path=Path(args.prompt_results).resolve() if args.prompt_results is not None else None,
        java_results_path=Path(args.java_results).resolve() if args.java_results is not None else None,
        run_dir=Path(args.run_dir).resolve() if args.run_dir is not None else None,
        latest_run=bool(args.latest_run),
        output_dir=Path(args.output_dir).resolve() if args.output_dir is not None else None,
        behavior_prompt_path=Path(args.behavior_prompt).resolve() if args.behavior_prompt is not None else None,
        behavior_java_path=Path(args.behavior_java).resolve() if args.behavior_java is not None else None,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
