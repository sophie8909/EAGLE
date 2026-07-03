"""Runtime examples editor view."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from eagle_ui import services
from eagle_ui.theme import (
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
from eagle_ui.ui_actions import safe_click


def build_examples_view(state: Any) -> dict[str, Any]:
    """Build the editable runtime examples view."""
    controls: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    validation_logs: list[dict[str, Any]] = []
    selected_id: str | None = None

    def option_map() -> dict[str, str]:
        return {
            str(record.get("id", index)): f"{index + 1}. {record.get('name') or f'example_{index}'}"
            for index, record in enumerate(records)
        }

    def clamp_selected_index() -> int:
        nonlocal selected_id
        if not records:
            selected_id = None
            return 0
        ids = [str(record.get("id", index)) for index, record in enumerate(records)]
        if selected_id not in ids:
            selected_id = ids[0]
        return ids.index(str(selected_id))

    def apply_editor_to_record() -> None:
        if not records:
            return
        index = clamp_selected_index()
        record = records[index]
        record["name"] = str(name_input.value or "").strip() or f"example_{index}"
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
        example_select.options = option_map()
        example_select.value = selected_id
        example_select.update()
        empty_label.set_visibility(not records)
        invalid_logs_checkbox.set_visibility(bool(validation_logs))
        invalid_logs_editor.set_visibility(bool(validation_logs) and bool(invalid_logs_checkbox.value))
        invalid_logs_editor.value = _render_validation_logs(validation_logs)
        invalid_logs_editor.update()
        load_record_into_editor()

    def set_example_bound(field_name: str, value: Any) -> None:
        setattr(state.config, field_name, str(value or "0").strip())

    def set_example_weight(key: str, value: Any) -> None:
        state.operators.example_reproduction_weights[key] = str(value or "0").strip()

    def set_example_mutation_source_weight(key: str, value: Any) -> None:
        state.operators.example_mutation_source_weights[key] = str(value or "0").strip()

    def toggle_invalid_logs(event: Any) -> None:
        invalid_logs_editor.set_visibility(bool(validation_logs) and bool(event.value))

    def _render_validation_logs(rows: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for row in rows[-50:]:
            errors = row.get("errors")
            error_text = "; ".join(str(error) for error in errors) if isinstance(errors, list) else str(errors or "")
            lines.append(
                " ".join(
                    part
                    for part in (
                        f"generation={row.get('generation', '')}",
                        f"round_id={row.get('round_id', '')}",
                        f"legality_level={row.get('legality_level', '')}",
                        error_text,
                    )
                    if part
                )
            )
        return "\n".join(lines)

    async def refresh() -> None:
        nonlocal records, selected_id, validation_logs
        previous_selected_id = selected_id
        path, loaded_records = await asyncio.to_thread(services.load_example_records, state)
        _, validation_logs = await asyncio.to_thread(services.load_examples_validation_logs, state)
        records = loaded_records
        selected_id = previous_selected_id
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
        nonlocal selected_id
        apply_editor_to_record()
        new_id = f"new_{len(records)}"
        selected_id = new_id
        records.append(
            {
                "id": new_id,
                "name": f"example_{len(records)}",
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
                "source": "manual",
                "validator_passed": True,
                "legality_level": "manual",
            }
        )
        refresh_widgets()

    async def delete_example() -> None:
        nonlocal selected_id
        if not records:
            return
        deleted_index = clamp_selected_index()
        records.pop(deleted_index)
        if records:
            next_index = min(deleted_index, len(records) - 1)
            selected_id = str(records[next_index].get("id", next_index))
        else:
            selected_id = None
        try:
            await asyncio.to_thread(services.save_example_records, state, records)
        except OSError as exc:
            ui.notify(str(exc), type="negative")
            return
        await refresh()

    def select_example(event: Any) -> None:
        nonlocal selected_id
        apply_editor_to_record()
        selected_id = str(event.value) if event.value is not None else None
        refresh_widgets()

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Examples").classes(SECTION_HEADER_CLASS)
            with ui.row().classes(f"{ROW_CLASS} gap-2"):
                ui.button("Refresh", on_click=safe_click(refresh, label="Refresh examples")).classes(BUTTON_CLASS)
                ui.button("Save", on_click=safe_click(save, label="Save examples")).classes(button_class(success=True))
        with ui.row().classes(f"{ROW_CLASS} items-center gap-4"):
            ui.checkbox(
                "few-shot prompt",
                value=state.config.use_few_shot_examples,
                on_change=lambda event: setattr(state.config, "use_few_shot_examples", bool(event.value)),
            )
            ui.label("example sample range").classes(MUTED_CLASS)
            ui.input(
                "min_examples",
                value=state.config.min_examples,
                on_change=lambda event: set_example_bound("min_examples", event.value),
            ).props("type=number min=0").classes(f"{INPUT_CLASS} w-32")
            ui.label("-").classes(MUTED_CLASS)
            ui.input(
                "max_examples",
                value=state.config.max_examples,
                on_change=lambda event: set_example_bound("max_examples", event.value),
            ).props("type=number min=0").classes(f"{INPUT_CLASS} w-32")
        with ui.row().classes(f"{ROW_CLASS} items-center gap-4"):
            ui.label("example reproduction").classes(MUTED_CLASS)
            for key, label in (("crossover", "crossover"), ("mutation", "mutation")):
                ui.input(
                    label,
                    value=state.operators.example_reproduction_weights.get(key, "0.5"),
                    on_change=lambda event, item=key: set_example_weight(item, event.value),
                ).props("type=number min=0 step=0.05").classes(f"{INPUT_CLASS} w-32")
        with ui.row().classes(f"{ROW_CLASS} items-center gap-4"):
            ui.label("mutation source").classes(MUTED_CLASS)
            for key, label in (("fresh", "fresh"), ("pool", "pool")):
                ui.input(
                    label,
                    value=state.operators.example_mutation_source_weights.get(key, "0.5"),
                    on_change=lambda event, item=key: set_example_mutation_source_weight(item, event.value),
                ).props("type=number min=0 step=0.05").classes(f"{INPUT_CLASS} w-32")
        path_label = ui.label("").classes(MUTED_CLASS)
        empty_label = ui.label("No runtime examples found.").classes(MUTED_CLASS)
        invalid_logs_checkbox = ui.checkbox(
            "Show invalid/skipped logs",
            value=False,
            on_change=toggle_invalid_logs,
        )
        invalid_logs_editor = ui.textarea("Invalid/skipped logs").props("readonly").classes(f"{TEXTAREA_CLASS} {height_class(180)} w-full")
        invalid_logs_checkbox.set_visibility(False)
        invalid_logs_editor.set_visibility(False)
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            example_select = ui.select([], label="Example", on_change=select_example).classes(f"{INPUT_CLASS} grow")
            ui.button("Add", on_click=safe_click(add_example, label="Add example")).classes(BUTTON_CLASS)
            ui.button("Delete", on_click=safe_click(delete_example, label="Delete example")).classes(BUTTON_CLASS)
        name_input = ui.input("Name").classes(f"{INPUT_CLASS} w-full")
        content_editor = ui.textarea("Content").classes(f"{TEXTAREA_CLASS} {height_class(520)} w-full")

    controls["refresh"] = refresh
    ui.timer(0.1, refresh, once=True)
    return controls
