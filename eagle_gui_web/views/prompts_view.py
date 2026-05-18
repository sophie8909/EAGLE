"""Runtime LLM trace inspection view."""

from __future__ import annotations

import asyncio
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
    TEXTAREA_CLASS,
    height_class,
)
from eagle_gui_web.ui_actions import safe_click


NO_TRACE_MESSAGE = "No llm_debug.jsonl found for selected run. Run an experiment with LLM debug logging enabled."


def build_prompts_view(state: Any) -> dict[str, Any]:
    """Build runtime LLM trace selectors and input/response panes."""
    controls: dict[str, Any] = {}

    async def refresh_prompts(force: bool = True) -> None:
        run_key = str(state.run.current_run_dir) if state.run.current_run_dir else None
        if not force and run_key == state.prompts.last_run_key and state.prompts.trace_records:
            return
        state.prompts.last_run_key = run_key
        if state.run.current_run_dir is None:
            state.prompts.trace_records = []
            _set_empty("No run selected. Start or select a run before inspecting LLM traces.")
            return

        run_dir = Path(state.run.current_run_dir)
        trace_records = await asyncio.to_thread(services.load_llm_trace_records, run_dir)
        if not trace_records and not (run_dir / "llm_debug.jsonl").exists():
            trace_records = await asyncio.to_thread(_load_fallback_trace_records, state.run.current_run_dir)
        state.prompts.trace_records = trace_records
        if not trace_records:
            _set_empty(NO_TRACE_MESSAGE)
            return
        _select_latest_generation()
        _refresh_generation_options()
        _refresh_individual_options()
        _refresh_call_options()
        render_selected_prompt()

    def _set_empty(message: str) -> None:
        state.prompts.selected_generation = ""
        state.prompts.selected_individual_id = ""
        state.prompts.selected_call_id = ""
        generation_select.options = []
        generation_select.value = None
        individual_select.options = []
        individual_select.value = None
        call_select.options = {}
        call_select.value = None
        for control in (generation_select, individual_select, call_select):
            control.update()
        metadata_label.set_text(message)
        prompt_text.value = ""
        response_text.value = message
        prompt_text.update()
        response_text.update()

    def _select_latest_generation() -> None:
        choices = services.generation_choices(state.prompts.trace_records)
        state.prompts.selected_generation = choices[-1] if choices else ""

    def _refresh_generation_options() -> None:
        choices = services.generation_choices(state.prompts.trace_records)
        generation_select.options = choices
        if state.prompts.selected_generation not in choices:
            state.prompts.selected_generation = choices[-1] if choices else ""
        generation_select.value = state.prompts.selected_generation or None
        generation_select.update()

    def _refresh_individual_options() -> None:
        choices = services.individual_choices(state.prompts.trace_records, state.prompts.selected_generation)
        individual_select.options = choices
        if state.prompts.selected_individual_id not in choices:
            state.prompts.selected_individual_id = choices[0] if choices else ""
        individual_select.value = state.prompts.selected_individual_id or None
        individual_select.update()

    def _refresh_call_options() -> None:
        options = services.llm_call_choices(
            state.prompts.trace_records,
            state.prompts.selected_generation,
            state.prompts.selected_individual_id,
        )
        call_select.options = options
        if state.prompts.selected_call_id not in options:
            state.prompts.selected_call_id = next(iter(options), "")
        call_select.value = state.prompts.selected_call_id or None
        call_select.update()

    def render_selected_prompt() -> None:
        record = _selected_record()
        if not record:
            metadata_label.set_text("No LLM call selected.")
            prompt_text.value = ""
            response_text.value = ""
            prompt_text.update()
            response_text.update()
            return
        state.prompts.selected_prompt = str(record.get("prompt") or "")
        state.prompts.selected_llm_output = _format_response(record)
        state.prompts.metadata = _format_metadata(record)
        metadata_label.set_text(state.prompts.metadata)
        prompt_text.value = state.prompts.selected_prompt
        response_text.value = state.prompts.selected_llm_output
        prompt_text.update()
        response_text.update()

    def on_generation_changed(event: Any) -> None:
        state.prompts.selected_generation = str(event.value or "")
        state.prompts.selected_individual_id = ""
        state.prompts.selected_call_id = ""
        _refresh_individual_options()
        _refresh_call_options()
        render_selected_prompt()

    def on_individual_changed(event: Any) -> None:
        state.prompts.selected_individual_id = str(event.value or "")
        state.prompts.selected_call_id = ""
        _refresh_call_options()
        render_selected_prompt()

    def on_call_changed(event: Any) -> None:
        state.prompts.selected_call_id = str(event.value or "")
        render_selected_prompt()

    def _selected_record() -> dict[str, Any]:
        for record in state.prompts.trace_records:
            if str(record.get("record_id", "")) == state.prompts.selected_call_id:
                return record
        return {}

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Prompts").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            generation_select = ui.select([], label="Generation", on_change=on_generation_changed).classes(
                f"{INPUT_CLASS} w-44"
            )
            individual_select = ui.select([], label="Individual", on_change=on_individual_changed).classes(
                f"{INPUT_CLASS} w-64"
            )
            call_select = ui.select({}, label="LLM call", on_change=on_call_changed).classes(f"{INPUT_CLASS} grow")
            ui.button("Refresh prompts", on_click=safe_click(refresh_prompts, label="Refresh prompts")).classes(BUTTON_CLASS)
        metadata_label = ui.label(state.prompts.metadata)
        with ui.row().classes(f"{ROW_CLASS} w-full gap-4"):
            prompt_text = ui.textarea("LLM INPUT", value=state.prompts.selected_prompt).props("readonly").classes(
                f"{TEXTAREA_CLASS} {height_class(620)} grow"
            )
            response_text = ui.textarea("LLM RESPONSE", value=state.prompts.selected_llm_output).props(
                "readonly"
            ).classes(f"{TEXTAREA_CLASS} {height_class(620)} grow")

    controls["refresh_prompts"] = refresh_prompts
    controls["render_selected_prompt"] = render_selected_prompt
    return controls


