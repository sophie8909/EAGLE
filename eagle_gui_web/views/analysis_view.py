"""Live analysis view."""

from __future__ import annotations

import asyncio
import math
import re
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle.analysis.evolution_result_analysis import (
    build_analysis_context,
    parse_final_test_analysis,
    parse_ga_convergence,
    parse_mo_analysis,
    parse_time_analysis,
)
from eagle_gui_web import services
from eagle_gui_web.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    COLORS,
    INPUT_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TABLE_CLASS,
    TEXTAREA_CLASS,
    height_class,
)
from eagle_gui_web.ui_actions import safe_click


def build_analysis_view(state: Any) -> dict[str, Any]:
    """Build live GA/MO and timing analysis panels."""
    controls: dict[str, Any] = {}

    async def refresh_analysis() -> None:
        try:
            summary, body = await asyncio.to_thread(services.build_analysis, state.run.current_run_dir)
            mo_summary = await asyncio.to_thread(_build_mo_analysis_text, state.run.current_run_dir)
            final_test_analysis = await asyncio.to_thread(_build_final_test_analysis_text, state.run.current_run_dir)
            ga_convergence = await asyncio.to_thread(_build_ga_convergence_options, state.run.current_run_dir)
            await refresh_mo_section()
        except (OSError, ValueError) as exc:
            summary, body = "Analysis load error", str(exc)
            mo_summary = str(exc)
            final_test_analysis = str(exc)
            ga_convergence = None
            _set_mo_hidden(str(exc))
        state.analysis.summary = summary
        state.analysis.body = body
        _render_ga_convergence(ga_chart_container, ga_convergence)
        mo_summary_text.value = mo_summary
        mo_summary_text.update()
        final_test_text.value = final_test_analysis
        final_test_text.update()
        summary_label.set_text(summary)
        body_text.value = body
        body_text.update()

    async def refresh_timing() -> None:
        try:
            summary, rows, body = await asyncio.to_thread(services.build_timing, state.run.current_run_dir)
            time_analysis = await asyncio.to_thread(_build_time_analysis_text, state.run.current_run_dir)
        except (OSError, ValueError) as exc:
            summary, rows, body = "Timing load error", [], str(exc)
            time_analysis = str(exc)
        state.analysis.timing_summary = summary
        state.analysis.timing_rows = rows
        state.analysis.timing_body = body
        time_analysis_text.value = time_analysis
        time_analysis_text.update()
        timing_summary_label.set_text(summary)
        timing_table.rows = rows
        timing_table.update()
        timing_text.value = body
        timing_text.update()

    async def refresh_all() -> None:
        await refresh_analysis()
        await refresh_timing()

    async def refresh_mo_section(*, force_generate: bool = False) -> None:
        run_dir = state.run.current_run_dir
        if run_dir is None:
            _set_mo_hidden("No run selected.")
            return

        mo_summary = await asyncio.to_thread(_build_mo_analysis_text, run_dir)
        if mo_summary == "No multi-objective data found.":
            _set_mo_hidden(mo_summary)
            return

        artifact_data = await asyncio.to_thread(
            services.generate_mo_analysis_artifacts, run_dir
        ) if force_generate else _discover_mo_artifacts(run_dir)

        state.analysis.mo_visible = True
        state.analysis.mo_summary = mo_summary
        state.analysis.mo_animation_path = str(artifact_data.get("animation_path") or "")
        state.analysis.mo_generation_choices = list(artifact_data.get("generation_choices") or [])
        state.analysis.mo_static_plot_paths = dict(artifact_data.get("static_plot_paths") or {})
        if state.analysis.mo_selected_generation not in state.analysis.mo_generation_choices:
            state.analysis.mo_selected_generation = (
                state.analysis.mo_generation_choices[-1] if state.analysis.mo_generation_choices else ""
            )
        mo_section.visible = True
        mo_summary_text.value = state.analysis.mo_summary
        mo_summary_text.update()
        _refresh_mo_options()
        _render_mo_artifacts()

    def _set_mo_hidden(message: str) -> None:
        state.analysis.mo_visible = False
        state.analysis.mo_summary = message
        state.analysis.mo_animation_path = ""
        state.analysis.mo_generation_choices = []
        state.analysis.mo_selected_generation = ""
        state.analysis.mo_static_plot_paths = {}
        mo_section.visible = False
        mo_summary_text.value = message
        mo_summary_text.update()
        _refresh_mo_options()
        _render_mo_artifacts()

    def _refresh_mo_options() -> None:
        generation_select.options = list(state.analysis.mo_generation_choices)
        if state.analysis.mo_selected_generation not in state.analysis.mo_generation_choices:
            state.analysis.mo_selected_generation = (
                state.analysis.mo_generation_choices[-1] if state.analysis.mo_generation_choices else ""
            )
        generation_select.value = state.analysis.mo_selected_generation or None
        generation_select.update()

    def _render_mo_artifacts() -> None:
        animation_container.clear()
        static_plot_container.clear()

        animation_path = state.analysis.mo_animation_path
        if animation_path and Path(animation_path).exists():
            with animation_container:
                ui.label("Pareto animation").classes(SECTION_HEADER_CLASS)
                ui.image(animation_path).classes("w-full max-w-5xl")
        elif state.analysis.mo_visible:
            with animation_container:
                ui.label("Pareto animation").classes(SECTION_HEADER_CLASS)
                ui.label("No Pareto animation generated yet.")

        static_plot_path = state.analysis.mo_static_plot_paths.get(state.analysis.mo_selected_generation, "")
        if static_plot_path and Path(static_plot_path).exists():
            with static_plot_container:
                ui.label(f"Generation {state.analysis.mo_selected_generation} Pareto front").classes(
                    SECTION_HEADER_CLASS
                )
                ui.image(static_plot_path).classes("w-full max-w-5xl")
        elif state.analysis.mo_visible:
            with static_plot_container:
                ui.label("Static Pareto front").classes(SECTION_HEADER_CLASS)
                ui.label("No static Pareto front generated for the selected generation.")

    def _discover_mo_artifacts(run_dir: Path) -> dict[str, Any]:
        analysis_dir = run_dir / "analysis" / "evolution"
        generation_dir = analysis_dir / "generation_fitness"
        animation_path = generation_dir / "generation_fitness_animation.gif"
        static_plot_paths: dict[str, str] = {}
        generation_choices: list[str] = []
        if generation_dir.exists():
            for path in sorted(generation_dir.glob("generation_*_fitness_scatter.png"), key=_generation_sort_key):
                if path.name == "generation_fitness_scatter_all.png":
                    continue
                match = re.search(r"generation_(\d+)_fitness_scatter\.png$", path.name)
                if not match:
                    continue
                generation = match.group(1)
                generation_choices.append(generation)
                static_plot_paths[generation] = str(path)
        return {
            "animation_path": str(animation_path) if animation_path.exists() else "",
            "generation_choices": generation_choices,
            "static_plot_paths": static_plot_paths,
        }

    def on_mo_generation_changed(event: Any) -> None:
        state.analysis.mo_selected_generation = str(event.value or "")
        _render_mo_artifacts()

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Analysis").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            summary_label = ui.label(state.analysis.summary)
            ui.button("Refresh analysis", on_click=safe_click(refresh_all, label="Refresh analysis")).classes(BUTTON_CLASS)
        body_text = ui.textarea(value=state.analysis.body).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(300)} w-full"
        )
        ga_chart_container = ui.column().classes("w-full gap-3")

        with ui.column().classes("w-full gap-3") as mo_section:
            ui.label("MO Analysis").classes(SECTION_HEADER_CLASS)
            with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
                ui.button(
                    "Generate MO Analysis",
                    on_click=safe_click(
                        lambda: refresh_mo_section(force_generate=True),
                        label="Generate MO Analysis",
                    ),
                ).classes(BUTTON_CLASS)
                generation_select = ui.select([], label="Generation", on_change=on_mo_generation_changed).classes(
                    f"{INPUT_CLASS} w-64"
                )
            mo_summary_text = ui.textarea(value=state.analysis.mo_summary).props("readonly").classes(
                f"{TEXTAREA_CLASS} {height_class(220)} w-full"
            )
            animation_container = ui.column().classes("w-full gap-3")
            static_plot_container = ui.column().classes("w-full gap-3")

        ui.label("Final Test").classes(SECTION_HEADER_CLASS)
        final_test_text = ui.textarea(value="No final test data found.").props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(170)} w-full"
        )

        ui.label("Time Analysis").classes(SECTION_HEADER_CLASS)
        time_analysis_text = ui.textarea(value="No timing data found.").props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(150)} w-full"
        )
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            timing_summary_label = ui.label(state.analysis.timing_summary)
            ui.button("Refresh timing", on_click=safe_click(refresh_timing, label="Refresh timing")).classes(BUTTON_CLASS)
        timing_table = ui.table(
            columns=[
                {"name": "phase", "label": "Phase", "field": "phase", "align": "left"},
                {"name": "count", "label": "Count", "field": "count"},
                {"name": "total_sec", "label": "Total sec", "field": "total_sec"},
                {"name": "avg_sec", "label": "Avg sec", "field": "avg_sec"},
                {"name": "max_sec", "label": "Max sec", "field": "max_sec"},
            ],
            rows=[],
        ).classes(f"{TABLE_CLASS} w-full")
        timing_text = ui.textarea(value=state.analysis.timing_body).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(300)} w-full"
        )

    mo_section.visible = False
    _refresh_mo_options()
    _render_mo_artifacts()

    controls["refresh_analysis"] = refresh_all
    controls["refresh_mo_section"] = refresh_mo_section
    return controls


