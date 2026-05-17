"""Prompt inspection view."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    INPUT_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TEXTAREA_CLASS,
    height_class,
)
from eagle_gui_web.ui_actions import safe_click


def build_prompts_view(state: Any) -> dict[str, Any]:
    """Build prompt record selector and prompt/response panes."""
    controls: dict[str, Any] = {}

    async def refresh_prompts(force: bool = True) -> None:
        run_key = str(state.run.current_run_dir) if state.run.current_run_dir else None
        if not force and run_key == state.prompts.last_run_key:
            return
        try:
            records = await asyncio.to_thread(services.load_prompt_records, state.run.current_run_dir)
        except (OSError, ValueError) as exc:
            records = {
                "error": {
                    "prompt": "",
                    "llm_output": str(exc),
                    "generation": "",
                    "individual_id": "load error",
                    "evaluation_mode": "",
                }
            }
        state.prompts.records = records
        state.prompts.last_run_key = run_key
        options = {record_id: services.prompt_record_label(record_id, record) for record_id, record in records.items()}
        prompt_select.options = options
        if options:
            state.prompts.selected_record_id = next(iter(options))
            prompt_select.value = state.prompts.selected_record_id
        else:
            state.prompts.selected_record_id = ""
            prompt_select.value = None
        prompt_select.update()
        render_selected_prompt()

    def render_selected_prompt() -> None:
        record = state.prompts.records.get(state.prompts.selected_record_id, {})
        state.prompts.selected_prompt = str(record.get("prompt") or "")
        state.prompts.selected_llm_output = str(record.get("llm_output") or "")
        state.prompts.metadata = services.prompt_record_metadata(record) if record else "No prompt selected"
        metadata_label.set_text(state.prompts.metadata)
        prompt_text.value = state.prompts.selected_prompt
        response_text.value = state.prompts.selected_llm_output
        prompt_text.update()
        response_text.update()

    def on_prompt_changed(event: Any) -> None:
        state.prompts.selected_record_id = str(event.value or "")
        render_selected_prompt()

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Prompts").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            prompt_select = ui.select({}, label="Prompt record", on_change=on_prompt_changed).classes(
                f"{INPUT_CLASS} grow"
            )
            ui.button("Refresh prompts", on_click=safe_click(refresh_prompts, label="Refresh prompts")).classes(BUTTON_CLASS)
        metadata_label = ui.label(state.prompts.metadata)
        with ui.row().classes(f"{ROW_CLASS} w-full gap-4"):
            prompt_text = ui.textarea("Prompt", value=state.prompts.selected_prompt).props("readonly").classes(
                f"{TEXTAREA_CLASS} {height_class(620)} grow"
            )
            response_text = ui.textarea("LLM output", value=state.prompts.selected_llm_output).props("readonly").classes(
                f"{TEXTAREA_CLASS} {height_class(620)} grow"
            )

    controls["refresh_prompts"] = refresh_prompts
    controls["render_selected_prompt"] = render_selected_prompt
    return controls
