"""Visible Java MicroRTS GUI controls."""

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
    button_class,
    height_class,
)
from eagle_gui_web.ui_actions import safe_click


def build_microrts_view(state: Any) -> dict[str, Any]:
    """Build the MicroRTS prompt, launch, and trace controls."""
    controls: dict[str, Any] = {}

    async def save_prompt() -> None:
        try:
            path = await asyncio.to_thread(services.save_current_prompt_to_microrts, state.microrts.prompt_text)
            state.microrts.status = f"Saved {path}"
            ui.notify(state.microrts.status, type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
        status_label.set_text(state.microrts.status)

    async def launch() -> None:
        try:
            state.microrts.status = await asyncio.to_thread(services.launch_microrts_gui, state)
            ui.notify(state.microrts.status, type="positive")
        except (OSError, RuntimeError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
        await refresh_status()

    async def stop() -> None:
        state.microrts.status = await asyncio.to_thread(services.stop_microrts_gui)
        ui.notify(state.microrts.status)
        await refresh_status()

    async def refresh_status() -> None:
        state.microrts.status = await asyncio.to_thread(services.microrts_status_text)
        state.microrts.log_text = await asyncio.to_thread(services.read_microrts_log)
        status_label.set_text(state.microrts.status)
        log_text.value = state.microrts.log_text
        log_text.update()
        refresh_trace_choices()

    async def open_trace() -> None:
        try:
            message = await asyncio.to_thread(services.open_trace, state.microrts.selected_trace, state)
            ui.notify(message, type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")

    def load_rendered_prompt() -> None:
        prompt = state.components.rendered_prompt or state.prompts.selected_prompt
        state.microrts.prompt_text = prompt
        prompt_text.value = prompt
        prompt_text.update()

    def on_map_dir_changed(event: Any) -> None:
        state.microrts.map_dir = str(event.value or "8x8")
        files = list(services.microrts_map_file_choices(state.microrts.map_dir))
        map_file_select.options = files
        if state.microrts.map_file not in files:
            state.microrts.map_file = files[0]
        map_file_select.value = state.microrts.map_file
        map_file_select.update()

    def refresh_trace_choices() -> None:
        traces = services.microrts_trace_choices()
        trace_select.options = traces
        if traces and state.microrts.selected_trace not in traces:
            state.microrts.selected_trace = traces[0]
        trace_select.value = state.microrts.selected_trace or None
        trace_select.update()

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("MicroRTS").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3"):
            ui.select(
                list(services.MICRORTS_OPPONENT_CHOICES),
                label="Opponent",
                value=state.microrts.opponent,
                on_change=lambda event: setattr(state.microrts, "opponent", str(event.value or "")),
            ).classes(f"{INPUT_CLASS} w-72")
            ui.select(
                list(services.microrts_map_dir_choices()),
                label="Map folder",
                value=state.microrts.map_dir,
                on_change=on_map_dir_changed,
            ).classes(f"{INPUT_CLASS} w-44")
            map_file_select = ui.select(
                list(services.microrts_map_file_choices(state.microrts.map_dir)),
                label="Map file",
                value=state.microrts.map_file,
                on_change=lambda event: setattr(state.microrts, "map_file", str(event.value or "")),
            ).classes(f"{INPUT_CLASS} w-72")
            ui.input(
                "Update interval",
                value=state.microrts.update_interval,
                on_change=lambda event: setattr(state.microrts, "update_interval", str(event.value or "")),
            ).classes(f"{INPUT_CLASS} w-36")
            ui.input(
                "LLM interval",
                value=state.microrts.llm_interval,
                on_change=lambda event: setattr(state.microrts, "llm_interval", str(event.value or "")),
            ).classes(f"{INPUT_CLASS} w-36")
            ui.checkbox(
                "Save trace",
                value=state.microrts.save_trace,
                on_change=lambda event: setattr(state.microrts, "save_trace", bool(event.value)),
            )

        with ui.row().classes(f"{ROW_CLASS} gap-2"):
            ui.button("Load current prompt", on_click=safe_click(load_rendered_prompt, label="Load current prompt")).classes(
                BUTTON_CLASS
            )
            ui.button("Save prompt.txt", on_click=safe_click(save_prompt, label="Save prompt")).classes(BUTTON_CLASS)
            ui.button("Launch Java GUI", on_click=safe_click(launch, label="Launch Java GUI")).classes(
                button_class(success=True)
            )
            ui.button("Stop Java GUI", on_click=safe_click(stop, label="Stop Java GUI")).classes(button_class(danger=True))
            ui.button("Refresh", on_click=safe_click(refresh_status, label="Refresh MicroRTS")).classes(BUTTON_CLASS)
            status_label = ui.label(state.microrts.status)

        prompt_text = ui.textarea(
            "Prompt for Java GUI",
            value=state.microrts.prompt_text,
            on_change=lambda event: setattr(state.microrts, "prompt_text", str(event.value or "")),
        ).classes(f"{TEXTAREA_CLASS} {height_class(280)} w-full")

        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            trace_select = ui.select(
                [],
                label="Saved trace",
                on_change=lambda event: setattr(state.microrts, "selected_trace", str(event.value or "")),
            ).classes(f"{INPUT_CLASS} grow")
            ui.button("Open trace", on_click=safe_click(open_trace, label="Open trace")).classes(BUTTON_CLASS)
        log_text = ui.textarea(value=state.microrts.log_text).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(300)} w-full"
        )

    controls["refresh_status"] = refresh_status
    controls["refresh_trace_choices"] = refresh_trace_choices
    refresh_trace_choices()
    return controls
