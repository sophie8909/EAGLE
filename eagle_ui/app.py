"""Restored NiceGUI application shell for the current EAGLE architecture."""

from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from eagle_ui.controllers.run_controller import RunController
from eagle_ui.controllers.artifact_controller import ArtifactController
from eagle_ui.controllers.analysis_controller import AnalysisController
from eagle_ui.controllers.error_controller import ErrorAnalysisController
from eagle_ui.controllers.llm_controller import LLMConfigController
from eagle_ui.controllers.prompt_controller import InitialPromptController, MetaPromptController
from eagle_ui.state import AppState
from eagle_ui.theme import CARD_CLASS, install_theme
from eagle_ui.views.llm_view import build_llm_view
from eagle_ui.views.prompt_view import build_prompt_view
from eagle_ui.views.run_view import build_run_view
from eagle_ui.views.candidate_view import build_candidate_view
from eagle_ui.views.analysis_view import build_analysis_view
from eagle_ui.views.error_view import build_error_view
from eagle.prompts import DEFAULT_PROMPT_TEMPLATE_PATH


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
        with ui.tab_panel(llm_tab):
            build_llm_view(LLMConfigController(ROOT), ROOT)
        with ui.tab_panel(prompt_tab):
            build_prompt_view(ROOT, InitialPromptController(), MetaPromptController(DEFAULT_PROMPT_TEMPLATE_PATH))
        with ui.tab_panel(browser_tab):
            build_candidate_view(ArtifactController(ROOT / "runs"))
        with ui.tab_panel(analysis_tab):
            build_analysis_view(AnalysisController(), STATE)
        with ui.tab_panel(error_tab):
            build_error_view(ErrorAnalysisController(), STATE)


def _shutdown() -> None:
    RUN_CONTROLLER.shutdown()


app.on_shutdown(_shutdown)


def main() -> None:
    build_layout()
    ui.run(title="EAGLE", reload=False, show=True)


if __name__ in {"__main__", "__mp_main__"}:
    main()
