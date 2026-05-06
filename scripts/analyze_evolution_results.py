"""CLI wrapper for plotting EAGLE evolution and final-test results."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from statistics import median


def _extract_eval_mode(argv: list[str]) -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--eval-mode",
        choices=["real", "surrogate", "round"],
        default="real",
    )

    known_args, remaining_argv = parser.parse_known_args(argv)
    return known_args.eval_mode, remaining_argv


def _extract_ea_mode(argv: list[str]) -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--ea-mode",
        choices=["auto", "mo", "ga"],
        default="auto",
    )
    known_args, remaining_argv = parser.parse_known_args(argv)
    return known_args.ea_mode, remaining_argv


def _patch_ea_log_parser(eval_mode: str) -> None:
    import eagle.analysis.evolution_result_analysis as analysis

    from eagle.evolution.component.log_parse import (
        parse_individuals_from_ea_log,
        parse_population_snapshot_from_ea_log,
    )

    analysis.parse_individuals_from_ea_log = parse_individuals_from_ea_log
    analysis.parse_population_snapshot_from_ea_log = parse_population_snapshot_from_ea_log


def _patch_analysis_ea_mode() -> None:
    import eagle.analysis.evolution_result_analysis as analysis

    if getattr(analysis, "_ea_mode_patched", False):
        return

    ga_generation_pattern = re.compile(r"generation_(\d+)\.txt$")
    original_build_argument_parser = analysis.build_argument_parser
    original_analyze_evolution_run = analysis.analyze_evolution_run

    def _extract_ga_generation_number(path: Path) -> int:
        match = ga_generation_pattern.match(path.name)
        if not match:
            return -1
        return int(match.group(1))

    def _detect_ea_mode(run_dir: Path):
        if any(run_dir.glob("generation_*_mo.txt")):
            return "mo"
        if any(path for path in run_dir.glob("generation_*.txt") if "_mo" not in path.name):
            return "ga"
        return None

    def _has_ga_generation_logs(run_dir: Path) -> bool:
        return any(path for path in run_dir.glob("generation_*.txt") if "_mo" not in path.name)

    def _has_matching_generation_logs(run_dir: Path, ea_mode: str) -> bool:
        if ea_mode == "mo":
            return any(run_dir.glob("generation_*_mo.txt"))
        if ea_mode == "ga":
            return _has_ga_generation_logs(run_dir)
        return any(run_dir.glob("generation_*_mo.txt")) or _has_ga_generation_logs(run_dir)

    def _find_latest_ea_run_dir(ea_mode: str) -> Path:
        candidates = []
        for path in analysis.EAGLE_LOGS_DIR.iterdir():
            if path.is_dir() and _has_matching_generation_logs(path, ea_mode):
                candidates.append(path)
        if not candidates:
            raise FileNotFoundError(
                f"No {ea_mode} EA run directories with generation logs found under {analysis.EAGLE_LOGS_DIR}"
            )
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _resolve_run_dir_with_ea_mode(run_dir: str | Path | None, latest: bool, ea_mode: str) -> Path:
        if run_dir is not None:
            return Path(run_dir).resolve()
        if latest:
            return _find_latest_ea_run_dir(ea_mode)
        raise ValueError("Provide --run-dir or use --latest.")

    def _load_ga_generation_scores(run_dir: Path) -> list[tuple[int, list[float]]]:
        generations: list[tuple[int, list[float]]] = []
        generation_logs = (
            path for path in run_dir.glob("generation_*.txt")
            if "_mo" not in path.name
        )
        for generation_log in sorted(generation_logs, key=_extract_ga_generation_number):
            generation_number = _extract_ga_generation_number(generation_log)
            if generation_number < 1:
                continue
            scores: list[float] = []
            for raw_line in generation_log.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line.startswith(("Individual", "RoundIndividual")):
                    continue
                fitness_start = line.find("Fitness:")
                if fitness_start == -1:
                    continue
                fitness_segment = line[fitness_start + len("Fitness:"):].strip()
                try:
                    parsed = json.loads(fitness_segment.replace("'", '"'))
                except Exception:
                    continue
                if isinstance(parsed, list) and parsed:
                    value = analysis._safe_float(parsed[0])
                    if not math.isnan(value):
                        scores.append(value)
            if scores:
                generations.append((generation_number, scores))
        return generations

    def _plot_ga_curve(
        run_dir: Path,
        output_dir: Path,
        custom_title: str | None = None,
        debug: bool = False,
    ) -> Path | None:
        plt = analysis._require_matplotlib()
        generations: list[int] = []
        best_scores: list[float] = []
        mean_scores: list[float] = []
        median_scores: list[float] = []
        worst_scores: list[float] = []

        for generation_number, scores in _load_ga_generation_scores(run_dir):
            generations.append(generation_number)
            best_scores.append(max(scores))
            mean_scores.append(sum(scores) / len(scores))
            median_scores.append(float(median(scores)))
            worst_scores.append(min(scores))

        if not generations:
            generation_entries = analysis._load_generation_entries(run_dir, debug=debug)
            for generation_number, individuals, _ in generation_entries:
                scores = []
                for individual in individuals:
                    fitness = list(getattr(individual, "fitness", []) or [])
                    score = analysis._safe_float(fitness[0]) if fitness else float("nan")
                    if not math.isnan(score):
                        scores.append(score)
                if scores:
                    generations.append(int(generation_number))
                    best_scores.append(max(scores))
                    mean_scores.append(sum(scores) / len(scores))
                    median_scores.append(float(median(scores)))
                    worst_scores.append(min(scores))

        if not generations:
            return None

        plt.figure(figsize=(10, 6))
        plt.plot(generations, best_scores, label="Best", linewidth=2.0)
        plt.plot(generations, mean_scores, label="Mean", linewidth=2.0)
        plt.plot(generations, median_scores, label="Median", linewidth=2.0)
        plt.plot(generations, worst_scores, label="Worst", linewidth=2.0)
        plt.xlabel("Generation")
        plt.ylabel("Fitness Score")
        plt.title(analysis._compose_plot_title("GA Generation Fitness Curve", custom_title))
        plt.grid(alpha=0.25)
        plt.legend(loc="best")

        figure_path = output_dir / "ga_fitness_curve.png"
        plt.tight_layout()
        plt.savefig(figure_path, dpi=200)
        plt.close()
        return figure_path

    def _analyze_evolution_run_with_ea_mode(
        run_dir: str | Path | None = None,
        *,
        latest: bool = False,
        title: str | None = None,
        debug: bool = False,
        eval_mode: str = "match",
        ea_mode: str = "auto",
    ) -> dict[str, object]:
        resolved_run_dir = _resolve_run_dir_with_ea_mode(run_dir, latest, ea_mode)
        detected = _detect_ea_mode(resolved_run_dir)
        resolved_ea_mode = detected if ea_mode == "auto" else ea_mode

        if resolved_ea_mode == "mo":
            summary = original_analyze_evolution_run(
                run_dir=resolved_run_dir,
                latest=False,
                title=title,
                debug=debug,
                eval_mode=eval_mode,
            )
            summary["ea_mode"] = resolved_ea_mode
            summary_path = Path(summary["summary_path"])
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return summary

        output_dir = analysis.ensure_directory(resolved_run_dir / "analysis" / "evolution")
        generation_output_dir = analysis.ensure_directory(output_dir / "generation_fitness")
        ga_curve_path = _plot_ga_curve(
            resolved_run_dir,
            generation_output_dir,
            custom_title=title,
            debug=debug,
        )

        final_test_path = analysis._resolve_final_test_path(resolved_run_dir)
        final_test_figures: dict[str, str] = {}
        if final_test_path is not None:
            final_test_output_dir = analysis.ensure_directory(output_dir / "final_test")
            for interval_mode in analysis.FINAL_TEST_MODES:
                figure_path = analysis._plot_final_test_mode(
                    resolved_run_dir,
                    final_test_output_dir,
                    final_test_path,
                    interval_mode,
                    custom_title=title,
                )
                if figure_path is not None:
                    final_test_figures[interval_mode] = str(figure_path)

        summary = {
            "run_dir": str(resolved_run_dir),
            "generation_scatter_figures": [],
            "generation_animation_gif": None,
            "ga_fitness_curve": str(ga_curve_path) if ga_curve_path is not None else None,
            "final_test_result_path": str(final_test_path) if final_test_path is not None else None,
            "final_test_figures": final_test_figures,
            "title": title,
            "debug": debug,
            "eval_mode": eval_mode,
            "ea_mode": resolved_ea_mode,
        }
        summary_path = output_dir / "analysis_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["summary_path"] = str(summary_path)
        return summary

    def _build_argument_parser_with_ea_mode():
        parser = original_build_argument_parser()
        parser.add_argument(
            "--ea-mode",
            choices=["auto", "mo", "ga"],
            default="auto",
            help="Evolution analysis mode: auto-detect from logs, or force 'mo'/'ga'.",
        )
        return parser

    def _main_with_ea_mode() -> None:
        parser = analysis.build_argument_parser()
        args = parser.parse_args()
        summary = analysis.analyze_evolution_run(
            run_dir=args.run_dir,
            latest=args.latest,
            title=args.title,
            debug=args.debug,
            eval_mode=args.eval_mode,
            ea_mode=args.ea_mode,
        )
        analysis._debug_print(args.debug, json.dumps(summary, ensure_ascii=False, indent=2))

    analysis.build_argument_parser = _build_argument_parser_with_ea_mode
    analysis.analyze_evolution_run = _analyze_evolution_run_with_ea_mode
    analysis.main = _main_with_ea_mode
    analysis._ea_mode_patched = True


def main() -> None:
    eval_mode, argv_after_eval = _extract_eval_mode(sys.argv[1:])
    ea_mode, original_argv = _extract_ea_mode(argv_after_eval)
    _patch_ea_log_parser(eval_mode)

    import eagle.analysis.evolution_result_analysis as analysis
    _patch_analysis_ea_mode()

    # Keep wrapper-only options for the downstream flow.
    sys.argv = [sys.argv[0], "--eval-mode", eval_mode, "--ea-mode", ea_mode, *original_argv]
    analysis.main()


if __name__ == "__main__":
    main()
