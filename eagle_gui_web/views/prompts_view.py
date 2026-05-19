"""Runtime LLM trace inspection view."""

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
NO_RUN_MESSAGE = "No run folder selected."
NO_TRACE_MESSAGE = "No LLM trace files found. Expected <run_dir>/llm_calls/generation_*.json."
NO_CALL_MESSAGE = "No LLM call selected."
NO_RESPONSE_MESSAGE = "No response field found in this trace record."


def build_prompts_view(state: Any) -> dict[str, Any]:
    """Build runtime LLM trace selectors and input/response panes."""
    controls: dict[str, Any] = {}

    async def refresh_prompts(force: bool = True) -> None:
        if state.run.current_run_dir is None:
            state.prompts.trace_records = []
            _set_empty(NO_RUN_MESSAGE)
            return

        run_dir = state.run.current_run_dir
        state.prompts.trace_records = await asyncio.to_thread(services.load_llm_trace_records, run_dir)
        trace_records = state.prompts.trace_records
        if not trace_records:
            if _has_generation_trace_files(run_dir) or _has_llm_debug_trace_file(run_dir):
                _set_empty(NO_CALL_MESSAGE)
            else:
                _set_empty(NO_TRACE_MESSAGE)
            return
        _refresh_all_options()
        render_selected_call()

    def _set_empty(message: str) -> None:
        state.prompts.selected_generation = ""
        state.prompts.selected_individual_id = ""
        state.prompts.selected_call_id = ""
        state.prompts.selected_prompt = ""
        state.prompts.selected_llm_output = ""
        state.prompts.metadata = message
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

    def _refresh_all_options() -> None:
        _refresh_generation_options()
        _refresh_individual_options()
        _refresh_call_options()

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

    def render_selected_call() -> None:
        record = _selected_record()
        if not record:
            metadata_label.set_text(NO_CALL_MESSAGE)
            state.prompts.selected_prompt = ""
            state.prompts.selected_llm_output = ""
            state.prompts.metadata = NO_CALL_MESSAGE
            prompt_text.value = ""
            response_text.value = ""
            prompt_text.update()
            response_text.update()
            return
        state.prompts.selected_prompt = str(record.get("input") or "")
        state.prompts.selected_llm_output = _format_response(record)
        state.prompts.metadata = _format_metadata(record, state.prompts.trace_records)
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
        render_selected_call()

    def on_individual_changed(event: Any) -> None:
        state.prompts.selected_individual_id = str(event.value or "")
        state.prompts.selected_call_id = ""
        _refresh_call_options()
        render_selected_call()

    def on_call_changed(event: Any) -> None:
        state.prompts.selected_call_id = str(event.value or "")
        render_selected_call()

    def _selected_record() -> dict[str, Any]:
        record = services.get_llm_trace_record(state.prompts.trace_records, state.prompts.selected_call_id)
        return record or {}

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
    controls["render_selected_call"] = render_selected_call
    return controls


def _format_metadata(record: dict[str, Any], trace_records: list[dict[str, Any]]) -> str:
    """Return a compact runtime LLM call metadata line."""
    generation_count = len(services.generation_choices(trace_records))
    individual_count = len({str(item.get("individual_id", "")) for item in trace_records if str(item.get("individual_id", ""))})
    return (
        f"Loaded {len(trace_records)} records | Generations: {generation_count} | Individuals: {individual_count}\n"
        f"Generation: {record.get('generation', '')} | Individual: {record.get('individual_id', '')} | "
        f"Call: {record.get('call_index', '')} | Turn: {record.get('turn', '')} | Mode: {record.get('mode', '')} | "
        f"Opponent: {record.get('opponent', '')} | Error: {record.get('error') or 'none'}"
    )


def _format_response(record: dict[str, Any]) -> str:
    """Return the response pane text with explicit source sections."""
    if not _has_response_fields(record):
        return NO_RESPONSE_MESSAGE
    sections = [
        ("RAW RESPONSE BODY", record.get("raw_response_body", ""), "(none)"),
        ("PARSED RESPONSE", record.get("parsed_response", ""), "(none)"),
        ("FINAL RESPONSE", record.get("final_response", ""), "(none)"),
        ("FALLBACK RESPONSE", record.get("fallback_response") or record.get("llm_output", ""), "(none)"),
        ("ERROR", record.get("error", ""), "none"),
    ]
    return "\n\n".join(f"=== {title} ===\n{_response_value(value, empty=empty)}" for title, value, empty in sections)


def _has_response_fields(record: dict[str, Any]) -> bool:
    """Return whether a trace record has any response content."""
    return any(
        str(record.get(field, "")).strip()
        for field in ("raw_response_body", "parsed_response", "final_response", "fallback_response", "llm_output", "error")
    )


def _response_value(value: Any, *, empty: str = "(none)") -> str:
    """Return response text with a visible empty placeholder."""
    text = str(value or "").strip()
    return text if text else empty


def _has_generation_trace_files(run_dir: Any) -> bool:
    """Return whether the selected run has per-generation trace JSON files."""
    if run_dir is None:
        return False
    return any((run_dir / "llm_calls").glob("generation_*.json"))


def _has_llm_debug_trace_file(run_dir: Any) -> bool:
    """Return whether the selected run has a JSONL trace file."""
    if run_dir is None:
        return False
    return (run_dir / "llm_debug.jsonl").exists()
