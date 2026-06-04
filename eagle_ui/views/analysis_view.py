"""Live analysis view."""

from __future__ import annotations

import asyncio
import json
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
from eagle.analysis.objective_metadata import load_run_objective_specs
from eagle_ui import services
from eagle_ui.components.selectors import create_run_selector
from eagle_ui.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    COLORS,
    INPUT_CLASS,
    PAGE_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TABLE_CLASS,
    TAB_CLASS,
    TEXTAREA_CLASS,
    height_class,
)
from eagle_ui.ui_actions import safe_click


def build_analysis_view(state: Any) -> dict[str, Any]:
    """Build live GA/MO and timing analysis panels."""
    controls: dict[str, Any] = {}
    mo_generate_button: Any | None = None

    async def refresh_runs(selected_run_dir: Path | None = None) -> None:
        runs = await asyncio.to_thread(services.run_choices)
        explicit_sync = selected_run_dir is not None
        if selected_run_dir is not None:
            state.analysis.analysis_selected_run_dir = selected_run_dir
            state.analysis.analysis_run_selected_manually = False
        if (
            state.analysis.analysis_selected_run_dir is None
            and not state.analysis.analysis_run_selected_manually
            and runs
        ):
            state.analysis.analysis_selected_run_dir = Path(runs[0])
        elif (
            state.analysis.analysis_selected_run_dir is not None
            and str(state.analysis.analysis_selected_run_dir) not in runs
        ):
            if explicit_sync:
                pass
            elif not state.analysis.analysis_run_selected_manually and runs:
                state.analysis.analysis_selected_run_dir = Path(runs[0])
            else:
                state.analysis.analysis_selected_run_dir = None
        run_select.options = [
            "",
            *(
                [str(state.analysis.analysis_selected_run_dir)]
                if state.analysis.analysis_selected_run_dir is not None
                and str(state.analysis.analysis_selected_run_dir) not in runs
                else []
            ),
            *runs,
        ]
        run_select.value = (
            str(state.analysis.analysis_selected_run_dir) if state.analysis.analysis_selected_run_dir else ""
        )
        run_select.update()
        selected_label.set_text(f"Selected folder: {state.analysis.analysis_selected_run_dir or '(none)'}")
        await refresh_selected_run_config()

    async def refresh_selected_run_config() -> None:
        try:
            summary = await asyncio.to_thread(
                services.load_run_config_summary,
                state.analysis.analysis_selected_run_dir,
            )
        except (OSError, ValueError) as exc:
            config_status_label.set_text(f"Config load error: {exc}")
            config_table.rows = []
            config_table.update()
            return
        config_status_label.set_text(str(summary.get("status") or ""))
        config_table.rows = list(summary.get("rows") or [])
        config_table.update()

    async def refresh_analysis() -> None:
        await refresh_selected_run_config()
        try:
            run_dir = state.analysis.analysis_selected_run_dir
            summary, body = await asyncio.to_thread(services.build_analysis, run_dir)
            mo_summary = await asyncio.to_thread(_build_mo_analysis_text, run_dir)
            mo_objectives = await asyncio.to_thread(_load_mo_objective_options, run_dir)
            final_test_analysis = await asyncio.to_thread(_build_final_test_analysis_text, run_dir)
            ga_convergence = await asyncio.to_thread(_build_ga_convergence_options, run_dir)
            mutation_weights = await asyncio.to_thread(_build_mutation_weight_options, run_dir)
            state.analysis.mo_objective_options = mo_objectives
            await refresh_mo_section()
        except (OSError, ValueError) as exc:
            summary, body = "Analysis load error", str(exc)
            mo_summary = str(exc)
            mo_objectives = {}
            final_test_analysis = str(exc)
            ga_convergence = None
            mutation_weights = None
            state.analysis.mo_objective_options = mo_objectives
            _set_mo_hidden(str(exc))
        state.analysis.summary = summary
        state.analysis.body = body
        state.analysis.mo_objective_options = mo_objectives
        _render_ga_convergence(ga_chart_container, ga_convergence)
        _render_mutation_weight_history(mutation_weight_container, mutation_weights)
        mo_summary_text.value = mo_summary
        mo_summary_text.update()
        final_test_text.value = final_test_analysis
        final_test_text.update()
        summary_label.set_text(summary)
        body_text.value = body
        body_text.update()

    async def refresh_timing() -> None:
        try:
            run_dir = state.analysis.analysis_selected_run_dir
            summary, rows, body = await asyncio.to_thread(services.build_timing, run_dir)
            time_analysis = await asyncio.to_thread(_build_time_analysis_text, run_dir)
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
        run_dir = state.analysis.analysis_selected_run_dir
        if run_dir is None:
            _set_mo_hidden("No run selected.")
            return

        try:
            if force_generate:
                if mo_generate_button is not None:
                    mo_generate_button.disable()
                _ensure_mo_axis_selection()
                result = await asyncio.to_thread(
                    services.run_analysis_subprocess,
                    run_dir,
                    _mo_output_dir(run_dir),
                    "evolution",
                    extra_args=_mo_axis_args(),
                )
                if not result.get("ok"):
                    _set_mo_error(str(result.get("error") or result.get("stderr") or "Analysis subprocess failed."))
                    return
                output_files = result.get("output_files") if isinstance(result.get("output_files"), dict) else {}
                if not output_files.get("generation_animation_gif") and not output_files.get("generation_scatter_figures"):
                    mo_summary = await asyncio.to_thread(_build_mo_analysis_text, run_dir)
                    _set_mo_hidden(mo_summary)
                    return
                artifact_data = _artifact_data_from_output_files(output_files)
            else:
                mo_summary = await asyncio.to_thread(_build_mo_analysis_text, run_dir)
                if mo_summary == "No multi-objective data found.":
                    _set_mo_hidden(mo_summary)
                    return
                artifact_data = _discover_mo_artifacts(run_dir)

            state.analysis.mo_visible = True
            state.analysis.mo_summary = await asyncio.to_thread(_build_mo_analysis_text, run_dir)
            state.analysis.mo_animation_path = str(artifact_data.get("animation_path") or "")
            state.analysis.mo_generation_choices = list(artifact_data.get("generation_choices") or [])
            state.analysis.mo_static_plot_paths = dict(artifact_data.get("static_plot_paths") or {})
            _ensure_mo_axis_selection()
            if state.analysis.mo_selected_generation not in state.analysis.mo_generation_choices:
                state.analysis.mo_selected_generation = (
                    state.analysis.mo_generation_choices[-1] if state.analysis.mo_generation_choices else ""
                )
            mo_section.visible = True
            mo_summary_text.value = state.analysis.mo_summary
            mo_summary_text.update()
            _refresh_mo_options()
            _render_mo_artifacts()
        except (OSError, ValueError) as exc:
            _set_mo_error(str(exc))
        finally:
            if mo_generate_button is not None:
                mo_generate_button.enable()

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

    def _set_mo_error(message: str) -> None:
        state.analysis.mo_visible = True
        state.analysis.mo_summary = message
        state.analysis.mo_animation_path = ""
        state.analysis.mo_generation_choices = []
        state.analysis.mo_selected_generation = ""
        state.analysis.mo_static_plot_paths = {}
        mo_section.visible = True
        mo_summary_text.value = message
        mo_summary_text.update()
        _refresh_mo_options()
        _render_mo_artifacts()

    def _refresh_mo_options() -> None:
        _ensure_mo_axis_selection()
        generation_select.options = list(state.analysis.mo_generation_choices)
        if state.analysis.mo_selected_generation not in state.analysis.mo_generation_choices:
            state.analysis.mo_selected_generation = (
                state.analysis.mo_generation_choices[-1] if state.analysis.mo_generation_choices else ""
            )
        generation_select.value = state.analysis.mo_selected_generation or None
        generation_select.update()
        x_axis_select.options = dict(state.analysis.mo_objective_options)
        x_axis_select.value = state.analysis.mo_selected_x_objective or None
        x_axis_select.update()
        y_axis_select.options = dict(state.analysis.mo_objective_options)
        y_axis_select.value = state.analysis.mo_selected_y_objective or None
        y_axis_select.update()

    def _ensure_mo_axis_selection() -> None:
        keys = list(state.analysis.mo_objective_options)
        if not keys:
            state.analysis.mo_selected_x_objective = ""
            state.analysis.mo_selected_y_objective = ""
            return
        if state.analysis.mo_selected_x_objective not in state.analysis.mo_objective_options:
            state.analysis.mo_selected_x_objective = keys[0]
        if state.analysis.mo_selected_y_objective not in state.analysis.mo_objective_options:
            state.analysis.mo_selected_y_objective = keys[1] if len(keys) > 1 else keys[0]

    def _mo_axis_args() -> list[str]:
        args: list[str] = []
        if state.analysis.mo_selected_x_objective:
            args.extend(["--x-objective", state.analysis.mo_selected_x_objective])
        if state.analysis.mo_selected_y_objective:
            args.extend(["--y-objective", state.analysis.mo_selected_y_objective])
        return args

    def _mo_output_dir(run_dir: Path) -> Path:
        if not state.analysis.mo_selected_x_objective or not state.analysis.mo_selected_y_objective:
            return run_dir / "analysis" / "evolution"
        return (
            run_dir
            / "analysis"
            / "evolution"
            / "objective_axes"
            / _axis_pair_slug(state.analysis.mo_selected_x_objective, state.analysis.mo_selected_y_objective)
        )

    def _render_mo_artifacts() -> None:
        animation_container.clear()
        static_plot_container.clear()

        animation_path = state.analysis.mo_animation_path
        if animation_path and Path(animation_path).exists():
            with animation_container:
                ui.label("Pareto animation").classes(SECTION_HEADER_CLASS)
                ui.image(animation_path).props(_artifact_image_props(animation_path)).classes("w-full max-w-5xl")
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
                ui.image(static_plot_path).props(_artifact_image_props(static_plot_path)).classes("w-full max-w-5xl")
        elif state.analysis.mo_visible:
            with static_plot_container:
                ui.label("Static Pareto front").classes(SECTION_HEADER_CLASS)
                ui.label("No static Pareto front generated for the selected generation.")

    def _discover_mo_artifacts(run_dir: Path) -> dict[str, Any]:
        analysis_dir = _mo_output_dir(run_dir)
        if not (analysis_dir / "generation_fitness").exists():
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

    def _artifact_data_from_output_files(output_files: dict[str, Any]) -> dict[str, Any]:
        """Convert CLI output files into the MO section artifact model."""
        animation_path = str(output_files.get("generation_animation_gif") or "")
        static_plot_paths: dict[str, str] = {}
        generation_choices: list[str] = []
        for path_text in output_files.get("generation_scatter_figures") or []:
            path = Path(str(path_text))
            generation = _extract_mo_generation(path)
            if generation is None:
                continue
            generation_text = str(generation)
            generation_choices.append(generation_text)
            static_plot_paths[generation_text] = str(path)
        return {
            "animation_path": animation_path,
            "generation_choices": generation_choices,
            "static_plot_paths": static_plot_paths,
        }

    def on_mo_generation_changed(event: Any) -> None:
        state.analysis.mo_selected_generation = str(event.value or "")
        _render_mo_artifacts()

    def on_mo_x_axis_changed(event: Any) -> None:
        state.analysis.mo_selected_x_objective = str(event.value or "")
        _clear_mo_artifact_display()

    def on_mo_y_axis_changed(event: Any) -> None:
        state.analysis.mo_selected_y_objective = str(event.value or "")
        _clear_mo_artifact_display()

    def _clear_mo_artifact_display() -> None:
        state.analysis.mo_animation_path = ""
        state.analysis.mo_static_plot_paths = {}
        _render_mo_artifacts()

    def on_run_changed(event: Any) -> None:
        state.analysis.analysis_selected_run_dir = Path(str(event.value)) if event.value else None
        state.analysis.analysis_run_selected_manually = True
        selected_label.set_text(f"Selected folder: {state.analysis.analysis_selected_run_dir or '(none)'}")
        asyncio.create_task(refresh_all())

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Analysis").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            run_select = create_run_selector(
                value=state.analysis.analysis_selected_run_dir,
                on_change=on_run_changed,
            ).classes(f"{INPUT_CLASS} w-full")
            ui.button("Refresh runs", on_click=safe_click(refresh_runs, label="Refresh analysis runs")).classes(
                BUTTON_CLASS
            )
        selected_label = ui.label("Selected folder: (none)")
        ui.label("Selected Run Config").classes(SECTION_HEADER_CLASS)
        config_status_label = ui.label("No run selected")
        config_table = ui.table(
            columns=[
                {"name": "field", "label": "Field", "field": "field", "align": "left"},
                {"name": "value", "label": "Value", "field": "value", "align": "left"},
            ],
            rows=[],
        ).props("hide-pagination dense flat").classes(f"{TABLE_CLASS} w-full")
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            summary_label = ui.label(state.analysis.summary)
            ui.button("Refresh analysis", on_click=safe_click(refresh_all, label="Refresh analysis")).classes(BUTTON_CLASS)
        with ui.tabs().classes(f"{CARD_CLASS} w-full") as analysis_tabs:
            early_end_analysis_tab = ui.tab("Early End Analysis").classes(TAB_CLASS)
            real_eval_analysis_tab = ui.tab("Real Eval Analysis").classes(TAB_CLASS)
            final_test_analysis_tab = ui.tab("Final Test Analysis").classes(TAB_CLASS)

        with ui.tab_panels(analysis_tabs, value=real_eval_analysis_tab).classes(f"{PAGE_CLASS} w-full"):
            with ui.tab_panel(early_end_analysis_tab).classes(f"{PAGE_CLASS} w-full"):
                ui.label("Early End Analysis").classes(SECTION_HEADER_CLASS)
                ui.label("Early End analysis will be added here.")

            with ui.tab_panel(real_eval_analysis_tab).classes(f"{PAGE_CLASS} w-full"):
                body_text = ui.textarea(value=state.analysis.body).props("readonly").classes(
                    f"{TEXTAREA_CLASS} {height_class(300)} w-full"
                )
                ga_chart_container = ui.column().classes("w-full gap-3")
                mutation_weight_container = ui.column().classes("w-full gap-3")

                with ui.column().classes("w-full gap-3") as mo_section:
                    ui.label("MO Analysis").classes(SECTION_HEADER_CLASS)
                    with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
                        mo_generate_button = ui.button(
                            "Generate MO Analysis",
                            on_click=safe_click(
                                lambda: refresh_mo_section(force_generate=True),
                                label="Generate MO Analysis",
                            ),
                        ).classes(BUTTON_CLASS)
                        generation_select = ui.select([], label="Generation", on_change=on_mo_generation_changed).classes(
                            f"{INPUT_CLASS} w-64"
                        )
                        x_axis_select = ui.select({}, label="X axis", on_change=on_mo_x_axis_changed).classes(
                            f"{INPUT_CLASS} w-64"
                        )
                        y_axis_select = ui.select({}, label="Y axis", on_change=on_mo_y_axis_changed).classes(
                            f"{INPUT_CLASS} w-64"
                        )
                    mo_summary_text = ui.textarea(value=state.analysis.mo_summary).props("readonly").classes(
                        f"{TEXTAREA_CLASS} {height_class(220)} w-full"
                    )
                    animation_container = ui.column().classes("w-full gap-3")
                    static_plot_container = ui.column().classes("w-full gap-3")

                ui.label("Time Analysis").classes(SECTION_HEADER_CLASS)
                time_analysis_text = ui.textarea(value="No timing data found.").props("readonly").classes(
                    f"{TEXTAREA_CLASS} {height_class(150)} w-full"
                )
                with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
                    timing_summary_label = ui.label(state.analysis.timing_summary)
                    ui.button("Refresh timing", on_click=safe_click(refresh_timing, label="Refresh timing")).classes(
                        BUTTON_CLASS
                    )
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

            with ui.tab_panel(final_test_analysis_tab).classes(f"{PAGE_CLASS} w-full"):
                ui.label("Final Test Analysis").classes(SECTION_HEADER_CLASS)
                final_test_text = ui.textarea(value="No final test data found.").props("readonly").classes(
                    f"{TEXTAREA_CLASS} {height_class(170)} w-full"
                )

    mo_section.visible = False
    _refresh_mo_options()
    _render_mo_artifacts()

    controls["refresh_analysis"] = refresh_all
    controls["refresh_runs"] = refresh_runs
    controls["refresh_run_config"] = refresh_selected_run_config
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
        objective_specs = load_run_objective_specs(run_dir, dimension=_fitness_dimension_from_text(log_text))
        analysis = parse_mo_analysis(log_text, objective_specs=objective_specs)
        if not analysis:
            return "No multi-objective data found."
        lines = [
            f"Pareto front count: {analysis.get('pareto_front_count', 0)}",
        ]
        if analysis.get("objective_names"):
            labels = {
                str(spec.get("name")): str(spec.get("axis_label"))
                for spec in list(analysis.get("objective_specs", []))
                if isinstance(spec, dict)
            }
            lines.append(
                "Objectives: "
                + ", ".join(labels.get(str(name), str(name)) for name in analysis["objective_names"])
            )
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


