"""Canonical Experiment surface combining run control and prompt editing."""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from eagle.prompts import DEFAULT_PROMPT_TEMPLATE_PATH
from eagle_ui.controllers.prompt_controller import InitialPromptController, MetaPromptController
from eagle_ui.controllers.run_controller import RunController
from eagle_ui.state import AppState
from eagle_ui.views.prompt_view import build_prompt_view
from eagle_ui.views.run_view import build_run_view


def build_experiment_view(state: AppState, run_controller: RunController, repository_root: Path) -> None:
    """Render one prompt/configuration source and one experiment lifecycle."""

    build_run_view(state, run_controller)
    ui.separator()
    ui.label("Prompt configuration").classes("text-h6")
    build_prompt_view(repository_root, InitialPromptController(), MetaPromptController(DEFAULT_PROMPT_TEMPLATE_PATH))
