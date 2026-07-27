"""Complete Analysis dashboard driven by one canonical view model."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle.analysis.dashboard import AnalysisViewModel
from eagle_ui.components.echart import replace_chart_options
from eagle_ui.controllers.analysis_controller import AnalysisController
from eagle_ui.state import AppState
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def _run_option_label(run_id: str, status: str) -> str:
    return f"{run_id} ??{status}"


def _empty_chart(title: str):
    return ui.echart({"title": {"text": title, "textStyle": {"color": "var(--eagle-text-muted)"}}}).classes("eagle-empty w-full h-[360px]")


def _line_options(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tooltip": {"trigger": "axis"}, "legend": {"textStyle": {"color": "#e5e7eb"}}, "xAxis": {"type": "category", "data": [row.get("generation") for row in rows]}, "yAxis": {"type": "value", "name": name}, "series": [{"name": name, "type": "line", "data": [row.get(name) for row in rows]}], "grid": {"left": "8%", "right": "4%", "bottom": "12%", "containLabel": True}}


def build_analysis_view(controller: AnalysisController, state: AppState) -> None:
    model: AnalysisViewModel | None = None
    load_version = 0
    run_select = ui.select({}, label="Experiment or run folder").classes(f"{INPUT_CLASS} w-full")
    folder_input = ui.input("Folder path (optional)").classes(f"{INPUT_CLASS} w-full")
    status = ui.label("Select a result folder to load analysis.")
    spinner = ui.spinner(size="2em").classes("hidden")
    refresh = ui.button("Refresh", on_click=lambda: refresh_sources()).classes(BUTTON_CLASS)
    run_selector = ui.select({}, label="Detected run").classes(f"{INPUT_CLASS} w-full")
    objective_select = ui.select({}, label="Objective").classes(f"{INPUT_CLASS} w-full")
    overview_table = ui.table(columns=[{"name": "field", "label": "Field", "field": "field"}, {"name": "value", "label": "Value", "field": "value"}], rows=[], row_key="field").classes("w-full")
    evolution_chart = _empty_chart("Evolution progress unavailable")
    population_chart = _empty_chart("Population progress unavailable")
    pareto_chart = _empty_chart("Multi-objective analysis unavailable")
    distribution_chart = _empty_chart("Objective distributions unavailable")
    operator_chart = _empty_chart("Operator analysis unavailable")
    timing_chart = _empty_chart("Timing analysis unavailable")
    error_table = ui.table(columns=[{"name": name, "label": name.replace("_", " ").title(), "field": name} for name in ("candidate_id", "generation", "operator", "stage", "category", "message")], rows=[], row_key="candidate_id").classes("w-full")
    candidate_table = ui.table(columns=[], rows=[], row_key="candidate_id").classes("w-full")
    candidate_detail = ui.textarea("Selected candidate details").props("readonly").classes("w-full h-[240px]")
    warnings = ui.label("").classes("text-warning")
    config = ui.textarea("Resolved configuration").props("readonly").classes("w-full h-[260px]")

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Run overview").classes("text-h6")
        overview_table
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Evolution progress").classes("text-h6")
        evolution_chart
        population_chart
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Multi-objective or ranking analysis").classes("text-h6")
        pareto_chart
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Objective distributions").classes("text-h6")
        distribution_chart
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Operator analysis").classes("text-h6")
        operator_chart
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("LLM request and pipeline timing").classes("text-h6")
        timing_chart
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Error analysis").classes("text-h6")
        error_table
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Candidate analysis and inspection").classes("text-h6")
        candidate_table
        candidate_detail
    with ui.expansion("Evaluation breakdown", value=False).classes(f"{CARD_CLASS} w-full"):
        evaluation = ui.label("Data unavailable")
    with ui.expansion("Configuration and reproducibility", value=False).classes(f"{CARD_CLASS} w-full"):
        config
    ui.label("Analysis status and partial-data warnings")
    warnings

    async def refresh_sources() -> None:
        try:
            sources = await asyncio.to_thread(controller.discover_sources, state.repository_root / "runs")
        except OSError as exc:
            status.set_text(f"Cannot discover result folders: {exc}")
            return
        options = {str(item.path): _run_option_label(item.run_id, item.status) for item in sources}
        run_select.options = options
        run_select.update()
        if run_select.value not in options:
            run_select.value = None
        run_select.update()

    async def load_path(path: Path) -> None:
        nonlocal model, load_version
        load_version += 1
        version = load_version
        model = None
        spinner.classes(remove="hidden")
        status.set_text(f"Loading {path}...")
        warnings.set_text("")
        clear_dashboard()
        try:
            loaded = await asyncio.to_thread(controller.load_dashboard, path)
        except (OSError, ValueError) as exc:
            if version != load_version:
                return
            status.set_text(f"Cannot parse analysis folder: {exc}")
            warnings.set_text("Fatal folder-loading error: " + str(exc))
            return
        finally:
            if version == load_version:
                spinner.classes(add="hidden")
        if version != load_version:
            return
        model = loaded
        state.selection.run_dir = loaded.run_dir
        run_selector.options = {str(item.path): _run_option_label(item.run_id, item.status) for item in loaded.run_options}
        run_selector.value = str(loaded.run_dir)
        run_selector.update()
        status.set_text(f"Loaded {loaded.run_dir.name} ({loaded.run_kind})")
        render(loaded)

    def clear_dashboard() -> None:
        overview_table.rows = []
        overview_table.update()
        for chart, title in ((evolution_chart, "Evolution progress unavailable"), (population_chart, "Population progress unavailable"), (pareto_chart, "Multi-objective analysis unavailable"), (distribution_chart, "Objective distributions unavailable"), (operator_chart, "Operator analysis unavailable"), (timing_chart, "Timing analysis unavailable")):
            replace_chart_options(chart, {"title": {"text": title, "textStyle": {"color": "#94a3b8"}}, "series": []})
            chart.update()
        error_table.rows = []
        error_table.update()
        candidate_table.rows = []
        candidate_table.update()
        config.value = ""
        evaluation.set_text("Data unavailable")

    def render(loaded: AnalysisViewModel) -> None:
        overview_table.rows = [{"field": key.replace("_", " ").title(), "value": value} for key, value in loaded.overview.items() if key != "summary" and value is not None]
        overview_table.update()
        names = loaded.overview.get("objective_names") or []
        objective = names[0] if names else None
        stats = loaded.evolution.get("objectives", {}).get(objective, []) if objective else []
        if stats:
            replace_chart_options(evolution_chart, _line_options("mean", stats))
        population = loaded.evolution.get("population", [])
        if population:
            replace_chart_options(population_chart, _line_options("count", population))
        if loaded.pareto.get("available"):
            points = [{"name": row.get("candidate_id"), "value": [row.get(loaded.pareto["x"]), row.get(loaded.pareto["y"])], "itemStyle": {"color": "#b08d57" if row.get("candidate_id") in loaded.pareto["pareto_ids"] else "#38bdf8"}} for row in loaded.pareto["rows"]]
            replace_chart_options(pareto_chart, {"tooltip": {"trigger": "item"}, "xAxis": {"type": "value", "name": loaded.pareto["x"]}, "yAxis": {"type": "value", "name": loaded.pareto["y"]}, "series": [{"type": "scatter", "data": points}]})
        elif objective:
            ranked = sorted(loaded.candidates, key=lambda row: (row.get(objective) is None, row.get(objective, 0)), reverse=loaded.directions.get(objective, "maximize") == "minimize")
            replace_chart_options(pareto_chart, {"title": {"text": "Single-objective ranking"}, "xAxis": {"type": "category", "data": [row.get("candidate_id") for row in ranked]}, "yAxis": {"type": "value", "name": objective}, "series": [{"type": "bar", "data": [row.get(objective) for row in ranked]}]})
        if objective and loaded.distributions.get(objective, {}).get("values"):
            values = loaded.distributions[objective]["values"]
            replace_chart_options(distribution_chart, {"xAxis": {"type": "category", "data": list(range(len(values)))}, "yAxis": {"type": "value", "name": objective}, "series": [{"type": "bar", "data": values}]})
        if loaded.operators:
            replace_chart_options(operator_chart, {"xAxis": {"type": "category", "data": list(loaded.operators)}, "yAxis": {"type": "value", "name": "count"}, "series": [{"type": "bar", "name": "usage", "data": [item["usage_count"] for item in loaded.operators.values()]}, {"type": "bar", "name": "successful", "data": [item["successful_offspring"] for item in loaded.operators.values()]}]})
        requests = loaded.timing.get("llm_requests", [])
        if requests:
            replace_chart_options(timing_chart, {"xAxis": {"type": "category", "data": list(range(len(requests)))}, "yAxis": {"type": "value", "name": "seconds"}, "series": [{"type": "line", "name": "request duration", "data": [item.get("duration_seconds") for item in requests]}]})
        error_table.rows = loaded.errors["rows"]
        error_table.update()
        candidate_table.columns = [{"name": key, "label": key.replace("_", " ").title(), "field": key} for key in ("candidate_id", "generation", "operator", "status", "pareto") + tuple(names)]
        candidate_table.rows = loaded.candidates
        candidate_table.update()
        warnings.set_text("; ".join(loaded.warnings) if loaded.warnings else "All available analysis artifacts loaded.")
        config.value = __import__("json").dumps(loaded.configuration, ensure_ascii=False, indent=2)
        evaluation.set_text("Evaluation metrics are available in candidate artifacts." if loaded.evaluation["available"] else "Data unavailable: no generic evaluator metrics were recorded.")
        for chart in (evolution_chart, population_chart, pareto_chart, distribution_chart, operator_chart, timing_chart):
            chart.update()

    def select_candidate(event: Any) -> None:
        if model is None:
            return
        args = getattr(event, "args", {})
        candidate_id = str(args.get("id") or args.get("candidate_id") or "") if isinstance(args, dict) else ""
        row = next((item for item in model.candidates if str(item.get("candidate_id")) == candidate_id), None)
        if row is not None:
            candidate_detail.value = __import__("json").dumps(row, ensure_ascii=False, indent=2, default=str)
            candidate_detail.update()
    async def select_source() -> None:
        if run_select.value:
            await load_path(Path(str(run_select.value)))

    async def select_folder() -> None:
        if folder_input.value:
            await load_path(Path(str(folder_input.value)))

    async def select_run() -> None:
        if run_selector.value:
            await load_path(Path(str(run_selector.value)))


    async def rerender() -> None:
        if model is not None:
            render(model)

    objective_select.on_value_change(lambda _: rerender())
    candidate_table.on("rowClick", select_candidate)
    run_selector.on_value_change(lambda _: select_run())
    run_select.on_value_change(lambda _: select_source())
    folder_input.on_value_change(lambda _: select_folder())
    ui.timer(0.1, refresh_sources, once=True)
