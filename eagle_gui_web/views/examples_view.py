"""Runtime examples inspection view."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.theme import BUTTON_CLASS, CARD_CLASS, MUTED_CLASS, SECTION_HEADER_CLASS, TABLE_CLASS
from eagle_gui_web.ui_actions import safe_click


def build_examples_view(state: Any) -> dict[str, Any]:
    """Build the read-only runtime examples view."""
    controls: dict[str, Any] = {}

    async def refresh() -> None:
        path, rows = await asyncio.to_thread(services.load_examples_pool, state)
        path_label.set_text(services.relative_or_absolute(path))
        examples_table.rows = rows
        examples_table.update()
        empty_label.set_visibility(not rows)

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Examples").classes(SECTION_HEADER_CLASS)
            ui.button("Refresh", on_click=safe_click(refresh, label="Refresh examples")).classes(BUTTON_CLASS)
        path_label = ui.label("").classes(MUTED_CLASS)
        empty_label = ui.label("No runtime examples found.").classes(MUTED_CLASS)
        examples_table = ui.table(
            columns=[
                {"name": "raw_move", "label": "raw_move", "field": "raw_move", "align": "left"},
                {"name": "unit_position", "label": "unit_position", "field": "unit_position", "align": "left"},
                {"name": "unit_type", "label": "unit_type", "field": "unit_type", "align": "left"},
                {"name": "action_type", "label": "action_type", "field": "action_type", "align": "left"},
            ],
            rows=[],
            row_key="id",
        ).classes(f"{TABLE_CLASS} w-full")

    controls["refresh"] = refresh
    ui.timer(0.1, refresh, once=True)
    return controls
