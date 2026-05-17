"""Live analysis view."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    TABLE_CLASS,
    TEXTAREA_CLASS,
    height_class,
)


def build_analysis_view(state: Any) -> dict[str, Any]:
    """Build live GA/MO and timing analysis panels."""
    controls: dict[str, Any] = {}

    async def refresh_analysis() -> None:
        try:
            summary, body = await asyncio.to_thread(services.build_analysis, state.run.current_run_dir)
        except (OSError, ValueError) as exc:
            summary, body = "Analysis load error", str(exc)
        state.analysis.summary = summary
        state.analysis.body = body
        summary_label.set_text(summary)
        body_text.value = body
        body_text.update()

    async def refresh_timing() -> None:
        try:
            summary, rows, body = await asyncio.to_thread(services.build_timing, state.run.current_run_dir)
        except (OSError, ValueError) as exc:
            summary, rows, body = "Timing load error", [], str(exc)
        state.analysis.timing_summary = summary
        state.analysis.timing_rows = rows
        state.analysis.timing_body = body
        timing_summary_label.set_text(summary)
        timing_table.rows = rows
        timing_table.update()
        timing_text.value = body
        timing_text.update()

    async def refresh_all() -> None:
        await refresh_analysis()
        await refresh_timing()

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Analysis").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            summary_label = ui.label(state.analysis.summary)
            ui.button("Refresh analysis", on_click=refresh_all).classes(BUTTON_CLASS)
        body_text = ui.textarea(value=state.analysis.body).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(300)} w-full"
        )

        ui.label("Timing").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-center gap-3"):
            timing_summary_label = ui.label(state.analysis.timing_summary)
            ui.button("Refresh timing", on_click=refresh_timing).classes(BUTTON_CLASS)
        timing_table = ui.table(
            columns=[
                {"name": "phase", "label": "Phase", "field": "phase", "align": "left"},
                {"name": "count", "label": "Count", "field": "count"},
                {"name": "total_sec", "label": "Total sec", "field": "total_sec"},
                {"name": "avg_sec", "label": "Avg sec", "field": "avg_sec"},
                {"name": "max_sec", "label": "Max sec", "field": "max_sec"},
            ],
            rows=[],
        ).classes(f"{TABLE_CLASS} w-full")
        timing_text = ui.textarea(value=state.analysis.timing_body).props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(300)} w-full"
        )

    controls["refresh_analysis"] = refresh_all
    return controls