def _artifact_image_props(path_text: str) -> str:
    """Return image props that force remounting after an artifact is overwritten."""
    path = Path(path_text)
    try:
        cache_key = f"{path.name}-{path.stat().st_mtime_ns}"
    except OSError:
        cache_key = path.name
    return f'key="{cache_key}"'


def _axis_pair_slug(x_objective: str, y_objective: str) -> str:
    """Return a filesystem-safe slug for one selected objective pair."""
    return f"{_axis_slug(x_objective)}__{_axis_slug(y_objective)}"


def _axis_slug(value: str) -> str:
    """Return a compact filesystem-safe objective slug."""
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip()).strip("_")
    return slug or "objective"


def _load_mo_objective_options(run_dir: Path | None) -> dict[str, str]:
    """Return configured MO objective select options for the selected run."""
    if run_dir is None:
        return {}
    log_text = _read_mo_analysis_text(run_dir)
    specs = load_run_objective_specs(run_dir, dimension=_fitness_dimension_from_text(log_text))
    return {spec.name: spec.axis_label for spec in specs}


def _fitness_dimension_from_text(text: str) -> int:
    """Return the widest fitness vector seen in MO logs."""
    dimension = 0
    for match in re.finditer(r"fitness\s*(?:=|:)\s*[\[(]([^\])]+)[\])]", text, flags=re.IGNORECASE):
        parts = [part.strip() for part in match.group(1).split(",") if part.strip()]
        dimension = max(dimension, len(parts))
    return dimension


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


