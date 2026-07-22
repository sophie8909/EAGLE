"""Reusable run selector backed by canonical run discovery."""

from nicegui import ui

from eagle_ui.theme import INPUT_CLASS


def create_run_selector(*, label: str = "Run"):
    return ui.select({}, label=label).classes(f"{INPUT_CLASS} w-full")
