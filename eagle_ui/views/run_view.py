"""EA run-control page backed by :class:`RunController`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from eagle_ui.components.log_panel import create_log_panel
from eagle_ui.controllers.run_controller import RunController
from eagle_ui.state import AppState
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def build_run_view(state: AppState, controller: RunController) -> None:
    choices = {str(path): path.name for path in controller.config_choices()}
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("EA Run Control").classes("text-h6")
        config_select = ui.select(
            choices,
            label="Experiment configuration",
            value=str(state.repository_root / state.run.config_path),
        ).classes(f"{INPUT_CLASS} w-full")
        mock = ui.checkbox("Dry run / mock evaluation", value=state.run.mock)
        with ui.row().classes("items-center gap-2"):
            start_button = ui.button("Start EA run").classes(BUTTON_CLASS)
            status = ui.badge("idle")
        with ui.grid(columns=3).classes("w-full gap-3"):
            generation = _status_field("Current generation", "—")
            candidate = _status_field("Current candidate", "—")
            counts = _status_field("Completed / failed", "0 / 0")
        run_dir = _status_field("Current run directory", "—")
        log = create_log_panel()

    async def start() -> None:
        try:
            selected = Path(str(config_select.value))
            await asyncio.to_thread(controller.start, selected, mock=bool(mock.value))
        except (OSError, ValueError, RuntimeError) as exc:
            ui.notify(f"Cannot start EA run: {exc}", type="negative")
            return
        refresh()

    def refresh() -> None:
        status.set_text("running" if state.run.running else f"exit {state.run.returncode}" if state.run.returncode is not None else "idle")
        generation.set_text("—" if state.run.current_generation is None else str(state.run.current_generation))
        candidate.set_text(state.run.current_candidate or "—")
        counts.set_text(f"{state.run.completed_candidates} / {state.run.failed_candidates}")
        run_dir.set_text(str(state.run.effective_run_dir or "—"))
        log.value = "\n".join(state.run.log_lines[-2000:])
        log.update()
        start_button.set_enabled(not state.run.running)

    start_button.on_click(start)
    ui.timer(0.5, refresh)


def _status_field(label: str, value: str):
    with ui.column().classes("gap-0"):
        ui.label(label).classes("text-caption")
        return ui.label(value).classes("font-mono break-all")
