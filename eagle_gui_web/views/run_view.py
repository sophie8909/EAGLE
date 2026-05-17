"""Experiment run control view."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_gui_web import services


def build_run_view(state: Any) -> dict[str, Any]:
    """Build the run process controls and log view."""
    controls: dict[str, Any] = {}

    async def start() -> None:
        try:
            success, message = await asyncio.to_thread(services.start_experiment, state)
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(message, type="positive" if success else "warning")
        await refresh_log()

    async def stop() -> None:
        message = await asyncio.to_thread(services.stop_experiment)
        ui.notify(message)
        await refresh_status()

    async def refresh_runs() -> None:
        runs = await asyncio.to_thread(services.run_choices)
        run_select.options = runs
        if state.run.current_run_dir is None and runs:
            state.run.current_run_dir = Path(runs[0])
            run_select.value = runs[0]
        elif state.run.current_run_dir is not None and str(state.run.current_run_dir) not in runs:
            state.run.current_run_dir = Path(runs[0]) if runs else None
            run_select.value = str(state.run.current_run_dir) if state.run.current_run_dir else None
        run_select.update()

    async def refresh_status() -> None:
        state.run.status_text = await asyncio.to_thread(services.process_status_text)
        status_badge.set_text(state.run.status_text)
        status_badge.props(f"color={'positive' if state.run.status_text.startswith('running') else 'grey'}")

    async def refresh_log() -> None:
        await refresh_status()
        state.run.log_text = await asyncio.to_thread(services.read_log_tail)
        log_textarea.value = state.run.log_text
        log_textarea.update()

    def on_run_changed(event: Any) -> None:
        state.run.current_run_dir = Path(str(event.value)) if event.value else None

    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("items-center gap-3"):
            ui.button("Start experiment", on_click=start)
            ui.button("Stop process", on_click=stop, color="negative")
            ui.button("Refresh runs", on_click=refresh_runs)
            ui.button("Refresh log", on_click=refresh_log)
            status_badge = ui.badge(state.run.status_text, color="grey")
        with ui.row().classes("gap-6"):
            ui.checkbox(
                "Quick run",
                value=state.run.quick_run,
                on_change=lambda event: setattr(state.run, "quick_run", bool(event.value)),
            )
            ui.checkbox(
                "Skip final test",
                value=state.run.skip_final_test,
                on_change=lambda event: setattr(state.run, "skip_final_test", bool(event.value)),
            )
            ui.checkbox(
                "Precompile Python",
                value=state.run.precompile_python,
                on_change=lambda event: setattr(state.run, "precompile_python", bool(event.value)),
            )
        run_select = ui.select([], label="Run folder", on_change=on_run_changed).classes("w-full")
        log_textarea = ui.textarea(value=state.run.log_text).props("readonly").classes("w-full font-mono")
        log_textarea.style("height: 560px")

    controls.update({"refresh_runs": refresh_runs, "refresh_status": refresh_status, "refresh_log": refresh_log})
    return controls
