"""Restored NiceGUI application shell for the current EAGLE architecture."""

from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from eagle_ui.controllers.run_controller import RunController
from eagle_ui.state import AppState
from eagle_ui.theme import CARD_CLASS, install_theme
from eagle_ui.views.run_view import build_run_view


ROOT = Path(__file__).resolve().parents[1]
STATE = AppState(repository_root=ROOT)
RUN_CONTROLLER = RunController(ROOT, STATE.run)


def build_layout() -> None:
    install_theme()
    with ui.header().classes("items-center justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("EAGLE").classes("text-h5")
            ui.label("Evolutionary Algorithm for Game-playing with LLM-Enabled Agents").classes("text-caption")
        ui.button("Close GUI", on_click=app.shutdown)

    with ui.tabs().classes(f"{CARD_CLASS} w-full") as tabs:
        run_tab = ui.tab("Run")
        llm_tab = ui.tab("LLM Roles")
        prompt_tab = ui.tab("Prompts")
        browser_tab = ui.tab("Runs & Candidates")
        analysis_tab = ui.tab("Objectives")
        error_tab = ui.tab("Errors")
    with ui.tab_panels(tabs, value=run_tab).classes("w-full"):
        with ui.tab_panel(run_tab):
            build_run_view(STATE, RUN_CONTROLLER)
        for tab, message in (
            (llm_tab, "LLM role configuration"),
            (prompt_tab, "Initial and meta-prompt configuration"),
            (browser_tab, "Run and candidate inspection"),
            (analysis_tab, "Multi-objective analysis"),
            (error_tab, "Error analysis"),
        ):
            with ui.tab_panel(tab):
                ui.label(message).classes("text-h6")


def _shutdown() -> None:
    RUN_CONTROLLER.shutdown()


app.on_shutdown(_shutdown)


def main() -> None:
    build_layout()
    ui.run(title="EAGLE", reload=False, show=True)


if __name__ in {"__main__", "__mp_main__"}:
    main()