def _format_metadata(record: dict[str, Any]) -> str:
    """Return a compact runtime LLM call metadata line."""
    return (
        f"Generation: {record.get('generation', '')} | "
        f"Individual: {record.get('individual_id', '')} | "
        f"Call: {record.get('call_index', '')} | "
        f"Turn: {record.get('turn', '')} | "
        f"Mode: {record.get('mode', '')} | "
        f"Opponent: {record.get('opponent', '')} | "
        f"Error: {record.get('error') or 'none'}"
    )


def _format_response(record: dict[str, Any]) -> str:
    """Return the response pane text with explicit source sections."""
    sections = [
        ("RAW RESPONSE BODY", record.get("raw_response_body", "")),
        ("PARSED RESPONSE", record.get("parsed_response", "")),
        ("FALLBACK RESPONSE", record.get("fallback_response", "")),
        ("ERROR", record.get("error", "")),
    ]
    return "\n\n".join(f"=== {title} ===\n{value or ''}" for title, value in sections)


def _load_fallback_trace_records(run_dir: Path | None) -> list[dict[str, Any]]:
    """Convert legacy prompt records into trace-like rows when llm_debug.jsonl is absent."""
    try:
        records = services.load_prompt_records(run_dir)
    except (OSError, ValueError):
        return []
    trace_records: list[dict[str, Any]] = []
    for index, (record_id, record) in enumerate(records.items(), start=1):
        generation = str(record.get("generation", ""))
        individual_id = str(record.get("individual_id", ""))
        trace_records.append(
            {
                "record_id": str(record_id),
                "generation": generation,
                "individual_id": individual_id,
                "mode": str(record.get("evaluation_mode", "")),
                "opponent": str(record.get("opponent", "")),
                "turn": "",
                "call_index": index,
                "timestamp": "",
                "prompt": str(record.get("prompt") or ""),
                "raw_response_body": "",
                "parsed_response": str(record.get("llm_output") or ""),
                "fallback_response": "",
                "error": "",
            }
        )
    return trace_records