def _render_mutation_weight_history(container: Any, options: dict[str, Any] | None) -> None:
    """Render mutation AOS weight history only when the selected run used AOS."""
    container.clear()
    if not options:
        return
    with container:
        ui.label("Mutation Operator Weights").classes(SECTION_HEADER_CLASS)
        ui.echart(options).classes("w-full h-80")


def _build_mutation_weight_options(run_dir: Path | None) -> dict[str, Any] | None:
    """Build ECharts options for mutation AOS weight history."""
    with services.LoggedOperation("parsing logs", kind="mutation_weight_history", run_dir=run_dir):
        if run_dir is None:
            return None
        config_path = run_dir / "config.json"
        if not config_path.exists():
            return None
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if str(config.get("mutation_selection_mode", "fixed")).strip().lower() != "aos":
            return None
        rows = _load_mutation_weight_history(run_dir / "mutation_weights.jsonl")
        if not rows:
            return None

        generations = [row["generation"] for row in rows]
        operators = sorted({operator for row in rows for operator in row["mutation_weights"]})
        if not operators:
            return None
        palette = [
            COLORS["sky_blue"],
            COLORS["bronze"],
            COLORS["success"],
            COLORS["error"],
            COLORS["text"],
        ]
        series = []
        for index, operator in enumerate(operators):
            series.append(
                {
                    "name": operator,
                    "type": "line",
                    "smooth": True,
                    "data": [row["mutation_weights"].get(operator) for row in rows],
                    "lineStyle": {"width": 2, "color": palette[index % len(palette)]},
                    "itemStyle": {"color": palette[index % len(palette)]},
                }
            )
        return {
            "backgroundColor": "transparent",
            "color": palette,
            "tooltip": {"trigger": "axis"},
            "legend": {"textStyle": {"color": COLORS["text"]}},
            "grid": {"left": 48, "right": 24, "top": 56, "bottom": 44},
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
                "name": "weight",
                "axisLine": {"lineStyle": {"color": COLORS["border"]}},
                "axisLabel": {"color": COLORS["muted"]},
                "splitLine": {"lineStyle": {"color": COLORS["border"]}},
                "nameTextStyle": {"color": COLORS["muted"]},
            },
            "series": series,
        }


