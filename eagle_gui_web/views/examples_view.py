"""Runtime examples editor view."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    INPUT_CLASS,
    MUTED_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TEXTAREA_CLASS,
    button_class,
    height_class,
)
from eagle_gui_web.ui_actions import safe_click


def build_examples_view(state: Any) -> dict[str, Any]:
    """Build the editable runtime examples view."""
    controls: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    selected_index = 0

    def option_labels() -> list[str]:
        return [
            f"{index + 1}. {record.get('name') or f'example_{index}'}"
            for index, record in enumerate(records)
        ]

    def clamp_selected_index() -> int:
        nonlocal selected_index
        if not records:
            selected_index = 0
            return selected_index
        selected_index = max(0, min(selected_index, len(records) - 1))
        return selected_index

    def apply_editor_to_record() -> None:
        if not records:
            return
        record = records[clamp_selected_index()]
        record["name"] = str(name_input.value or "").strip() or f"example_{selected_index}"
        record["content"] = str(content_editor.value or "").splitlines()

    def load_record_into_editor() -> None:
        if not records:
            name_input.value = ""
            content_editor.value = ""
            name_input.update()
            content_editor.update()
            return
        record = records[clamp_selected_index()]
        name_input.value = str(record.get("name", ""))
        content_editor.value = "\n".join(str(line) for line in list(record.get("content") or []))
        name_input.update()
        content_editor.update()

    def refresh_widgets() -> None:
        example_select.options = option_labels()
        example_select.value = option_labels()[selected_index] if records else None
        example_select.update()
        empty_label.set_visibility(not records)
        load_record_into_editor()

    async def refresh() -> None:
        nonlocal records
        path, loaded_records = await asyncio.to_thread(services.load_example_records, state)
        records = loaded_records
        clamp_selected_index()
        path_label.set_text(services.relative_or_absolute(path))
        refresh_widgets()

    async def save() -> None:
        apply_editor_to_record()
        try:
            path = await asyncio.to_thread(services.save_example_records, state, records)
        except OSError as exc:
            ui.notify(str(exc), type="negative")
            return
        path_label.set_text(services.relative_or_absolute(path))
        refresh_widgets()
        ui.notify(f"Saved {path}", type="positive")

    def add_example() -> None:
        nonlocal selected_index
        apply_editor_to_record()
        selected_index = len(records)
        records.append(
            {
                "name": f"example_{selected_index}",
                "content": [
                    "INPUT:",
                    "Map size: 8x8",
                    "Turn: 0/5000",
                    "Max actions: 4",
                    "",
                    "Feature locations:",
                    "(2, 1) Ally Base Unit {resources=5, current_action=\"idling\", HP=10}",
                    "(1, 1) Ally Worker Unit {current_action=\"idling\", HP=1}",
                    "(5, 6) Enemy Base Unit {resources=5, current_action=\"idling\", HP=10}",
                    "",
                    "OUTPUT:",
                    "{",
                    "  \"thinking\": \"Describe the state and why this move is valid.\",",
                    "  \"moves\": [",
                    "    {",
                    "      \"raw_move\": \"(1,1): worker harvest((0,0),(2,1))\",",
                    "      \"unit_position\": [1,1],",
                    "      \"unit_type\": \"worker\",",
                    "      \"action_type\": \"harvest\"",
                    "    }",
                    "  ]",
                    "}",
                ],
            }
        )
        refresh_widgets()

    async def delete_example() -> None:
        nonlocal selected_index
        if not records:
            return
        records.pop(clamp_selected_index())
        selected_index = max(0, selected_index - 1)
        try:
            await asyncio.to_thread(services.save_example_records, state, records)
        except OSError as exc:
            ui.notify(str(exc), type="negative")
            return
        await refresh()

    def select_example(event: Any) -> None:
        nonlocal selected_index
        apply_editor_to_record()
        value = str(event.value or "")
        try:
            selected_index = int(value.split(".", 1)[0]) - 1
        except ValueError:
            selected_index = 0
        refresh_widgets()

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Examples").classes(SECTION_HEADER_CLASS)
            with ui.row().classes(f"{ROW_CLASS} gap-2"):
                ui.button("Refresh", on_click=safe_click(refresh, label="Refresh examples")).classes(BUTTON_CLASS)
                ui.button("Save", on_click=safe_click(save, label="Save examples")).classes(button_class(success=True))
        path_label = ui.label("").classes(MUTED_CLASS)
        empty_label = ui.label("No runtime examples found.").classes(MUTED_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            example_select = ui.select([], label="Example", on_change=select_example).classes(f"{INPUT_CLASS} grow")
            ui.button("Add", on_click=safe_click(add_example, label="Add example")).classes(BUTTON_CLASS)
            ui.button("Delete", on_click=safe_click(delete_example, label="Delete example")).classes(BUTTON_CLASS)
        name_input = ui.input("Name").classes(f"{INPUT_CLASS} w-full")
        content_editor = ui.textarea("Content").classes(f"{TEXTAREA_CLASS} {height_class(520)} w-full")

    controls["refresh"] = refresh
    ui.timer(0.1, refresh, once=True)
    return controls
