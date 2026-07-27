"""Interactive multi-objective analysis page."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from eagle.analysis.records import discover_runs
from eagle_ui.controllers.analysis_controller import AnalysisController
from eagle_ui.components.echart import replace_chart_options
from eagle_ui.state import AppState
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def _run_option_label(run_id: str, status: str) -> str:
    return f"{run_id} · {status}"


def build_analysis_view(controller: AnalysisController, state: AppState) -> None:
    frame = None
    directions: dict[str, str] = {}
    run_select = ui.select({}, label="Run").classes(f"{INPUT_CLASS} w-full")
    ui.button("Refresh runs", on_click=lambda: refresh_runs()).classes(BUTTON_CLASS)
    distribution = ui.echart({"title": {"text": "Load a run to view objective distribution", "textStyle": {"color": "var(--eagle-text-muted)"}}}).classes("eagle-empty w-full h-[440px]")
    scatter = ui.echart({"title": {"text": "Load a run to view objective scatter", "textStyle": {"color": "var(--eagle-text-muted)"}}}).classes("eagle-empty w-full h-[440px]")
    pareto_candidates = ui.select({}, label="Pareto candidate inspection").classes(f"{INPUT_CLASS} w-full")
    summary = ui.table(
        columns=[{"name": name, "label": name, "field": name} for name in ("generation", "min", "max", "mean", "median", "success_count", "failure_count")],
        rows=[],
        row_key="generation",
    ).classes("w-full")

    async def refresh_runs() -> None:
        runs = await asyncio.to_thread(discover_runs, state.repository_root / "runs")
        run_select.options = {
            str(item.path): _run_option_label(item.run_id, item.status)
            for item in runs
        }
        run_select.update()

    async def load_run() -> None:
        nonlocal frame, directions
        if not run_select.value:
            return
        run_dir = Path(str(run_select.value))
        try:
            frame, directions, timing_summary, timing_plots = await asyncio.to_thread(
                controller.load_run,
                run_dir,
            )
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot load analysis artifacts from {run_dir}: {exc}", type="negative")
            return
        state.selection.run_dir = run_dir
        names = controller.objectives(frame)
        render_objective_charts(names)
        render_timing(timing_summary, timing_plots)

    def render_objective_charts(names: list[str]) -> None:
        if frame is None or not names:
            return
        objective = names[0]
        x_objective = names[0]
        y_objective = names[min(1, len(names) - 1)]
        pareto = controller.pareto(frame, (x_objective, y_objective), directions)
        pareto_ids = set(pareto["candidate_id"].astype(str))
        replace_chart_options(distribution, controller.distribution_plot(filtered, str(objective.value)))
        replace_chart_options(scatter, controller.scatter_plot(filtered, str(x_objective.value), str(y_objective.value), pareto_ids))
        distribution.update()
        scatter.update()
        pareto_candidates.options = {candidate: candidate for candidate in sorted(pareto_ids)}
        pareto_candidates.update()
        stats = controller.statistics(frame, objective)
        summary.rows = stats.round(4).to_dict(orient="records")
        summary.update()

    pareto_candidates.on_value_change(lambda event: setattr(state.selection, "candidate_id", str(event.value) if event.value else None))
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Timing Analysis").classes("text-h6")
        timing_status = ui.label("Select a run to inspect persisted timing.")
        with ui.grid(columns=2).classes("w-full gap-3"):
            generation_timing_chart = ui.echart({"title": {"text": "No timing data loaded", "textStyle": {"color": "var(--eagle-text-muted)"}}}).classes("eagle-empty w-full h-[320px]")
            operation_timing_chart = ui.echart({"title": {"text": "No operation timing data", "textStyle": {"color": "var(--eagle-text-muted)"}}}).classes("eagle-empty w-full h-[320px]")
            llm_stage_chart = ui.echart({"title": {"text": "No LLM stage timing data", "textStyle": {"color": "var(--eagle-text-muted)"}}}).classes("eagle-empty w-full h-[320px]")
            llm_model_chart = ui.echart({"title": {"text": "No LLM model timing data", "textStyle": {"color": "var(--eagle-text-muted)"}}}).classes("eagle-empty w-full h-[320px]")
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
            timing_summary = await asyncio.to_thread(controller.timing, run_dir)
            timing_plots = await asyncio.to_thread(controller.timing_plots, run_dir)
        except (OSError, ValueError) as exc:
            timing_status.set_text(f"Cannot load timing artifacts: {exc}")
            return
        timing_status.set_text(
            f"Run duration: {timing_summary['total_run_duration_seconds']:.4f}s"
            f" | Requests: {len(timing_summary['llm_requests'])}"
        )
        replace_chart_options(generation_timing_chart, timing_plots["generation_duration"])
        replace_chart_options(operation_timing_chart, timing_plots["operation_breakdown"])
        replace_chart_options(llm_stage_chart, timing_plots["llm_by_stage"])
        replace_chart_options(llm_model_chart, timing_plots["llm_by_model"])
        for chart in (generation_timing_chart, operation_timing_chart, llm_stage_chart, llm_model_chart):
            chart.update()
        timing_table.rows = timing_summary["operation_records"][:20]
        timing_table.update()

    run_select.on_value_change(lambda _: load_run())
    ui.timer(0.1, refresh_runs, once=True)
