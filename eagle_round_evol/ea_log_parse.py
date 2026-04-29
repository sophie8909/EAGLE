"""Parse human-readable EA logs back into prompts and Individual objects."""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
import re
from statistics import median

from .individual import Individual


INDIVIDUAL_PREFIXES = ("Individual(", "RoundIndividual(")


def _split_top_level_fields(individual_str: str) -> list[str]:
    """Split a serialized Individual(...) payload without breaking nested dicts."""
    fields = []
    start = 0
    depth = 0
    in_string = False
    string_quote = ""
    escaped = False

    for i, char in enumerate(individual_str):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            continue

        if char in ("'", '"'):
            in_string = True
            string_quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            fields.append(individual_str[start:i].strip())
            start = i + 1

    tail = individual_str[start:].strip()
    if tail:
        fields.append(tail)
    return fields


def _parse_literal(value: str):
    """Best-effort parser for literal values embedded inside log lines."""
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def _extract_individual_payload(line: str) -> str | None:
    """Extract the constructor payload from Individual(...) log lines."""
    for prefix in INDIVIDUAL_PREFIXES:
        start_idx = line.find(prefix)
        if start_idx == -1:
            continue
        end_idx = line.rfind(")")
        if end_idx == -1 or end_idx <= start_idx:
            return None
        return line[start_idx + len(prefix):end_idx]
    return None


def parse_individuals_from_ea_log(log_file: str):
    """Parse serialized Individual records back into runtime Individual objects."""
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    
    individuals = []
    front = []
    for line in lines:
        if line.startswith("Pareto Front "):
            if front:
                individuals.append(front)
                front = []
            continue
        if not line.startswith(("Individual", "RoundIndividual")):
            continue

        individual_str = _extract_individual_payload(line)
        if individual_str is None:
            continue

        components = _split_top_level_fields(individual_str)
        individual_data = {}
        for component in components:
            if "=" in component:
                key, value = component.split("=", 1)
                individual_data[key.strip()] = _parse_literal(value.strip())

        individual = Individual(**individual_data)
        fitness_start = line.find("Fitness:")
        if fitness_start != -1:
            fitness_segment = line[fitness_start + len("Fitness:"):].strip()
            eval_mode_start = fitness_segment.find(" - EvalMode:")
            if eval_mode_start != -1:
                fitness_segment = fitness_segment[:eval_mode_start].strip()
            if fitness_segment.startswith("[") and fitness_segment.endswith("]"):
                individual.fitness = _parse_literal(fitness_segment)

        front.append(individual)

    if front:
        individuals.append(front)

    return individuals


def parse_population_snapshot_from_ea_log(log_file: str) -> list[Individual]:
    """Parse the full population snapshot block from one generation log."""
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    in_population_snapshot = False
    population: list[Individual] = []
    for raw_line in lines:
        line = raw_line.strip()
        if line == "Population Snapshot:":
            in_population_snapshot = True
            continue
        if not in_population_snapshot:
            continue
        if not line.startswith(("Individual", "RoundIndividual")):
            continue

        individual_str = _extract_individual_payload(line)
        if individual_str is None:
            continue

        components = _split_top_level_fields(individual_str)
        individual_data = {}
        for component in components:
            if "=" in component:
                key, value = component.split("=", 1)
                individual_data[key.strip()] = _parse_literal(value.strip())

        individual = Individual(**individual_data)
        fitness_start = line.find("Fitness:")
        if fitness_start != -1:
            fitness_segment = line[fitness_start + len("Fitness:"):].strip()
            eval_mode_start = fitness_segment.find(" - EvalMode:")
            if eval_mode_start != -1:
                fitness_segment = fitness_segment[:eval_mode_start].strip()
            if fitness_segment.startswith("[") and fitness_segment.endswith("]"):
                individual.fitness = _parse_literal(fitness_segment)

        population.append(individual)

    return population


