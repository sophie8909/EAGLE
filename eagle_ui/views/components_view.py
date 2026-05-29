"""Component JSON editor and prompt preview view."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nicegui import ui

from eagle_ui import services
from eagle_ui.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    INPUT_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TABLE_CLASS,
    TEXTAREA_CLASS,
    button_class,
)
from eagle_ui.ui_actions import safe_click
from eagle_ui.views.config_view import refresh_config_summary


def build_components_view(state: Any) -> dict[str, Any]:
    """Build the component editor view."""
    controls: dict[str, Any] = {}
    example_component_keys = {"example", "examples"}
    example_editor_class = "border border-[#b08d57] rounded-[8px] p-1"

    def component_path_options() -> list[str]:
        options = {"", *services.component_json_choices()}
        if state.config.component_pool_path:
            options.add(str(state.config.component_pool_path))
        if state.components.loaded_path:
            options.add(services.relative_or_absolute(state.components.loaded_path))
        return sorted(options)

    async def load_components() -> None:
        try:
            path = services.resolve_repo_path(path_input.value)
            payload = await asyncio.to_thread(services.load_components, path)
            services.apply_component_payload(state, payload, path)
            ui.notify(f"Loaded {path}", type="positive")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh_all()
        refresh_config_summary(state)
        await render_prompt()

    async def save_components() -> None:
        try:
            path = await asyncio.to_thread(services.save_component_json, state)
            ui.notify(f"Saved {path}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh_all()
        refresh_config_summary(state)

    async def save_components_as() -> None:
        try:
            path = services.resolve_repo_path(save_as_input.value)
            saved = await asyncio.to_thread(services.save_component_json, state, path)
            ui.notify(f"Saved {saved}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh_all()
        refresh_config_summary(state)

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
        refresh_example_highlight()

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
        refresh_config_summary(state)

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
        refresh_config_summary(state)

    def reset_selection() -> None:
        state.components.prompt_selection = {key: 0 for key in services.component_keys(state)}
        refresh_selection_table()
        refresh_config_summary(state)

    def copy_prompt() -> None:
        ui.clipboard.write(state.components.rendered_prompt)
        ui.notify("Copied current prompt")

    def add_component_item() -> None:
        key = state.components.selected_category
        if not key or key not in services.component_keys(state):
            ui.notify("Load a component JSON and select a component first.", type="warning")
            return
        value = state.components.payload.get(key)
        if key == "training_examples" and isinstance(value, list):
            value.append({"name": f"example_{len(value)}", "content": [""]})
        elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            state.components.payload[key] = [list(value), [""]]
        elif isinstance(value, list):
            value.append([""])
        else:
            state.components.payload[key] = [[""]]
        state.components.selected_candidate = services.component_candidate_count(state, key) - 1
        refresh_candidate_options()
        load_editor_text()
        refresh_selection_table()

    def delete_component_item() -> None:
        key = state.components.selected_category
        if not key or key not in services.component_keys(state):
            ui.notify("Load a component JSON and select a component first.", type="warning")
            return
        value = state.components.payload.get(key)
        index = int(state.components.selected_candidate)
        if not isinstance(value, list) or index < 0:
            ui.notify("Selected component does not contain editable items.", type="warning")
            return
        if value and all(isinstance(item, str) for item in value):
            state.components.payload[key] = []
        elif index < len(value):
            del value[index]
        else:
            ui.notify("Selected item no longer exists.", type="warning")
            return
        count = services.component_candidate_count(state, key)
        state.components.selected_candidate = min(index, max(0, count - 1))
        refresh_candidate_options()
        load_editor_text()
        refresh_selection_table()

    def refresh_all() -> None:
        options = component_path_options()
        next_value = (
            services.relative_or_absolute(state.components.loaded_path)
            if state.components.loaded_path
            else state.config.component_pool_path or ""
        )
        if next_value not in options:
            options.insert(0, next_value)
        path_input.options = options
        path_input.value = next_value
        path_input.update()
        keys = services.component_keys(state)
        category_select.options = keys
        category_select.value = state.components.selected_category or (keys[0] if keys else None)
        category_select.update()
        refresh_candidate_options()
        load_editor_text()
        refresh_selection_table()
        status_label.set_text(state.components.status)
        refresh_example_highlight()

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

    def refresh_example_highlight() -> None:
        key = str(state.components.selected_category or "").strip().lower()
        if key in example_component_keys:
            editor.classes(add=example_editor_class)
        else:
            editor.classes(remove=example_editor_class)

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

    def update_component_path(event: Any) -> None:
        state.config.component_pool_path = str(event.value or "")

    def create_component_path_select(options: list[str], value: str) -> Any:
        try:
            return ui.select(
                options,
                label="Component JSON",
                value=value,
                on_change=update_component_path,
                with_input=True,
                clearable=True,
            )
        except TypeError:
            return ui.select(
                options,
                label="Component JSON",
                value=value,
                on_change=update_component_path,
            ).props("use-input clearable new-value-mode=add-unique")

    with ui.column().classes("w-full gap-3"):
        control_button_classes = "h-[56px] min-w-[88px] px-4"
        with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
            ui.label("Components").classes(SECTION_HEADER_CLASS)
            with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full flex-nowrap"):
                initial_options = component_path_options()
                initial_value = state.config.component_pool_path or ""
                if initial_value not in initial_options:
                    initial_options.insert(0, initial_value)
                path_input = create_component_path_select(initial_options, initial_value).classes(
                    f"{INPUT_CLASS} grow min-w-[320px]"
                )
                ui.button("Load", on_click=safe_click(load_components, label="Load components")).classes(
                    f"{BUTTON_CLASS} {control_button_classes}"
                )
                ui.button("Save", on_click=safe_click(save_components, label="Save components")).classes(
                    f"{button_class(success=True)} {control_button_classes}"
                )
            with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full flex-nowrap"):
                save_as_input = ui.input("Save as", value="configs/experiments/eagle_ui_components.json").classes(
                    f"{INPUT_CLASS} grow min-w-[320px]"
                )
                ui.button("Save as", on_click=safe_click(save_components_as, label="Save components as")).classes(
                    f"{BUTTON_CLASS} {control_button_classes} min-w-[104px]"
                )
                status_label = ui.label(state.components.status).classes("min-w-[180px] pb-4 whitespace-nowrap")
            with ui.row().classes(f"{ROW_CLASS} gap-2 w-full flex-wrap"):
                ui.button("Add item", on_click=safe_click(add_component_item, label="Add component item")).classes(BUTTON_CLASS)
                ui.button(
                    "Delete item",
                    on_click=safe_click(delete_component_item, label="Delete component item"),
                ).classes(BUTTON_CLASS)
                ui.button("Use in prompt", on_click=safe_click(use_in_prompt, label="Use in prompt")).classes(BUTTON_CLASS)
                ui.button("Toggle static", on_click=safe_click(toggle_static, label="Toggle static")).classes(BUTTON_CLASS)
                ui.button("Reset selection", on_click=safe_click(reset_selection, label="Reset selection")).classes(BUTTON_CLASS)
                ui.button("Render selected prompt", on_click=safe_click(render_prompt, label="Render prompt")).classes(
                    button_class(success=True)
                )
            with ui.row().classes(f"{ROW_CLASS} gap-3 w-full flex-nowrap"):
                category_select = ui.select([], label="Component", on_change=on_category_changed).classes(
                    f"{INPUT_CLASS} grow min-w-[320px]"
                )
                candidate_select = ui.select([], label="Candidate", on_change=on_candidate_changed).classes(
                    f"{INPUT_CLASS} w-56"
                )
            editor = ui.textarea(
                "Candidate text",
                value=state.components.editor_text,
                on_change=lambda event: setattr(state.components, "editor_text", str(event.value or "")),
            ).classes(f"{TEXTAREA_CLASS} min-h-[300px] w-full")

            with ui.row().classes(f"{ROW_CLASS} w-full gap-4 items-stretch flex-nowrap"):
                with ui.column().classes("flex-1 basis-0 min-w-0 gap-2 min-h-[550px]"):
                    ui.label("Component Table").classes(SECTION_HEADER_CLASS)
                    selection_table = ui.table(
                        columns=[
                            {"name": "component", "label": "Component", "field": "component", "align": "left"},
                            {"name": "static", "label": "Static", "field": "static"},
                            {"name": "selected", "label": "Selected", "field": "selected"},
                            {"name": "candidates", "label": "Candidates", "field": "candidates"},
                        ],
                        rows=[],
                        row_key="component",
                    ).classes(f"{TABLE_CLASS} w-full h-[500px] overflow-auto")

                with ui.column().classes("flex-1 basis-0 min-w-0 gap-2 min-h-[550px]"):
                    with ui.row().classes("items-center justify-between w-full"):
                        token_label = ui.label(state.components.prompt_token_summary)
                        ui.button("Copy prompt", on_click=safe_click(copy_prompt, label="Copy prompt")).classes(BUTTON_CLASS)
                    prompt_output = ui.textarea(value=state.components.rendered_prompt).props("readonly").classes(
                        f"{TEXTAREA_CLASS} w-full h-[500px]"
                    )

    controls["refresh"] = refresh_all
    return controls
