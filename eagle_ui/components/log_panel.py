"""Scrollable read-only log panel."""

from nicegui import ui

from eagle_ui.theme import MONO_CLASS, TEXTAREA_CLASS


def create_log_panel(*, height_px: int = 360):
    return ui.textarea(label="stdout / stderr").props("readonly autogrow=false").classes(
        f"{TEXTAREA_CLASS} {MONO_CLASS} w-full h-[{height_px}px]"
    )
