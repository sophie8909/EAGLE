"""Experiment run control view."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_ui import services
from eagle_ui.components.selectors import create_run_selector
from eagle_ui.state import EARLY_END_FITNESS_METRIC, EARLY_END_LLM_CALL_LIMIT
from eagle_ui.theme import (
    BADGE_CLASS,
    BUTTON_CLASS,
    CARD_CLASS,
    INPUT_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TEXTAREA_CLASS,
    button_class,
    height_class,
    status_badge_class,
)
from eagle_ui.ui_actions import safe_click


def build_run_view(state: Any, *, log_height: int = 560) -> dict[str, Any]:
    """Build the run process controls and log view."""
    controls: dict[str, Any] = {}

    async def start() -> None:
        try:
            success, message = await asyncio.to_thread(services.start_experiment, state)
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(message, type="positive" if success else "warning")
        await asyncio.sleep(0.2)
        await refresh_status()
        await refresh_runs()
        analysis_refresh = getattr(state.runtime, "analysis_runs_refresh", None)
        if callable(analysis_refresh):
            await analysis_refresh(state.run.experiment_current_run_dir)
        await refresh_log()

    async def stop() -> None:
        message = await asyncio.to_thread(services.stop_experiment, state)
        ui.notify(message)
        await refresh_status()

    async def refresh_runs() -> None:
        runs = await asyncio.to_thread(services.run_choices)
        selected_run = state.run.experiment_current_run_dir
        run_select.options = [""] + ([str(selected_run)] if selected_run is not None and str(selected_run) not in runs else []) + runs

        if selected_run is None:
            run_select.value = ""
        else:
            run_select.value = str(selected_run)

        run_select.update()
        refresh_start_button()

    async def refresh_status() -> None:
        state.run.status_text = await asyncio.to_thread(services.process_status_text, state)
        status_badge.set_text(state.run.status_text)
        status_badge.classes(replace=status_badge_class(state.run.status_text))
        refresh_run_config_panel()

    async def refresh_log() -> None:
        await refresh_status()
        state.run.log_text = await asyncio.to_thread(services.read_log_tail)
        log_textarea.value = state.run.log_text
        log_textarea.update()

    def refresh_start_button() -> None:
        """Update the start button label based on whether a run is selected."""
        if state.run.experiment_current_run_dir is None:
            start_button.set_text("Start experiment")
        else:
            start_button.set_text("Resume experiment")

    def on_run_changed(event: Any) -> None:
        state.run.experiment_current_run_dir = Path(str(event.value)) if event.value else None
        refresh_start_button()

    def refresh_run_config_panel() -> None:
        eval_mode = services.normalize_eval_mode(state.config.eval_mode)
        eval_mode_value.set_text(services.EVALUATION_MODE_CHOICES.get(eval_mode, eval_mode))
        fitness_value.set_text(EARLY_END_FITNESS_METRIC if eval_mode == "early_end" else state.config.fitness_metric)
        llm_call_limit_value.set_text(
            EARLY_END_LLM_CALL_LIMIT if eval_mode == "early_end" else state.config.llm_call_limit
        )
        early_end_badge.visible = eval_mode == "early_end"

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Run Control").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            start_button = ui.button(
                "Start experiment",
                on_click=safe_click(start, label="Start experiment"),
            ).classes(button_class(success=True))
            ui.button("Stop Experiment", on_click=safe_click(stop, label="Stop Experiment")).classes(
                button_class(danger=True)
            )
            ui.button(
                "Refresh runs",
                on_click=safe_click(refresh_runs, label="Refresh runs"),
            ).classes(BUTTON_CLASS)
            ui.button("Refresh log", on_click=safe_click(refresh_log, label="Refresh log")).classes(BUTTON_CLASS)
            status_badge = ui.badge(state.run.status_text).classes(BADGE_CLASS)
        with ui.row().classes(f"{ROW_CLASS} gap-6"):
            ui.checkbox(
                "Quick run",
                value=state.run.quick_run,
                on_change=lambda event: setattr(state.run, "quick_run", bool(event.value)),
            )
            ui.checkbox(
                "Skip final test",
                value=state.run.skip_final_test,
                on_change=lambda event: setattr(state.run, "skip_final_test", event.value is True),
            )
            ui.checkbox(
                "Precompile Python",
                value=state.run.precompile_python,
                on_change=lambda event: setattr(state.run, "precompile_python", bool(event.value)),
            )
        run_select = create_run_selector(
            value=state.run.experiment_current_run_dir,
            on_change=on_run_changed,
        ).classes(f"{INPUT_CLASS} w-full")
        with ui.column().classes("w-full gap-2 rounded border border-[#2d4059] p-3"):
            with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
                ui.label("Running experiment").classes(SECTION_HEADER_CLASS)
                early_end_badge = ui.badge("EARLY END").classes("uppercase")
            with ui.grid(columns=3).classes("w-full gap-3"):
                eval_mode_value = _status_field("Eval Mode")
                fitness_value = _status_field("Fitness Metric")
                llm_call_limit_value = _status_field("LLM Call Limit")
        log_textarea = ui.textarea(value=state.run.log_text).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(log_height)} w-full"
        )

    refresh_run_config_panel()
    controls.update({"refresh_runs": refresh_runs, "refresh_status": refresh_status, "refresh_log": refresh_log})
    return controls


def _status_field(label: str) -> Any:
    with ui.column().classes("gap-1"):
        ui.label(label).classes("text-xs uppercase tracking-widest text-[#b08d57]")
        return ui.label().classes("font-mono")
