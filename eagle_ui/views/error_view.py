"""Error summary, trends, root causes, detail, and filtered export."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nicegui import ui

from eagle.analysis.records import discover_runs
from eagle_ui.controllers.error_controller import ErrorAnalysisController
from eagle_ui.state import AppState
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS, TEXTAREA_CLASS


def build_error_view(controller: ErrorAnalysisController, state: AppState) -> None:
    frame = None
    filtered = None
    total_candidates = 0
    generation_counts: dict[int, int] = {}
    run_dir: Path | None = None
    run_select = ui.select({}, label="Run").classes(f"{INPUT_CLASS} w-full")
    with ui.grid(columns=4).classes(f"{CARD_CLASS} w-full gap-3"):
        generation_min = ui.number("Generation from", min=0)
        generation_max = ui.number("Generation to", min=0)
        categories = ui.select([], label="Category", multiple=True)
        candidate_id = ui.input("Candidate ID contains")
        trend_metric = ui.select({"failure_count": "Failure count", "failure_rate": "Failure rate"}, value="failure_count", label="Trend metric")
        export_format = ui.select(["csv", "json"], value="csv", label="Export format")
        export_path = ui.input("Export path").classes("col-span-2")
    with ui.row().classes("gap-2"):
        ui.button("Refresh runs", on_click=lambda: refresh_runs()).classes(BUTTON_CLASS)
        ui.button("Apply filters", on_click=lambda: render()).classes(BUTTON_CLASS)
        ui.button("Export filtered", on_click=lambda: export()).classes(BUTTON_CLASS)
    summary_table = ui.table(columns=[{"name": name, "label": name, "field": name} for name in ("category", "count", "percent_all", "percent_failed")], rows=[], row_key="category").classes("w-full")
    trend_chart = ui.echart({}).classes("w-full h-[420px]")
    roots_table = ui.table(columns=[{"name": name, "label": name, "field": name} for name in ("category", "root_cause", "count", "representative_message", "candidate_ids")], rows=[], row_key="root_cause").classes("w-full")
    detail_select = ui.select({}, label="Candidate error detail").classes(f"{INPUT_CLASS} w-full")
    detail = ui.textarea("Full error detail").props("readonly").classes(f"{TEXTAREA_CLASS} font-mono w-full h-[600px]")

    async def refresh_runs() -> None:
        runs = await asyncio.to_thread(discover_runs, state.repository_root / "runs")
        run_select.options = {str(item.path): f"{item.run_id} · failures={item.failure_count}" for item in runs}
        run_select.update()

    async def load_run() -> None:
        nonlocal frame, total_candidates, generation_counts, run_dir
        if not run_select.value:
            return
        run_dir = Path(str(run_select.value))
        try:
            frame, total_candidates, generation_counts = await asyncio.to_thread(controller.load, run_dir)
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot load failure artifacts from {run_dir}: {exc}", type="negative")
            return
        categories.options = sorted(frame["category"].astype(str).unique()) if not frame.empty else []
        generation_min.value = int(frame["generation"].min()) if not frame.empty else None
        generation_max.value = int(frame["generation"].max()) if not frame.empty else None
        export_path.value = str(run_dir / "analysis" / "filtered_errors.csv")
        for control in (categories, generation_min, generation_max, export_path):
            control.update()
        render()

    def render() -> None:
        nonlocal filtered
        if frame is None:
            return
        filtered = controller.filter(
            frame,
            generation_min=int(generation_min.value) if generation_min.value is not None else None,
            generation_max=int(generation_max.value) if generation_max.value is not None else None,
            categories=tuple(categories.value or ()),
            candidate_id=str(candidate_id.value or ""),
        )
        summary = controller.summary(filtered, total_candidates=total_candidates, total_failed=len(frame))
        summary_table.rows = summary.round(2).to_dict(orient="records")
        summary_table.update()
        roots_table.rows = controller.root_causes(filtered).to_dict(orient="records")
        roots_table.update()
        trend = controller.trend(filtered, candidates_per_generation=generation_counts)
        metric = str(trend_metric.value)
        series = []
        for category, group in trend.groupby("category") if not trend.empty else []:
            series.append({"name": str(category), "type": "line", "data": [[int(row["generation"]), float(row[metric])] for _, row in group.iterrows()]})
        trend_chart.options = {
            "tooltip": {"trigger": "axis"},
            "legend": {"textStyle": {"color": "#e5e7eb"}},
            "xAxis": {"type": "value", "name": "Generation"},
            "yAxis": {"type": "value", "name": metric},
            "series": series,
        }
        trend_chart.update()
        detail_select.options = {str(value): str(value) for value in filtered["candidate_id"].astype(str)}
        detail_select.update()

    def show_detail() -> None:
        if filtered is None or not detail_select.value:
            return
        row = filtered.loc[filtered["candidate_id"].astype(str) == str(detail_select.value)].iloc[0]
        detail.value = json.dumps(row.to_dict(), ensure_ascii=False, indent=2)
        detail.update()
        state.selection.candidate_id = str(detail_select.value)

    async def export() -> None:
        if filtered is None or run_dir is None:
            return
        format_name = str(export_format.value)
        path = Path(str(export_path.value))
        if path.suffix.lower() != f".{format_name}":
            path = path.with_suffix(f".{format_name}")
            export_path.value = str(path)
            export_path.update()
        try:
            await asyncio.to_thread(controller.export, filtered, path, format_name)
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot export filtered errors to {path}: {exc}", type="negative")
            return
        ui.notify(f"Exported {path}", type="positive")

    run_select.on_value_change(lambda _: load_run())
    detail_select.on_value_change(lambda _: show_detail())
    trend_metric.on_value_change(lambda _: render())
    ui.timer(0.1, refresh_runs, once=True)
