"""Interactive multi-objective analysis page."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from eagle.analysis.objectives import ObjectiveFilters
from eagle.analysis.records import discover_runs
from eagle_ui.controllers.analysis_controller import AnalysisController
from eagle_ui.state import AppState
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def build_analysis_view(controller: AnalysisController, state: AppState) -> None:
    frame = None
    directions: dict[str, str] = {}
    run_select = ui.select({}, label="Run").classes(f"{INPUT_CLASS} w-full")
    with ui.grid(columns=4).classes(f"{CARD_CLASS} w-full gap-3"):
        generation_min = ui.number("Generation from", min=0)
        generation_max = ui.number("Generation to", min=0)
        statuses = ui.select([], label="Status", multiple=True)
        operators = ui.select([], label="Operator", multiple=True)
        candidate_id = ui.input("Candidate ID contains")
        failures = ui.select([], label="Failure category", multiple=True)
        objective = ui.select([], label="Distribution objective")
        x_objective = ui.select([], label="Scatter X")
        y_objective = ui.select([], label="Scatter Y")
    with ui.row().classes("gap-2"):
        ui.button("Refresh runs", on_click=lambda: refresh_runs()).classes(BUTTON_CLASS)
        ui.button("Apply filters", on_click=lambda: render()).classes(BUTTON_CLASS)
    distribution = ui.echart({}).classes("w-full h-[440px]")
    scatter = ui.echart({}).classes("w-full h-[440px]")
    pareto_candidates = ui.select({}, label="Pareto candidate inspection").classes(f"{INPUT_CLASS} w-full")
    summary = ui.table(
        columns=[{"name": name, "label": name, "field": name} for name in ("generation", "min", "max", "mean", "median", "success_count", "failure_count")],
        rows=[],
        row_key="generation",
    ).classes("w-full")

    async def refresh_runs() -> None:
        runs = await asyncio.to_thread(discover_runs, state.repository_root / "runs")
        run_select.options = {str(item.path): f"{item.run_id} · {item.status}" for item in runs}
        run_select.update()

    async def load_run() -> None:
        nonlocal frame, directions
        if not run_select.value:
            return
        run_dir = Path(str(run_select.value))
        try:
            frame = await asyncio.to_thread(controller.load, run_dir)
            directions = await asyncio.to_thread(controller.directions, run_dir)
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot load objective artifacts from {run_dir}: {exc}", type="negative")
            return
        state.selection.run_dir = run_dir
        names = controller.objectives(frame)
        for control in (objective, x_objective, y_objective):
            control.options = names
        if names:
            objective.value = names[0]
            x_objective.value = names[0]
            y_objective.value = names[min(1, len(names) - 1)]
        statuses.options = sorted(str(value) for value in frame["status"].dropna().unique())
        operators.options = sorted(str(value) for value in frame["operator"].dropna().unique())
        failures.options = sorted(str(value) for value in frame["failure_category"].dropna().unique())
        generation_min.value = int(frame["generation"].min()) if not frame.empty else None
        generation_max.value = int(frame["generation"].max()) if not frame.empty else None
        for control in (objective, x_objective, y_objective, statuses, operators, failures, generation_min, generation_max):
            control.update()
        render()

    def render() -> None:
        if frame is None or not objective.value or not x_objective.value or not y_objective.value:
            return
        filtered = controller.filter(frame, ObjectiveFilters(
            generation_min=int(generation_min.value) if generation_min.value is not None else None,
            generation_max=int(generation_max.value) if generation_max.value is not None else None,
            statuses=tuple(statuses.value or ()),
            operators=tuple(operators.value or ()),
            candidate_id=str(candidate_id.value or ""),
            failure_categories=tuple(failures.value or ()),
        ))
        pareto = controller.pareto(filtered, (str(x_objective.value), str(y_objective.value)), directions)
        pareto_ids = set(pareto["candidate_id"].astype(str))
        distribution.options = controller.distribution_plot(filtered, str(objective.value))
        scatter.options = controller.scatter_plot(filtered, str(x_objective.value), str(y_objective.value), pareto_ids)
        distribution.update()
        scatter.update()
        pareto_candidates.options = {candidate: candidate for candidate in sorted(pareto_ids)}
        pareto_candidates.update()
        stats = controller.statistics(filtered, str(objective.value))
        summary.rows = stats.round(4).to_dict(orient="records")
        summary.update()

    run_select.on_value_change(lambda _: load_run())
    pareto_candidates.on_value_change(lambda event: setattr(state.selection, "candidate_id", str(event.value) if event.value else None))
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Timing Analysis").classes("text-h6")
        timing_status = ui.label("Select a run to inspect persisted timing.")
        with ui.grid(columns=2).classes("w-full gap-3"):
            generation_timing_chart = ui.echart({}).classes("w-full h-[320px]")
            operation_timing_chart = ui.echart({}).classes("w-full h-[320px]")
            llm_stage_chart = ui.echart({}).classes("w-full h-[320px]")
            llm_model_chart = ui.echart({}).classes("w-full h-[320px]")
        timing_table = ui.table(
            columns=[{"name": name, "label": name, "field": name} for name in ("candidate_id", "operation", "duration_seconds", "status")],
            rows=[],
            row_key="candidate_id",
        ).classes("w-full")

    async def load_timing() -> None:
        if not run_select.value:
            return
        run_dir = Path(str(run_select.value))
        try:
            summary = await asyncio.to_thread(controller.timing, run_dir)
            plots = await asyncio.to_thread(controller.timing_plots, run_dir)
        except (OSError, ValueError) as exc:
            timing_status.set_text(f"Cannot load timing artifacts: {exc}")
            return
        timing_status.set_text(f"Run duration: {summary['total_run_duration_seconds']:.4f}s | Requests: {len(summary['llm_requests'])}")
        generation_timing_chart.options = plots["generation_duration"]
        operation_timing_chart.options = plots["operation_breakdown"]
        llm_stage_chart.options = plots["llm_by_stage"]
        llm_model_chart.options = plots["llm_by_model"]
        for chart in (generation_timing_chart, operation_timing_chart, llm_stage_chart, llm_model_chart):
            chart.update()
        timing_table.rows = summary["operation_records"][:20]
        timing_table.update()

    run_select.on_value_change(lambda _: load_timing())
    ui.timer(0.1, refresh_runs, once=True)
