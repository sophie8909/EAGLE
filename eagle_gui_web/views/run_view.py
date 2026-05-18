"""Experiment run control view."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_gui_web import services
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
    status_badge_class,
)
from eagle_gui_web.ui_actions import safe_click


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
        await refresh_runs(select_latest=True)
        await refresh_log()

    async def stop() -> None:
        message = await asyncio.to_thread(services.stop_experiment, state)
        ui.notify(message)
        await refresh_status()

    async def refresh_runs(select_latest: bool = False) -> None:
        runs = await asyncio.to_thread(services.run_choices)
        run_select.options = runs

        if select_latest and runs:
            state.run.current_run_dir = Path(runs[0])
            run_select.value = runs[0]
        elif state.run.current_run_dir is None and runs:
            state.run.current_run_dir = Path(runs[0])
            run_select.value = runs[0]
        elif state.run.current_run_dir is not None and str(state.run.current_run_dir) not in runs:
            state.run.current_run_dir = Path(runs[0]) if runs else None
            run_select.value = str(state.run.current_run_dir) if state.run.current_run_dir else None

        run_select.update()

    async def refresh_status() -> None:
        state.run.status_text = await asyncio.to_thread(services.process_status_text)
        status_badge.set_text(state.run.status_text)
        status_badge.classes(replace=status_badge_class(state.run.status_text))

    async def refresh_log() -> None:
        await refresh_status()
        state.run.log_text = await asyncio.to_thread(services.read_log_tail)
        log_textarea.value = state.run.log_text
        log_textarea.update()

    def on_run_changed(event: Any) -> None:
        state.run.current_run_dir = Path(str(event.value)) if event.value else None

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Run Control").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            ui.button("Start experiment", on_click=safe_click(start, label="Start experiment")).classes(
                button_class(success=True)
            )
            ui.button("Stop Experiment", on_click=safe_click(stop, label="Stop Experiment")).classes(
                button_class(danger=True)
            )
            ui.button(
                "Refresh runs",
                on_click=safe_click(lambda: refresh_runs(select_latest=True), label="Refresh runs"),
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
        run_select = ui.select([], label="Run folder", on_change=on_run_changed).classes(f"{INPUT_CLASS} w-full")
        log_textarea = ui.textarea(value=state.run.log_text).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(log_height)} w-full"
        )

    controls.update({"refresh_runs": refresh_runs, "refresh_status": refresh_status, "refresh_log": refresh_log})
    return controls