def _build_mo_analysis_text(run_dir: Path | None) -> str:
    """Render multi-objective analysis separately from GA/final-test panels."""
    with services.LoggedOperation("parsing logs", kind="mo_analysis", run_dir=run_dir):
        if run_dir is None:
            return "No multi-objective data found."
        log_text = _read_mo_analysis_text(run_dir)
        if not build_analysis_context(log_text).get("is_multi_objective"):
            return "No multi-objective data found."
        analysis = parse_mo_analysis(log_text)
        if not analysis:
            return "No multi-objective data found."
        lines = [
            f"Pareto front count: {analysis.get('pareto_front_count', 0)}",
        ]
        if analysis.get("objective_names"):
            lines.append("Objectives: " + ", ".join(str(name) for name in analysis["objective_names"]))
        front_rows = list(analysis.get("final_pareto_front_individuals", []))
        if front_rows:
            lines.append("Final Pareto front individuals:")
            for row in front_rows[:12]:
                lines.append(f"- {row.get('id')}: {_format_fitness(row.get('fitness'))}")
        best_rows = list(analysis.get("objective_best", []))
        if best_rows:
            lines.append("Objective best:")
            for row in best_rows:
                lines.append(f"- {row.get('objective')}: {row.get('individual')} = {float(row.get('value', 0.0)):.4g}")
        trends = analysis.get("objective_trends")
        if isinstance(trends, dict) and trends.get("generations"):
            lines.append("Objective trends:")
            lines.append(f"- generations: {', '.join(str(item) for item in trends['generations'])}")
            for objective in analysis.get("objective_names", []):
                if objective in trends:
                    lines.append(f"- {objective}: {', '.join(_format_float(item) for item in trends[objective])}")
        return "\n".join(lines)


