"""Final-test batch replay view for existing EAGLE runs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.components.selectors import (
    create_aggregation_selector,
    create_map_selector,
    create_metric_selector,
    create_opponent_selector,
    create_run_selector,
)
from eagle_gui_web.theme import (
    BADGE_CLASS,
    BUTTON_CLASS,
    CARD_CLASS,
    INPUT_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TEXTAREA_CLASS,
    button_class,
    height_class,
)
from eagle_gui_web.ui_actions import safe_click


REPEAT_COUNT = 10


def build_final_test_view(state: Any) -> dict[str, Any]:
    """Build the final-test controls, results summary, and analysis panel."""
    controls: dict[str, Any] = {}
    run_button: Any | None = None
    analysis_button: Any | None = None

    async def run_final_test() -> tuple[bool, str]:
        if run_button is not None:
            run_button.disable()
        state.final_test.status_text = "running"
        status_badge.set_text(state.final_test.status_text)
        status_badge.classes(replace=BADGE_CLASS)
        try:
            success, message = await asyncio.to_thread(services.start_final_test, state)
        finally:
            if run_button is not None:
                run_button.enable()
        await refresh_results()
        await refresh_analysis()
        await refresh_status()
        return success, message

    async def stop() -> None:
        message = await asyncio.to_thread(services.stop_experiment, state)
        ui.notify(message)
        await refresh_status()

    async def refresh_runs() -> None:
        runs = await asyncio.to_thread(services.run_choices)
        run_select.options = runs
        if state.final_test.selected_run_dir is None and runs:
            state.final_test.selected_run_dir = Path(runs[0])
            run_select.value = runs[0]
        elif state.final_test.selected_run_dir is not None and str(state.final_test.selected_run_dir) not in runs:
            state.final_test.selected_run_dir = Path(runs[0]) if runs else None
            run_select.value = str(state.final_test.selected_run_dir) if state.final_test.selected_run_dir else None
        run_select.update()
        selected_label.set_text(f"Selected folder: {state.final_test.selected_run_dir or '(none)'}")

    async def refresh_status() -> None:
        status_badge.set_text(state.final_test.status_text)
        status_badge.classes(replace=BADGE_CLASS)

    async def refresh_results() -> None:
        run_dir = state.final_test.selected_run_dir
        try:
            state.final_test.analysis_text = await asyncio.to_thread(services.build_final_test_results_text, run_dir)
            results_textarea.value = state.final_test.analysis_text
            results_textarea.update()
            results_path = await asyncio.to_thread(services.latest_final_test_results_path, run_dir)
            state.final_test.analysis_output_path = str(results_path) if results_path is not None else ""
            results_path_label.set_text(
                f"Latest results: {state.final_test.analysis_output_path or '(none)'}"
            )
        except (OSError, ValueError) as exc:
            state.final_test.analysis_text = str(exc)
            results_textarea.value = state.final_test.analysis_text
            results_textarea.update()
            results_path_label.set_text(f"Latest results: {exc}")
        await refresh_individuals()

    async def refresh_analysis() -> None:
        run_dir = state.final_test.selected_run_dir
        results_dir = await asyncio.to_thread(services.latest_final_test_results_dir, run_dir)
        if results_dir is None:
            _set_analysis_hidden("No final test results found.")
            return

        extra_args = _analysis_cli_args()
        if analysis_button is not None:
            analysis_button.disable()
        try:
            result = await asyncio.to_thread(
                services.run_analysis_subprocess,
                results_dir,
                results_dir / "analysis",
                "final_test",
                extra_args,
            )
        finally:
            if analysis_button is not None:
                analysis_button.enable()

        if not result.get("ok"):
            _set_analysis_error(str(result.get("error") or result.get("stderr") or "Analysis failed."))
            return

        output_files = dict(result.get("output_files") or {})
        summary_text = str(output_files.get("analysis_summary_json") or "")
        heatmap_text = str(output_files.get("metric_heatmap") or "")
        summary_path = Path(summary_text) if summary_text else None
        heatmap_path = Path(heatmap_text) if heatmap_text else None
        if summary_path is not None and summary_path.exists():
            try:
                summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                _set_analysis_error(str(exc))
                return
            analysis_textarea.value = "\n".join(str(line) for line in summary_payload.get("text_lines", [])) or "No analysis summary."
            analysis_textarea.update()
            state.final_test.analysis_output_path = str(summary_path)
            analysis_output_label.set_text(f"Analysis: {summary_path}")
        else:
            analysis_textarea.value = "No analysis summary generated."
            analysis_textarea.update()
            analysis_output_label.set_text("Analysis: (none)")
        _render_analysis_plot(heatmap_path if heatmap_path is not None and heatmap_path.exists() else None)

    async def refresh_all() -> None:
        await refresh_results()
        await refresh_analysis()

    async def refresh_individuals() -> None:
        individual_ids = await asyncio.to_thread(
            services.final_test_individual_choices,
            state.final_test.selected_run_dir,
        )
        if len(individual_ids) > 1:
            individual_options = {"all": "All individuals", **{item: f"Individual {item}" for item in individual_ids}}
            if state.final_test.analysis_individual not in individual_options:
                state.final_test.analysis_individual = "all"
            individual_select.options = individual_options
            individual_select.value = state.final_test.analysis_individual
            individual_select.visible = True
            individual_select.enable()
        elif len(individual_ids) == 1:
            state.final_test.analysis_individual = individual_ids[0]
            individual_select.options = {individual_ids[0]: f"Individual {individual_ids[0]}"}
            individual_select.value = individual_ids[0]
            individual_select.visible = False
            individual_select.disable()
        else:
            state.final_test.analysis_individual = "all"
            individual_select.options = {"all": "All individuals"}
            individual_select.value = "all"
            individual_select.visible = False
            individual_select.disable()
        individual_select.update()

    def _set_analysis_hidden(message: str) -> None:
        analysis_textarea.value = message
        analysis_textarea.update()
        analysis_output_label.set_text("Analysis: (none)")
        analysis_plot_container.clear()
        with analysis_plot_container:
            ui.label(message)

    def _set_analysis_error(message: str) -> None:
        analysis_textarea.value = message
        analysis_textarea.update()
        analysis_output_label.set_text(f"Analysis error: {message}")
        analysis_plot_container.clear()
        with analysis_plot_container:
            ui.label(message)

    def _render_analysis_plot(plot_path: Path | None) -> None:
        analysis_plot_container.clear()
        with analysis_plot_container:
            ui.label("Final Test Analysis Plot").classes(SECTION_HEADER_CLASS)
            if plot_path is not None and plot_path.exists():
                ui.image(str(plot_path)).classes("w-full max-w-5xl")
            else:
                ui.label("No analysis plot generated yet.")

    def _analysis_cli_args() -> list[str]:
        return [
            "--metric",
            state.final_test.analysis_metric,
            "--aggregation",
            state.final_test.analysis_aggregation,
            "--weight-resources",
            state.final_test.weight_resources,
            "--weight-base",
            state.final_test.weight_base,
            "--weight-barracks",
            state.final_test.weight_barracks,
            "--weight-worker",
            state.final_test.weight_worker,
            "--weight-light",
            state.final_test.weight_light,
            "--weight-heavy",
            state.final_test.weight_heavy,
            "--weight-ranged",
            state.final_test.weight_ranged,
            "--individual",
            state.final_test.analysis_individual,
        ]

    def on_run_changed(event: Any) -> None:
        state.final_test.selected_run_dir = Path(str(event.value)) if event.value else None
        selected_label.set_text(f"Selected folder: {state.final_test.selected_run_dir or '(none)'}")
        asyncio.create_task(refresh_all())

    def on_map_changed(event: Any) -> None:
        state.final_test.map = str(event.value or "all")

    def on_opponent_changed(event: Any) -> None:
        state.final_test.opponent = str(event.value or "all")

    def on_metric_changed(event: Any) -> None:
        state.final_test.analysis_metric = str(event.value or "win_rate")
        asyncio.create_task(refresh_analysis())

    def on_aggregation_changed(event: Any) -> None:
        state.final_test.analysis_aggregation = str(event.value or "mean")
        asyncio.create_task(refresh_analysis())

    def on_individual_changed(event: Any) -> None:
        state.final_test.analysis_individual = str(event.value or "all")
        asyncio.create_task(refresh_analysis())

    def on_weight_changed(field_name: str):
        def _handler(event: Any) -> None:
            setattr(state.final_test, field_name, str(event.value or "0"))
            asyncio.create_task(refresh_analysis())

        return _handler

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Final Test").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            run_button = ui.button(
                "Run final test",
                on_click=safe_click(run_final_test, label="Run final test", notify_result=True),
            ).classes(button_class(success=True))
            ui.button("Stop Experiment", on_click=safe_click(stop, label="Stop Experiment")).classes(
                button_class(danger=True)
            )
            ui.button("Refresh runs", on_click=safe_click(refresh_runs, label="Refresh runs")).classes(BUTTON_CLASS)
            ui.button("Refresh results", on_click=safe_click(refresh_results, label="Refresh results")).classes(
                BUTTON_CLASS
            )
            status_badge = ui.badge(state.final_test.status_text).classes(BADGE_CLASS)

        run_select = create_run_selector(
            value=state.final_test.selected_run_dir,
            on_change=on_run_changed,
        ).classes(f"{INPUT_CLASS} w-full")
        selected_label = ui.label("Selected folder: (none)")

        with ui.row().classes(f"{ROW_CLASS} gap-4"):
            create_map_selector(
                label="Map folder",
                value=state.final_test.map,
                on_change=on_map_changed,
                include_all=True,
            ).classes(f"{INPUT_CLASS} w-48")
            create_opponent_selector(
                value=state.final_test.opponent,
                on_change=on_opponent_changed,
                include_all=True,
            ).classes(f"{INPUT_CLASS} w-56")
            ui.label(f"Repeats: {REPEAT_COUNT}")

        ui.label("Final Test Results").classes(SECTION_HEADER_CLASS)
        results_path_label = ui.label("Latest results: (none)")
        results_textarea = ui.textarea(value=state.final_test.analysis_text).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(220)} w-full"
        )

        ui.label("Final Test Analysis").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} gap-4"):
            create_metric_selector(
                value=state.final_test.analysis_metric,
                on_change=on_metric_changed,
            ).classes(f"{INPUT_CLASS} w-56")
            create_aggregation_selector(
                value=state.final_test.analysis_aggregation,
                on_change=on_aggregation_changed,
            ).classes(f"{INPUT_CLASS} w-40")
            individual_select = ui.select(
                {"all": "All individuals"},
                label="Individual",
                value=state.final_test.analysis_individual,
                on_change=on_individual_changed,
            ).classes(f"{INPUT_CLASS} w-56")
            analysis_button = ui.button("Refresh analysis", on_click=safe_click(refresh_analysis, label="Refresh analysis")).classes(
                BUTTON_CLASS
            )
            analysis_output_label = ui.label("Analysis: (none)")
        with ui.row().classes(f"{ROW_CLASS} gap-4"):
            ui.input(
                "Resources weight",
                value=state.final_test.weight_resources,
                on_change=on_weight_changed("weight_resources"),
            ).classes(f"{INPUT_CLASS} w-36")
            ui.input(
                "Base weight",
                value=state.final_test.weight_base,
                on_change=on_weight_changed("weight_base"),
            ).classes(f"{INPUT_CLASS} w-36")
            ui.input(
                "Barracks weight",
                value=state.final_test.weight_barracks,
                on_change=on_weight_changed("weight_barracks"),
            ).classes(f"{INPUT_CLASS} w-36")
            ui.input(
                "Worker weight",
                value=state.final_test.weight_worker,
                on_change=on_weight_changed("weight_worker"),
            ).classes(f"{INPUT_CLASS} w-36")
        with ui.row().classes(f"{ROW_CLASS} gap-4"):
            ui.input(
                "Light weight",
                value=state.final_test.weight_light,
                on_change=on_weight_changed("weight_light"),
            ).classes(f"{INPUT_CLASS} w-36")
            ui.input(
                "Heavy weight",
                value=state.final_test.weight_heavy,
                on_change=on_weight_changed("weight_heavy"),
            ).classes(f"{INPUT_CLASS} w-36")
            ui.input(
                "Ranged weight",
                value=state.final_test.weight_ranged,
                on_change=on_weight_changed("weight_ranged"),
            ).classes(f"{INPUT_CLASS} w-36")
        analysis_textarea = ui.textarea(value="No final test analysis available.").props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(220)} w-full"
        )
        analysis_plot_container = ui.column().classes("w-full gap-3")

    _render_analysis_plot(None)

    controls.update(
        {
            "refresh_runs": refresh_runs,
            "refresh_status": refresh_status,
            "refresh_results": refresh_results,
            "refresh_analysis": refresh_analysis,
            "refresh_all": refresh_all,
        }
    )
    return controls
