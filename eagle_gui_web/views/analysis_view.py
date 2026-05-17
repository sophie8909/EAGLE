"""Live analysis view."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle.analysis.evolution_result_analysis import parse_time_analysis
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
            time_analysis = await asyncio.to_thread(_build_time_analysis_text, state.run.current_run_dir)
        except (OSError, ValueError) as exc:
            summary, rows, body = "Timing load error", [], str(exc)
            time_analysis = str(exc)
        state.analysis.timing_summary = summary
        state.analysis.timing_rows = rows
        state.analysis.timing_body = body
        time_analysis_text.value = time_analysis
        time_analysis_text.update()
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

        ui.label("Time Analysis").classes(SECTION_HEADER_CLASS)
        time_analysis_text = ui.textarea(value="No timing data found.").props("readonly").classes(
            f"{TEXTAREA_CLASS} {height_class(150)} w-full"
        )
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


def _build_time_analysis_text(run_dir: Path | None) -> str:
    """Render a compact time-analysis summary from selected-run timing text."""
    if run_dir is None:
        return "No timing data found."
    log_text = _read_time_analysis_text(run_dir)
    timing = parse_time_analysis(log_text)
    if not timing:
        return "No timing data found."
    labels = [
        ("total_runtime", "Total runtime"),
        ("generation_runtime", "Generation runtime"),
        ("average_generation_time", "Average generation time"),
        ("evaluation_time", "Evaluation time"),
        ("llm_call_time", "LLM call time"),
    ]
    return "\n".join(f"{label}: {_format_seconds(timing[key])}" for key, label in labels if key in timing)


def _read_time_analysis_text(run_dir: Path) -> str:
    """Read timing artifacts without touching GA/MO/final-test analysis files."""
    parts: list[str] = []
    for filename in ("timing_summary.json", "timing_events.jsonl", "timing_report.md"):
        path = run_dir / filename
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _format_seconds(value: object) -> str:
    """Format seconds for the compact time-analysis panel."""
    return f"{float(value):.3f} sec"