def _read_mo_analysis_text(run_dir: Path) -> str:
    """Read only MO generation logs for the MO analysis section."""
    with services.LoggedOperation("reading large files", kind="mo_generation_logs", run_dir=run_dir):
        parts: list[str] = []
        for path in sorted(run_dir.glob("generation_*_mo.txt"), key=_generation_sort_key):
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)


def _render_ga_convergence(container: Any, options: dict[str, Any] | None) -> None:
    """Render the GA convergence chart only when data is available."""
    container.clear()
    if not options:
        return
    with container:
        ui.label("GA Convergence").classes(SECTION_HEADER_CLASS)
        ui.echart(options).classes("w-full h-80")


def _build_ga_convergence_options(run_dir: Path | None) -> dict[str, Any] | None:
    """Build ECharts options for single-objective GA convergence."""
    with services.LoggedOperation("parsing logs", kind="ga_convergence", run_dir=run_dir):
        if run_dir is None:
            return None
        log_text = _read_ga_convergence_text(run_dir)
        if not build_analysis_context(log_text).get("is_single_objective"):
            return None
        data = parse_ga_convergence(log_text)
        if not data:
            return None
        generations = list(data.get("generations", []))
        series = [
            {
                "name": "Best fitness",
                "type": "line",
                "smooth": True,
                "data": list(data.get("best_fitness", [])),
                "lineStyle": {"color": COLORS["sky_blue"], "width": 3},
                "itemStyle": {"color": COLORS["sky_blue"]},
            }
        ]
        if data.get("average_fitness"):
            series.append(
                {
                    "name": "Average fitness",
                    "type": "line",
                    "smooth": True,
                    "data": list(data["average_fitness"]),
                    "lineStyle": {"color": COLORS["bronze"], "width": 2},
                    "itemStyle": {"color": COLORS["bronze"]},
                }
            )
        return {
            "backgroundColor": "transparent",
            "color": [COLORS["sky_blue"], COLORS["bronze"]],
            "tooltip": {"trigger": "axis"},
            "legend": {"textStyle": {"color": COLORS["text"]}},
            "grid": {"left": 48, "right": 24, "top": 48, "bottom": 44},
            "xAxis": {
                "type": "category",
                "name": "generation",
                "data": generations,
                "axisLine": {"lineStyle": {"color": COLORS["border"]}},
                "axisLabel": {"color": COLORS["muted"]},
                "nameTextStyle": {"color": COLORS["muted"]},
            },
            "yAxis": {
                "type": "value",
                "name": "fitness",
                "axisLine": {"lineStyle": {"color": COLORS["border"]}},
                "axisLabel": {"color": COLORS["muted"]},
                "splitLine": {"lineStyle": {"color": COLORS["border"]}},
                "nameTextStyle": {"color": COLORS["muted"]},
            },
            "series": series,
        }


