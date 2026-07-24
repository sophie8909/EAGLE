"""Canonical EAGLE GUI lifecycle and three top-level control surfaces."""

from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from eagle_ui.controllers.analysis_controller import AnalysisController
from eagle_ui.controllers.artifact_controller import ArtifactController
from eagle_ui.controllers.llm_controller import LLMConfigController
from eagle_ui.controllers.run_controller import RunController
from eagle_ui.state import AppState
from eagle_ui.theme import CARD_CLASS, install_theme
from eagle_ui.views.analysis_view import build_analysis_view
from eagle_ui.views.candidate_view import build_candidate_view
from eagle_ui.views.experiment_view import build_experiment_view
from eagle_ui.views.llm_view import build_llm_view, build_profile_configuration
from eagle_ui.runtime import resolve_gui_port


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
        servers_tab = ui.tab("Servers")
        experiment_tab = ui.tab("Experiment")
        analysis_tab = ui.tab("Analysis")
    llm_controller = LLMConfigController(ROOT)
    with ui.tab_panels(tabs, value=servers_tab).classes("w-full"):
        with ui.tab_panel(servers_tab):
            build_llm_view(llm_controller, ROOT)
            ui.separator()
            build_profile_configuration(llm_controller, ROOT)
        with ui.tab_panel(experiment_tab):
            build_experiment_view(STATE, RUN_CONTROLLER, ROOT)
        with ui.tab_panel(analysis_tab):
            build_analysis_view(AnalysisController(), STATE)
            ui.separator()
            ui.label("Candidate artifacts").classes("text-h6")
            build_candidate_view(ArtifactController(ROOT / "runs"))


def _shutdown() -> None:
    RUN_CONTROLLER.shutdown()


app.on_shutdown(_shutdown)


def main() -> None:
    build_layout()
    ui.run(title="EAGLE", reload=False, show=True, port=resolve_gui_port())


if __name__ in {"__main__", "__mp_main__"}:
    main()