def _load_mutation_weight_history(path: Path) -> list[dict[str, Any]]:
    """Load mutation AOS weights from a JSONL run artifact."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        weights = payload.get("mutation_weights") if isinstance(payload, dict) else None
        if not isinstance(weights, dict):
            continue
        try:
            generation = int(payload.get("generation"))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "generation": generation,
                "mutation_weights": {
                    str(key): float(value)
                    for key, value in weights.items()
                    if _is_number(value)
                },
            }
        )
    return rows
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
        lines.append("Fitness/objectives used by EA:")
        for key, label in (
            ("mean_fitness_win_score", "Mean win_score"),
            ("mean_fitness_resource_advantage", "Mean resource_advantage"),
        ):
            if analysis.get(key) is not None:
                lines.append(f"{label}: {_format_float(analysis[key])}")
        lines.append("Raw MicroRTS metrics:")
        for key, label in (
            ("mean_raw_p0_units", "Mean p0_units"),
            ("mean_raw_p1_units", "Mean p1_units"),
            ("mean_raw_p0_eval", "Mean p0_eval"),
            ("mean_raw_p1_eval", "Mean p1_eval"),
            ("mean_raw_resource_total", "Mean resource_total delta"),
            ("mean_raw_material_total", "Mean material_total delta"),
        ):
            if analysis.get(key) is not None:
                lines.append(f"{label}: {_format_float(analysis[key])}")
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
        latest_results = services.latest_final_test_results_path(run_dir)
        if latest_results is not None and latest_results.exists():
            parts.append(latest_results.read_text(encoding="utf-8", errors="replace"))
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


def _is_number(value: object) -> bool:
    """Return whether a value can be rendered as a chart number."""
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
def _format_seconds(value: object) -> str:
    """Format seconds for the compact time-analysis panel."""
    return f"{float(value):.3f} sec"
