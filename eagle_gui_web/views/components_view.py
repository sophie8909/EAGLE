"""Component JSON editor and prompt preview view."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    INPUT_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TABLE_CLASS,
    TEXTAREA_CLASS,
    button_class,
    height_class,
)
from eagle_gui_web.ui_actions import safe_click


def build_components_view(state: Any) -> dict[str, Any]:
    """Build the component editor view."""
    controls: dict[str, Any] = {}

    async def load_components() -> None:
        try:
            path = services.resolve_repo_path(path_input.value)
            payload = await asyncio.to_thread(services.load_component_json, path)
            services.apply_component_payload(state, payload, path)
            ui.notify(f"Loaded {path}", type="positive")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh_all()
        await render_prompt()

    async def save_components() -> None:
        try:
            path = await asyncio.to_thread(services.save_component_json, state)
            ui.notify(f"Saved {path}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh_all()

    async def save_components_as() -> None:
        try:
            path = services.resolve_repo_path(save_as_input.value)
            saved = await asyncio.to_thread(services.save_component_json, state, path)
            ui.notify(f"Saved {saved}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh_all()

    async def render_prompt() -> None:
        try:
            prompt = await asyncio.to_thread(services.render_component_prompt, state)
        except (TypeError, ValueError) as exc:
            prompt = f"Could not render prompt:\n{exc}"
            state.components.prompt_token_summary = "Prompt tokens: 0"
        prompt_output.value = prompt
        token_label.set_text(state.components.prompt_token_summary)
        prompt_output.update()

    def on_category_changed(event: Any) -> None:
        state.components.selected_category = str(event.value or "")
        state.components.selected_candidate = 0
        refresh_candidate_options()
        load_editor_text()

    def on_candidate_changed(event: Any) -> None:
        try:
            state.components.selected_candidate = int(event.value or 0)
        except ValueError:
            state.components.selected_candidate = 0
        load_editor_text()

    def use_in_prompt() -> None:
        key = state.components.selected_category
        if not key:
            return
        if key in state.config.non_evolving_prompt_components:
            state.components.prompt_selection[key] = 0
        else:
            state.components.prompt_selection[key] = int(state.components.selected_candidate)
        refresh_selection_table()

    def toggle_static() -> None:
        key = state.components.selected_category
        if not key or key == "training_examples":
            return
        if key in state.config.non_evolving_prompt_components:
            state.config.non_evolving_prompt_components.remove(key)
        else:
            state.config.non_evolving_prompt_components.add(key)
            state.components.prompt_selection[key] = 0
        refresh_selection_table()

    def reset_selection() -> None:
        state.components.prompt_selection = {key: 0 for key in services.component_keys(state)}
        refresh_selection_table()

    def copy_prompt() -> None:
        ui.clipboard.write(state.components.rendered_prompt)
        ui.notify("Copied current prompt")

    def refresh_all() -> None:
        keys = services.component_keys(state)
        category_select.options = keys
        category_select.value = state.components.selected_category or (keys[0] if keys else None)
        category_select.update()
        refresh_candidate_options()
        load_editor_text()
        refresh_selection_table()
        status_label.set_text(state.components.status)
        path_input.value = str(state.components.loaded_path or state.config.component_pool_path or "")
        path_input.update()

    def refresh_candidate_options() -> None:
        count = services.component_candidate_count(state, state.components.selected_category)
        options = list(range(count))
        candidate_select.options = options
        candidate_select.value = state.components.selected_candidate if options else None
        candidate_select.update()

    def load_editor_text() -> None:
        state.components.editor_text = services.component_candidate_text(
            state,
            state.components.selected_category,
            int(state.components.selected_candidate),
        )
        editor.value = state.components.editor_text
        editor.update()

    def refresh_selection_table() -> None:
        rows = []
        for key in services.component_keys(state):
            rows.append(
                {
                    "component": key,
                    "static": "yes" if key in state.config.non_evolving_prompt_components else "",
                    "selected": "sample" if key == "training_examples" else state.components.prompt_selection.get(key, 0),
                    "candidates": services.component_candidate_count(state, key),
                }
            )
        selection_table.rows = rows
        selection_table.update()

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Components").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            path_input = ui.input(
                "Component JSON",
                value=state.config.component_pool_path,
                placeholder="eagle/prompts/components.json",
            ).classes(f"{INPUT_CLASS} min-w-[460px]")
            ui.button("Load", on_click=safe_click(load_components, label="Load components")).classes(BUTTON_CLASS)
            ui.button("Save", on_click=safe_click(save_components, label="Save components")).classes(
                button_class(success=True)
            )
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            save_as_input = ui.input("Save as", value="configs/experiments/gui_web_components.json").classes(
                f"{INPUT_CLASS} min-w-[460px]"
            )
            ui.button("Save as", on_click=safe_click(save_components_as, label="Save components as")).classes(BUTTON_CLASS)
            status_label = ui.label(state.components.status)

        with ui.row().classes(f"{ROW_CLASS} w-full gap-4"):
            with ui.column().classes("w-1/2 gap-3"):
                with ui.row().classes(f"{ROW_CLASS} gap-3 w-full"):
                    category_select = ui.select([], label="Component", on_change=on_category_changed).classes(
                        f"{INPUT_CLASS} grow"
                    )
                    candidate_select = ui.select([], label="Candidate", on_change=on_candidate_changed).classes(
                        f"{INPUT_CLASS} w-32"
                    )
                editor = ui.textarea(
                    "Candidate text",
                    value=state.components.editor_text,
                    on_change=lambda event: setattr(state.components, "editor_text", str(event.value or "")),
                ).classes(f"{TEXTAREA_CLASS} {height_class(360)} w-full")
                with ui.row().classes(f"{ROW_CLASS} gap-2"):
                    ui.button("Use in prompt", on_click=safe_click(use_in_prompt, label="Use in prompt")).classes(BUTTON_CLASS)
                    ui.button("Toggle static", on_click=safe_click(toggle_static, label="Toggle static")).classes(BUTTON_CLASS)
                    ui.button("Reset selection", on_click=safe_click(reset_selection, label="Reset selection")).classes(BUTTON_CLASS)
                    ui.button("Render selected prompt", on_click=safe_click(render_prompt, label="Render prompt")).classes(
                        button_class(success=True)
                    )

                selection_table = ui.table(
                    columns=[
                        {"name": "component", "label": "Component", "field": "component", "align": "left"},
                        {"name": "static", "label": "Static", "field": "static"},
                        {"name": "selected", "label": "Selected", "field": "selected"},
                        {"name": "candidates", "label": "Candidates", "field": "candidates"},
                    ],
                    rows=[],
                    row_key="component",
                ).classes(f"{TABLE_CLASS} w-full")

            with ui.column().classes("w-1/2 gap-2"):
                with ui.row().classes("items-center justify-between w-full"):
                    token_label = ui.label(state.components.prompt_token_summary)
                    ui.button("Copy prompt", on_click=safe_click(copy_prompt, label="Copy prompt")).classes(BUTTON_CLASS)
                prompt_output = ui.textarea(value=state.components.rendered_prompt).props("readonly").classes(
                    f"{TEXTAREA_CLASS} {height_class(620)} w-full"
                )

    controls["refresh"] = refresh_all
    return controls