def _patch_round_analysis_ga_mode() -> None:
    try:
        import eagle.analysis.evolution_result_analysis as analysis
    except Exception:
        return

    if getattr(analysis, "_round_ga_mode_patched", False):
        return

    ga_generation_pattern = re.compile(r"generation_(\d+)\.txt$")

    def _extract_ga_generation_number(path: Path) -> int:
        match = ga_generation_pattern.match(path.name)
        if not match:
            return -1
        return int(match.group(1))

    def _detect_ea_mode(run_dir: Path, requested_mode: str) -> str:
        mode = (requested_mode or "auto").lower()
        if mode in {"mo", "ga"}:
            return mode
        if any(run_dir.glob("generation_*_mo.txt")):
            return "mo"
        if any(
            _extract_ga_generation_number(path) > 0
            for path in run_dir.glob("generation_*.txt")
        ):
            return "ga"
        return "mo"

    def _load_ga_generation_scores(run_dir: Path) -> list[tuple[int, list[float]]]:
        generations: list[tuple[int, list[float]]] = []
        for generation_log in sorted(run_dir.glob("generation_*.txt"), key=_extract_ga_generation_number):
            generation_number = _extract_ga_generation_number(generation_log)
            if generation_number < 1:
                continue
            scores: list[float] = []
            with generation_log.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line.startswith(("Individual", "RoundIndividual")):
                        continue
                    fitness_start = line.find("Fitness:")
                    if fitness_start == -1:
                        continue
                    fitness_segment = line[fitness_start + len("Fitness:"):].strip()
                    if fitness_segment.startswith("[") and fitness_segment.endswith("]"):
                        parsed = _parse_literal(fitness_segment)
                        if isinstance(parsed, list) and parsed:
                            value = analysis._safe_float(parsed[0])
                            if not math.isnan(value):
                                scores.append(value)
            if scores:
                generations.append((generation_number, scores))
        return generations

    def _plot_generation_ga_curve(
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

        generation_entries = analysis._load_generation_entries(run_dir, debug=debug)
        if generation_entries:
            for generation_number, individuals, _ in generation_entries:
                scores: list[float] = []
                for individual in individuals:
                    fitness = list(getattr(individual, "fitness", []) or [])
                    score = analysis._safe_float(fitness[0]) if len(fitness) > 0 else float("nan")
                    if not math.isnan(score):
                        scores.append(score)
                if scores:
                    generations.append(int(generation_number))
                    best_scores.append(max(scores))
                    mean_scores.append(sum(scores) / len(scores))
                    median_scores.append(float(median(scores)))
                    worst_scores.append(min(scores))
        else:
            for generation_number, scores in _load_ga_generation_scores(run_dir):
                generations.append(int(generation_number))
                best_scores.append(max(scores))
                mean_scores.append(sum(scores) / len(scores))
                median_scores.append(float(median(scores)))
                worst_scores.append(min(scores))

        if not generations:
            return None

        plt.figure(figsize=(10, 6))
        plt.plot(generations, best_scores, label="Best", linewidth=2.0, color="#2ca02c")
        plt.plot(generations, mean_scores, label="Mean", linewidth=2.0, color="#1f77b4")
        plt.plot(generations, median_scores, label="Median", linewidth=2.0, color="#ff7f0e")
        plt.plot(generations, worst_scores, label="Worst", linewidth=2.0, color="#d62728")

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

    original_build_argument_parser = analysis.build_argument_parser
    original_analyze_evolution_run = analysis.analyze_evolution_run

    def _build_argument_parser_with_ea_mode():
        parser = original_build_argument_parser()
        parser.add_argument(
            "--ea-mode",
            choices=["auto", "mo", "ga"],
            default="auto",
            help="Evolution analysis mode: auto-detect from logs, or force 'mo'/'ga'.",
        )
        return parser

    def _analyze_evolution_run_with_ea_mode(
        run_dir: str | Path | None = None,
        *,
        latest: bool = False,
        title: str | None = None,
        debug: bool = False,
        eval_mode: str = "match",
        ea_mode: str = "auto",
    ) -> dict[str, object]:
        resolved_run_dir = analysis._resolve_run_dir(run_dir, latest)
        resolved_ea_mode = _detect_ea_mode(resolved_run_dir, ea_mode)

        if resolved_ea_mode != "ga":
            summary = original_analyze_evolution_run(
                run_dir=resolved_run_dir,
                latest=latest,
                title=title,
                debug=debug,
                eval_mode=eval_mode,
            )
            summary["ea_mode"] = resolved_ea_mode
            summary_path = Path(summary["summary_path"])
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return summary

        if eval_mode not in {"match", "round"}:
            raise ValueError(f"Unsupported eval_mode: {eval_mode!r}")

        output_dir = analysis.ensure_directory(resolved_run_dir / "analysis" / "evolution")
        generation_output_dir = analysis.ensure_directory(output_dir / "generation_fitness")

        ga_curve_path = _plot_generation_ga_curve(
            resolved_run_dir,
            generation_output_dir,
            custom_title=title,
            debug=debug,
        )

        summary = {
            "run_dir": str(resolved_run_dir),
            "generation_scatter_figures": [],
            "generation_animation_gif": None,
            "ga_fitness_curve": str(ga_curve_path) if ga_curve_path is not None else None,
            "final_test_result_path": None,
            "final_test_figures": {},
            "title": title,
            "debug": debug,
            "eval_mode": eval_mode,
            "ea_mode": resolved_ea_mode,
        }
        summary_path = output_dir / "analysis_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["summary_path"] = str(summary_path)
        return summary

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
    analysis._round_ga_mode_patched = True


_patch_round_analysis_ga_mode()