def _read_ga_convergence_text(run_dir: Path) -> str:
    """Read GA generation logs without loading MO generation files."""
    with services.LoggedOperation("reading large files", kind="ga_generation_logs", run_dir=run_dir):
        parts: list[str] = []
        for path in sorted(run_dir.glob("generation_*.txt"), key=_generation_sort_key):
            if path.name.endswith("_mo.txt"):
                continue
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)


def _generation_sort_key(path: Path) -> int:
    """Sort generation logs by numeric generation suffix."""
    match = re.search(r"generation_(\d+)", path.name)
    return int(match.group(1)) if match else -1


def _build_final_test_analysis_text(run_dir: Path | None) -> str:
    """Render final-test analysis separately from evolution analysis."""
    with services.LoggedOperation("parsing logs", kind="final_test_analysis", run_dir=run_dir):
        if run_dir is None:
            return "No final test data found."
        log_text = _read_final_test_analysis_text(run_dir)
        analysis = parse_final_test_analysis(log_text)
        if not analysis.get("has_final_test"):
            return "No final test data found."
        lines: list[str] = []
        if "games" in analysis:
            lines.append(f"Final test games: {analysis['games']}")
        for key, label in (("wins", "Wins"), ("losses", "Losses"), ("draws", "Draws")):
            if key in analysis:
                lines.append(f"{label}: {analysis[key]}")
        if "win_rate" in analysis:
            lines.append(f"Win rate: {float(analysis['win_rate']) * 100:.1f}%")
        if analysis.get("maps"):
            lines.append("Maps: " + ", ".join(str(item) for item in analysis["maps"]))
        if analysis.get("opponents"):
            lines.append("Opponents: " + ", ".join(str(item) for item in analysis["opponents"]))
        if "skipped_games" in analysis:
            lines.append(f"Skipped games: {analysis['skipped_games']}")
        if "failed_games" in analysis:
            lines.append(f"Failed games: {analysis['failed_games']}")
        if analysis.get("skip_reason"):
            lines.append(f"Skip reason: {analysis['skip_reason']}")
        return "\n".join(lines) if lines else "FINAL_TEST markers found, but no detailed results are available yet."


def _read_final_test_analysis_text(run_dir: Path) -> str:
    """Read final-test artifacts without mixing them into evolution analysis."""
    with services.LoggedOperation("reading large files", kind="final_test_logs", run_dir=run_dir):
        parts: list[str] = []
        for filename in ("final_test_results.json", "final_test_result.json"):
            path = run_dir / filename
            if path.exists():
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
        log_files = sorted(run_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in log_files[:3]:
            text = path.read_text(encoding="utf-8", errors="replace")
            if "FINAL_TEST" in text.upper() or "Final Test" in text:
                parts.append(text)
        process_log_path = services.process_log_path()
        if process_log_path and process_log_path.exists():
            text = process_log_path.read_text(encoding="utf-8", errors="replace")
            if ("FINAL_TEST" in text.upper() or "Final Test" in text) and str(run_dir) in text:
                parts.append(text)
        return "\n".join(parts)


def _build_time_analysis_text(run_dir: Path | None) -> str:
    """Render a compact time-analysis summary from selected-run timing text."""
    with services.LoggedOperation("parsing logs", kind="time_analysis", run_dir=run_dir):
        if run_dir is None:
            return "No timing data found."
        log_text = _read_time_analysis_text(run_dir)
        timing = parse_time_analysis(log_text)
        if not timing:
            return "No timing data found."
        labels = [
            ("total_runtime", "Total runtime"),
            ("generation_runtime", "Generation runtime"),
            ("average_generation_time", "Average generation time"),
            ("evaluation_time", "Evaluation time"),
            ("llm_call_time", "LLM call time"),
        ]
        return "\n".join(f"{label}: {_format_seconds(timing[key])}" for key, label in labels if key in timing)


def _read_time_analysis_text(run_dir: Path) -> str:
    """Read timing artifacts without touching GA/MO/final-test analysis files."""
    with services.LoggedOperation("reading large files", kind="timing_logs", run_dir=run_dir):
        parts: list[str] = []
        for filename in ("timing_summary.json", "timing_events.jsonl", "timing_report.md"):
            path = run_dir / filename
            if path.exists():
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)


def _format_fitness(value: object) -> str:
    """Format one objective-fitness mapping for display."""
    if not isinstance(value, dict):
        return str(value)
    return ", ".join(f"{key}={_format_float(item)}" for key, item in value.items())


def _format_float(value: object) -> str:
    """Format a compact numeric value."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "n/a"
    return f"{number:.4g}"


def _format_seconds(value: object) -> str:
    """Format seconds for the compact time-analysis panel."""
    return f"{float(value):.3f} sec"
