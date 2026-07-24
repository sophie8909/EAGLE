"""Bounded selectable text log view with explicit controls."""
from __future__ import annotations
from nicegui import ui
from eagle.runtime.process_logs import ProcessLogBuffer
from eagle_ui.theme import BUTTON_CLASS, MONO_CLASS, TEXTAREA_CLASS

def create_log_panel(*, height_px: int = 360, on_clear=None):
    with ui.column().classes("eagle-log w-full gap-2"):
        with ui.row().classes("items-center gap-2"):
            ui.label("Process output").classes("text-subtitle2")
            paused = ui.checkbox("Pause auto-scroll", value=False)
            clear = ui.button("Clear").classes(BUTTON_CLASS)
            copy = ui.button("Copy visible log").classes(BUTTON_CLASS)
        output = ui.textarea().props("readonly autogrow=false spellcheck=false").classes(f"{TEXTAREA_CLASS} {MONO_CLASS} w-full h-[{height_px}px]")
    def set_buffer(buffer: ProcessLogBuffer):
        output.value = "\n".join(record.display() for record in buffer.snapshot()) or "No process output yet."
        output.update()
        if not paused.value:
            ui.run_javascript("document.querySelectorAll('.eagle-log textarea').forEach(e => e.scrollTop = e.scrollHeight)")
    def clear_log():
        if on_clear: on_clear()
        output.value = "No process output yet."; output.update()
    clear.on_click(clear_log)
    copy.on_click(lambda: ui.run_javascript("navigator.clipboard.writeText(document.querySelector('.eagle-log textarea')?.value || '')"))
    output.set_buffer = set_buffer
    return output