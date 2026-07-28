"""Complete Analysis dashboard driven by one canonical view model."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle.analysis.dashboard import (
    AnalysisViewModel,
    filter_candidate_rows,
)
from eagle_ui.components.echart import replace_chart_options
from eagle_ui.controllers.analysis_controller import (
    AnalysisController,
    AnalysisLoadCoordinator,
)
from eagle_ui.state import AppState
from eagle_ui.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    COLORS,
    INPUT_CLASS,
    TEXTAREA_CLASS,
)


CHART_CLASS = "w-full h-[360px]"
TABLE_PROPS = "dense flat wrap-cells"


def _run_option_label(run_id: str, status: str) -> str:
    return f"{run_id} · {status}"


def build_analysis_view(controller: AnalysisController, state: AppState) -> None:
    """Build a page whose only file-reading boundary is ``load_dashboard``."""

    model: AnalysisViewModel | None = None
    coordinator = AnalysisLoadCoordinator()
    active_selected_path: Path | None = None
    experiment_options: tuple[Any, ...] = ()
    updating_run_selector = False

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Analysis source").classes("text-h6")
        with ui.grid(columns=2).classes("w-full gap-3"):
            source_select = ui.select(
                {}, label="Discovered experiment or run"
            ).classes(f"{INPUT_CLASS} w-full")
            folder_input = (
                ui.input("Experiment or run folder path")
                .props("debounce=400")
                .classes(f"{INPUT_CLASS} w-full")
            )
        with ui.row().classes("items-center gap-3"):
            refresh_active = ui.button("Refresh active run").classes(BUTTON_CLASS)
            refresh_sources_button = ui.button("Rescan folders").classes(
                BUTTON_CLASS
            )
            spinner = ui.spinner(size="2em")
            spinner.set_visibility(False)
            status = ui.label("Select a result folder to load analysis.")
        run_selector = ui.select({}, label="Run in experiment").classes(
            f"{INPUT_CLASS} w-full"
        )
        run_selector.set_visibility(False)
        fatal_error = ui.label("").classes("eagle-error w-full")
        fatal_error.set_visibility(False)
        warning_summary = ui.label("").classes("text-warning w-full")
        warning_summary.set_visibility(False)

    overview_labels: dict[str, Any] = {}
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Run overview").classes("text-h6")
        overview_status = ui.label("Data unavailable: select a result folder.")
        with ui.grid(columns=4).classes("w-full gap-3"):
            for key in (
                "run_id",
                "status",
                "algorithm",
                "application",
                "random_seed",
                "total_duration_seconds",
                "completed_generations",
                "configured_generations",
                "population_size",
                "number_of_objectives",
                "total_candidate_evaluations",
                "successful_evaluations",
                "failed_evaluations",
                "failure_rate",
                "total_llm_requests",
                "total_token_usage",
            ):
                with ui.card().classes("w-full"):
                    ui.label(key.replace("_", " ").title()).classes(
                        "text-caption text-grey-5"
                    )
                    overview_labels[key] = ui.label("—").classes("text-h6")
        overview_table = _table(("field", "value"), row_key="field")

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Evolution progress").classes("text-h6")
        evolution_status = ui.label("Data unavailable: select a result folder.")
        objective_select = ui.select({}, label="Objective or metric").classes(
            f"{INPUT_CLASS} w-full"
        )
        evolution_chart = _chart("Evolution progress unavailable")
        population_chart = _chart("Population progress unavailable")
        evolution_table = _table(
            (
                "generation",
                "best",
                "mean",
                "median",
                "worst",
                "valid_count",
                "failure_count",
            ),
            row_key="generation",
        )

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Multi-objective or ranking analysis").classes("text-h6")
        pareto_status = ui.label("Data unavailable: select a result folder.")
        with ui.row().classes("w-full gap-3"):
            x_objective = ui.select({}, label="X objective").classes(
                f"{INPUT_CLASS} min-w-[260px]"
            )
            y_objective = ui.select({}, label="Y objective").classes(
                f"{INPUT_CLASS} min-w-[260px]"
            )
            pareto_summary = ui.label("")
        pareto_chart = _chart("Multi-objective analysis unavailable")
        hypervolume_chart = _chart("Hypervolume history unavailable")

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Objective distributions").classes("text-h6")
        distribution_status = ui.label(
            "Data unavailable: select a result folder."
        )
        distribution_chart = _chart("Objective distributions unavailable")
        distribution_table = _table(
            (
                "objective",
                "min",
                "max",
                "mean",
                "median",
                "stddev",
                "valid_count",
                "failed_count",
            ),
            row_key="objective",
        )

    with ui.expansion("Operator analysis", value=False).classes(
        f"{CARD_CLASS} w-full"
    ):
        operator_status = ui.label("Data unavailable: select a result folder.")
        operator_chart = _chart("Operator analysis unavailable")
        operator_history_chart = _chart("Operator history unavailable")
        operator_table = _table(
            (
                "operator",
                "usage_count",
                "usage_share",
                "successful_offspring",
                "success_rate",
                "mean_reward_or_improvement",
                "offspring_validity_rate",
                "compilation_failure_rate",
                "evaluation_failure_rate",
            ),
            row_key="operator",
        )

    with ui.expansion("LLM request and pipeline timing", value=False).classes(
        f"{CARD_CLASS} w-full"
    ):
        timing_status = ui.label("Data unavailable: select a result folder.")
        with ui.grid(columns=2).classes("w-full gap-3"):
            generation_timing_chart = _chart("Generation timing unavailable")
            operation_timing_chart = _chart("Operation timing unavailable")
            request_order_chart = _chart("LLM request timing unavailable")
            request_generation_chart = _chart(
                "LLM timing by generation unavailable"
            )
            role_timing_chart = _chart("LLM role timing unavailable")
            model_timing_chart = _chart("LLM model timing unavailable")
        ui.label("Slowest operations").classes("text-subtitle1")
        slow_operation_table = _table(
            ("candidate_id", "operation", "duration_seconds", "status"),
            row_key="candidate_id",
        )
        ui.label("Slowest individual LLM requests").classes("text-subtitle1")
        slow_request_table = _table(
            (
                "candidate_id",
                "generation",
                "operation_stage",
                "model_id",
                "duration_seconds",
                "status",
            ),
            row_key="request_correlation_id",
        )
        ui.label("Timing statistics").classes("text-subtitle1")
        timing_statistics_table = _table(
            (
                "group",
                "count",
                "total",
                "mean",
                "median",
                "p95",
                "maximum",
                "run_time_percent",
            ),
            row_key="group",
        )

    with ui.expansion("Error analysis", value=False).classes(
        f"{CARD_CLASS} w-full"
    ):
        error_status = ui.label("Data unavailable: select a result folder.")
        error_search = ui.input("Search errors").classes(
            f"{INPUT_CLASS} w-full"
        )
        with ui.grid(columns=3).classes("w-full gap-3"):
            error_stage_chart = _chart("Errors by stage unavailable")
            error_category_chart = _chart("Errors by category unavailable")
            error_generation_chart = _chart("Errors by generation unavailable")
        error_table = _table(
            (
                "candidate_id",
                "generation",
                "operator",
                "stage",
                "category",
                "message",
                "artifact_path",
                "timestamp",
            ),
            row_key="candidate_id",
            rows_per_page=25,
        )
        error_summary_table = _table(
            ("dimension", "value", "count", "failure_rate"),
            row_key="dimension",
        )
        error_detail = _viewer("Selected error details", 300)

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Candidate analysis").classes("text-h6")
        candidate_status = ui.label("Data unavailable: select a result folder.")
        with ui.grid(columns=4).classes("w-full gap-3"):
            candidate_search = ui.input("Candidate ID").classes(
                f"{INPUT_CLASS} w-full"
            )
            generation_filter = ui.select(
                {}, label="Generation"
            ).classes(f"{INPUT_CLASS} w-full")
            status_filter = ui.select(
                {
                    "": "All statuses",
                    "success": "Successful",
                    "failed": "Failed",
                },
                value="",
                label="Evaluation status",
            ).classes(f"{INPUT_CLASS} w-full")
            pareto_filter = ui.select(
                {
                    "": "All candidates",
                    "pareto": "Pareto optimal",
                    "dominated": "Not Pareto optimal",
                },
                value="",
                label="Pareto status",
            ).classes(f"{INPUT_CLASS} w-full")
        candidate_table = _table(
            ("candidate_id", "generation", "operator", "status", "pareto"),
            row_key="candidate_id",
            rows_per_page=25,
        )
        candidate_detail = _viewer("Selected candidate details", 520)

    with ui.expansion("Evaluation breakdown", value=False).classes(
        f"{CARD_CLASS} w-full"
    ):
        evaluation_status = ui.label(
            "Data unavailable: select a result folder."
        )
        evaluation_metric = ui.select({}, label="Evaluation metric").classes(
            f"{INPUT_CLASS} w-full"
        )
        evaluation_chart = _chart("Evaluation metric trend unavailable")
        evaluation_summary_table = _table(
            (
                "metric",
                "min",
                "max",
                "mean",
                "median",
                "stddev",
                "count",
                "missing_or_failed_count",
            ),
            row_key="metric",
        )
        ui.label("Recorded final-test results").classes("text-subtitle1")
        final_test_table = _table(
            (
                "final_test_id",
                "status",
                "formal",
                "tested_candidate_ids",
                "expected_matches",
                "completed_matches",
                "incomplete_matches",
                "path",
            ),
            row_key="final_test_id",
        )

    with ui.expansion(
        "Configuration and reproducibility", value=False
    ).classes(f"{CARD_CLASS} w-full"):
        configuration_status = ui.label(
            "Data unavailable: select a result folder."
        )
        configuration = _viewer("Resolved configuration and run metadata", 600)

    def section_status(
        label: Any,
        loaded: AnalysisViewModel,
        section: str,
        available: bool,
        available_text: str,
    ) -> None:
        messages = loaded.section_warnings.get(section, ())
        if available:
            text = available_text
            if messages:
                text += " · Warning: " + " ".join(messages)
        elif messages:
            text = "Data unavailable: " + " ".join(messages)
        else:
            text = "Data unavailable: the required artifact was not recorded."
        label.set_text(text)

    def clear_dashboard() -> None:
        for label in (
            overview_status,
            evolution_status,
            pareto_status,
            distribution_status,
            operator_status,
            timing_status,
            error_status,
            candidate_status,
            evaluation_status,
            configuration_status,
        ):
            label.set_text("Loading…")
        for label in overview_labels.values():
            label.set_text("—")
        overview_table.rows = []
        evolution_table.rows = []
        distribution_table.rows = []
        operator_table.rows = []
        slow_operation_table.rows = []
        slow_request_table.rows = []
        timing_statistics_table.rows = []
        error_table.rows = []
        error_summary_table.rows = []
        candidate_table.rows = []
        evaluation_summary_table.rows = []
        final_test_table.rows = []
        for table in (
            overview_table,
            evolution_table,
            distribution_table,
            operator_table,
            slow_operation_table,
            slow_request_table,
            timing_statistics_table,
            error_table,
            error_summary_table,
            candidate_table,
            evaluation_summary_table,
            final_test_table,
        ):
            table.update()
        for chart, title in (
            (evolution_chart, "Evolution progress unavailable"),
            (population_chart, "Population progress unavailable"),
            (pareto_chart, "Multi-objective analysis unavailable"),
            (hypervolume_chart, "Hypervolume history unavailable"),
            (distribution_chart, "Objective distributions unavailable"),
            (operator_chart, "Operator analysis unavailable"),
            (operator_history_chart, "Operator history unavailable"),
            (generation_timing_chart, "Generation timing unavailable"),
            (operation_timing_chart, "Operation timing unavailable"),
            (request_order_chart, "LLM request timing unavailable"),
            (
                request_generation_chart,
                "LLM timing by generation unavailable",
            ),
            (role_timing_chart, "LLM role timing unavailable"),
            (model_timing_chart, "LLM model timing unavailable"),
            (error_stage_chart, "Errors by stage unavailable"),
            (error_category_chart, "Errors by category unavailable"),
            (error_generation_chart, "Errors by generation unavailable"),
            (evaluation_chart, "Evaluation metric trend unavailable"),
        ):
            _replace_chart(chart, _empty_options(title))
        candidate_detail.value = ""
        error_detail.value = ""
        configuration.value = ""
        for viewer in (candidate_detail, error_detail, configuration):
            viewer.update()

    def render(loaded: AnalysisViewModel) -> None:
        overview = loaded.overview
        for key, label in overview_labels.items():
            label.set_text(_display(overview.get(key), key))
        overview_table.rows = [
            {
                "field": key.replace("_", " ").title(),
                "value": _display(value, key),
            }
            for key, value in overview.items()
            if value is not None
        ]
        overview_table.update()
        section_status(
            overview_status,
            loaded,
            "overview",
            bool(overview),
            f"Loaded run {loaded.run_dir.name}.",
        )

        names = list(overview.get("objective_names") or [])
        objective_select.options = {name: name for name in names}
        if objective_select.value not in names:
            objective_select.value = names[0] if names else None
        objective_select.update()
        x_objective.options = {name: name for name in names}
        y_objective.options = {name: name for name in names}
        if x_objective.value not in names:
            x_objective.value = names[0] if names else None
        if y_objective.value not in names:
            y_objective.value = names[1] if len(names) > 1 else None
        x_objective.update()
        y_objective.update()

        generations = sorted(
            {int(row.get("generation", 0)) for row in loaded.candidates}
        )
        generation_filter.options = {"": "All generations", **{
            str(value): f"Generation {value}" for value in generations
        }}
        if str(generation_filter.value or "") not in generation_filter.options:
            generation_filter.value = ""
        generation_filter.update()

        candidate_columns = (
            "candidate_id",
            "generation",
            "parent_ids",
            "operator",
            "rank",
            "crowding_distance",
            "pareto",
            *names,
            "evaluation_status",
            "compilation_status",
            "validation_status",
            "token_usage",
            "generation_duration_seconds",
        )
        candidate_table.columns = _columns(candidate_columns)
        candidate_table.update()

        render_objective()
        render_pareto()
        render_operators(loaded)
        render_timing(loaded)
        render_errors(loaded)
        render_candidates()
        render_evaluation(loaded)
        configuration.value = json.dumps(
            loaded.configuration, ensure_ascii=False, indent=2, default=str
        )
        configuration.update()
        section_status(
            configuration_status,
            loaded,
            "configuration",
            bool(loaded.configuration.get("resolved_config")),
            "Resolved run configuration loaded.",
        )

        if loaded.warnings:
            warning_summary.set_text(
                f"{len(loaded.warnings)} partial-data warning(s). "
                "Each affected section is marked below."
            )
            warning_summary.set_visibility(True)
        else:
            warning_summary.set_visibility(False)

    def render_objective() -> None:
        if model is None:
            return
        objective = str(objective_select.value or "")
        rows = model.evolution.get("objectives", {}).get(objective, [])
        if rows:
            _replace_chart(
                evolution_chart, _evolution_options(objective, rows)
            )
            evolution_table.rows = rows
        else:
            _replace_chart(
                evolution_chart,
                _empty_options("Objective history unavailable"),
            )
            evolution_table.rows = []
        evolution_table.update()
        _replace_chart(
            population_chart, _population_options(model.evolution)
        )
        distribution = model.distributions.get(objective, {})
        histogram = distribution.get("histogram", [])
        _replace_chart(
            distribution_chart,
            _histogram_options(objective, histogram)
            if histogram
            else _empty_options("Valid objective distribution unavailable"),
        )
        distribution_table.rows = [
            {"objective": name, **values}
            for name, values in model.distributions.items()
        ]
        distribution_table.update()
        section_status(
            evolution_status,
            model,
            "objectives",
            bool(rows),
            f"Showing {objective}; direction: "
            f"{model.directions.get(objective, 'not recorded')}.",
        )
        section_status(
            distribution_status,
            model,
            "objectives",
            bool(histogram),
            "Failure values are excluded from the final-population distribution.",
        )

    def render_pareto() -> None:
        if model is None:
            return
        names = list(model.overview.get("objective_names") or [])
        if len(names) == 1:
            objective = names[0]
            _replace_chart(
                pareto_chart,
                _ranking_options(
                    model.candidates,
                    objective,
                    model.directions.get(objective),
                ),
            )
            pareto_summary.set_text("Single-objective ranking")
            x_objective.set_visibility(False)
            y_objective.set_visibility(False)
            section_status(
                pareto_status,
                model,
                "objectives",
                bool(model.candidates),
                "Single-objective ranking loaded.",
            )
        elif model.pareto.get("available"):
            x_objective.set_visibility(True)
            y_objective.set_visibility(True)
            x_name = str(x_objective.value or names[0])
            y_name = str(y_objective.value or names[1])
            if x_name == y_name and len(names) > 1:
                y_name = next(name for name in names if name != x_name)
            _replace_chart(
                pareto_chart,
                _pareto_options(model.pareto, x_name, y_name),
            )
            pareto_summary.set_text(
                f"Pareto front: {model.pareto['front_size']} · "
                f"Dominated: {model.pareto['dominated_count']}"
            )
            section_status(
                pareto_status,
                model,
                "objectives",
                True,
                "Final-population Pareto analysis loaded.",
            )
        else:
            _replace_chart(
                pareto_chart,
                _empty_options("Multi-objective analysis unavailable"),
            )
            pareto_summary.set_text("")
            section_status(
                pareto_status,
                model,
                "objectives",
                False,
                "",
            )
        hypervolume = model.pareto.get("hypervolume_history", [])
        _replace_chart(
            hypervolume_chart,
            _named_history_options(
                hypervolume, "generation", "hypervolume", "Hypervolume"
            )
            if hypervolume
            else _empty_options(
                "Hypervolume history unavailable (artifact not recorded)"
            ),
        )

    def render_operators(loaded: AnalysisViewModel) -> None:
        stats = list(loaded.operators.get("statistics", {}).values())
        operator_table.rows = stats
        operator_table.update()
        _replace_chart(
            operator_chart,
            _operator_options(stats)
            if stats
            else _empty_options("Operator analysis unavailable"),
        )
        history = loaded.operators.get("history", [])
        _replace_chart(
            operator_history_chart,
            _operator_history_options(history)
            if history
            else _empty_options(
                "Operator reward/probability history was not recorded"
            ),
        )
        section_status(
            operator_status,
            loaded,
            "operators",
            bool(stats),
            "Generic recorded operator identifiers loaded.",
        )

    def render_timing(loaded: AnalysisViewModel) -> None:
        timing = loaded.timing
        generations = timing.get("generations", [])
        requests = timing.get("llm_requests", [])
        _replace_chart(
            generation_timing_chart,
            _named_history_options(
                generations, "generation", "duration_seconds", "Generation"
            )
            if generations
            else _empty_options("Generation timing unavailable"),
        )
        _replace_chart(
            operation_timing_chart,
            _group_bar_options(
                timing.get("operation_groups", {}), "Operation total time"
            ),
        )
        _replace_chart(
            request_order_chart,
            _request_order_options(requests),
        )
        _replace_chart(
            request_generation_chart,
            _request_generation_options(requests),
        )
        _replace_chart(
            role_timing_chart,
            _group_bar_options(
                timing.get("timing_by_role", {}), "LLM role total time"
            ),
        )
        _replace_chart(
            model_timing_chart,
            _group_bar_options(
                timing.get("timing_by_model", {}), "LLM model total time"
            ),
        )
        slow_operation_table.rows = timing.get("slowest_operations", [])
        slow_request_table.rows = timing.get("slowest_requests", [])
        timing_statistics_table.rows = [
            {"group": f"operation:{name}", **values}
            for name, values in timing.get("operation_groups", {}).items()
        ] + [
            {"group": f"llm_role:{name}", **values}
            for name, values in timing.get("timing_by_role", {}).items()
        ] + [
            {"group": f"llm_model:{name}", **values}
            for name, values in timing.get("timing_by_model", {}).items()
        ] + [
            {"group": f"llm_endpoint:{name}", **values}
            for name, values in timing.get("timing_by_endpoint", {}).items()
        ]
        for table in (
            slow_operation_table,
            slow_request_table,
            timing_statistics_table,
        ):
            table.update()
        section_status(
            timing_status,
            loaded,
            "timing",
            bool(generations or requests),
            "Recorded run, operation, and request timing loaded.",
        )

    def render_errors(loaded: AnalysisViewModel) -> None:
        rows = loaded.errors.get("rows", [])
        error_table.rows = rows
        error_table.update()
        error_summary_table.rows = [
            {
                "dimension": f"stage:{name}",
                "value": name,
                "count": count,
                "failure_rate": None,
            }
            for name, count in loaded.errors.get("by_stage", {}).items()
        ] + [
            {
                "dimension": f"category:{name}",
                "value": name,
                "count": count,
                "failure_rate": None,
            }
            for name, count in loaded.errors.get("by_category", {}).items()
        ] + [
            {
                "dimension": f"generation:{name}",
                "value": name,
                "count": count,
                "failure_rate": loaded.errors.get(
                    "by_generation_failure_rate", {}
                ).get(name),
            }
            for name, count in loaded.errors.get("by_generation", {}).items()
        ] + [
            {
                "dimension": f"operator:{name}",
                "value": name,
                "count": count,
                "failure_rate": loaded.errors.get(
                    "by_operator_failure_rate", {}
                ).get(name),
            }
            for name, count in loaded.errors.get("by_operator", {}).items()
        ]
        error_summary_table.update()
        _replace_chart(
            error_stage_chart,
            _count_bar_options(loaded.errors.get("by_stage", {}), "Stage"),
        )
        _replace_chart(
            error_category_chart,
            _count_bar_options(
                loaded.errors.get("by_category", {}), "Category"
            ),
        )
        _replace_chart(
            error_generation_chart,
            _count_bar_options(
                loaded.errors.get("by_generation", {}), "Generation"
            ),
        )
        section_status(
            error_status,
            loaded,
            "errors",
            bool(rows),
            f"{len(rows)} recorded error(s) loaded.",
        )

    def render_candidates() -> None:
        if model is None:
            return
        generation_value = str(generation_filter.value or "")
        pareto_value = str(pareto_filter.value or "")
        rows = filter_candidate_rows(
            model.candidates,
            search=str(candidate_search.value or ""),
            generation=int(generation_value) if generation_value else None,
            status=str(status_filter.value or "") or None,
            pareto=(
                True
                if pareto_value == "pareto"
                else False
                if pareto_value == "dominated"
                else None
            ),
        )
        candidate_table.rows = rows
        candidate_table.update()
        section_status(
            candidate_status,
            model,
            "candidates",
            bool(model.candidates),
            f"Showing {len(rows)} of {len(model.candidates)} candidates.",
        )

    def render_evaluation(loaded: AnalysisViewModel) -> None:
        summaries = loaded.evaluation.get("summaries", {})
        duration = loaded.evaluation.get("duration", {})
        duration_row = {
            "metric": "evaluation_duration_seconds",
            **duration,
            "missing_or_failed_count": None,
        }
        evaluation_summary_table.rows = list(summaries.values()) + (
            [duration_row] if duration.get("count") else []
        )
        evaluation_summary_table.update()
        final_test_table.rows = loaded.evaluation.get("final_tests", [])
        final_test_table.update()
        names = list(summaries)
        evaluation_metric.options = {name: name for name in names}
        if evaluation_metric.value not in names:
            evaluation_metric.value = names[0] if names else None
        evaluation_metric.update()
        render_evaluation_metric()
        section_status(
            evaluation_status,
            loaded,
            "evaluation",
            bool(summaries),
            f"{len(summaries)} generic evaluator metric(s) loaded · "
            f"success={loaded.evaluation['success_count']} "
            f"failure={loaded.evaluation['failure_count']}.",
        )

    def render_evaluation_metric() -> None:
        if model is None:
            return
        metric = str(evaluation_metric.value or "")
        rows = [
            row
            for row in model.evaluation.get("trends", [])
            if row.get("metric") == metric
        ]
        _replace_chart(
            evaluation_chart,
            _named_history_options(rows, "generation", "mean", metric)
            if rows
            else _empty_options("Evaluation metric trend unavailable"),
        )

    async def refresh_sources() -> None:
        try:
            sources = await asyncio.to_thread(
                controller.discover_sources, state.repository_root / "runs"
            )
        except (OSError, ValueError) as exc:
            status.set_text(f"Cannot discover result folders: {exc}")
            return
        source_select.options = {
            str(item.path): _run_option_label(item.run_id, item.status)
            for item in sources
        }
        if source_select.value not in source_select.options:
            source_select.value = None
        source_select.update()

    async def load_path(
        path: Path, preserve_options: tuple[Any, ...] | None = None
    ) -> None:
        nonlocal model, active_selected_path, experiment_options
        nonlocal updating_run_selector
        token = coordinator.begin()
        active_selected_path = path
        model = None
        spinner.set_visibility(True)
        fatal_error.set_visibility(False)
        warning_summary.set_visibility(False)
        status.set_text(f"Loading {path}…")
        clear_dashboard()
        try:
            loaded = await asyncio.to_thread(controller.load_dashboard, path)
        except (OSError, ValueError) as exc:
            if coordinator.is_current(token):
                fatal_error.set_text(
                    f"Fatal folder-loading error: {type(exc).__name__}: {exc}"
                )
                fatal_error.set_visibility(True)
                status.set_text(f"Cannot parse analysis folder: {path}")
            return
        finally:
            if coordinator.is_current(token):
                spinner.set_visibility(False)
        if not coordinator.is_current(token):
            return

        model = loaded
        state.selection.run_dir = loaded.run_dir
        options = preserve_options or loaded.run_options
        experiment_options = tuple(options)
        updating_run_selector = True
        try:
            run_selector.options = {
                str(item.path): _run_option_label(item.run_id, item.status)
                for item in options
            }
            run_selector.value = str(loaded.run_dir)
            run_selector.set_visibility(len(options) > 1)
            run_selector.update()
        finally:
            updating_run_selector = False
        status.set_text(
            f"Loaded {loaded.run_dir.name} · "
            f"{len(loaded.candidates)} candidates · "
            f"{len(loaded.warnings)} warning(s)"
        )
        render(loaded)

    async def select_source() -> None:
        if source_select.value:
            await load_path(Path(str(source_select.value)))

    async def select_folder() -> None:
        value = str(folder_input.value or "").strip()
        if value:
            await load_path(Path(value))

    async def select_run() -> None:
        if (
            updating_run_selector
            or not run_selector.value
            or (
                model is not None
                and Path(str(run_selector.value)) == model.run_dir
            )
        ):
            return
        await load_path(
            Path(str(run_selector.value)),
            preserve_options=experiment_options,
        )

    async def refresh_current() -> None:
        if model is not None:
            await load_path(
                model.run_dir,
                preserve_options=experiment_options,
            )
        elif active_selected_path is not None:
            await load_path(active_selected_path)

    def select_candidate(event: Any) -> None:
        if model is None:
            return
        candidate_id = _event_row_id(event)
        detail = model.candidate_details.get(candidate_id)
        if detail is None:
            return
        state.selection.candidate_id = candidate_id
        candidate_detail.value = json.dumps(
            detail, ensure_ascii=False, indent=2, default=str
        )
        candidate_detail.update()

    def select_error(event: Any) -> None:
        if model is None:
            return
        candidate_id = _event_row_id(event)
        row = next(
            (
                item
                for item in model.errors.get("rows", [])
                if str(item.get("candidate_id")) == candidate_id
            ),
            None,
        )
        if row is not None:
            error_detail.value = json.dumps(
                row, ensure_ascii=False, indent=2, default=str
            )
            error_detail.update()

    def select_chart_candidate(event: Any) -> None:
        if model is None:
            return
        args = getattr(event, "args", {})
        if not isinstance(args, dict):
            return
        candidate_id = str(args.get("name") or "")
        detail = model.candidate_details.get(candidate_id)
        if detail is not None:
            state.selection.candidate_id = candidate_id
            candidate_detail.value = json.dumps(
                detail, ensure_ascii=False, indent=2, default=str
            )
            candidate_detail.update()

    source_select.on_value_change(lambda _: select_source())
    folder_input.on("change", lambda _: select_folder())
    run_selector.on_value_change(lambda _: select_run())
    refresh_sources_button.on_click(refresh_sources)
    refresh_active.on_click(refresh_current)
    objective_select.on_value_change(lambda _: render_objective())
    x_objective.on_value_change(lambda _: render_pareto())
    y_objective.on_value_change(lambda _: render_pareto())
    candidate_search.on_value_change(lambda _: render_candidates())
    generation_filter.on_value_change(lambda _: render_candidates())
    status_filter.on_value_change(lambda _: render_candidates())
    pareto_filter.on_value_change(lambda _: render_candidates())
    evaluation_metric.on_value_change(lambda _: render_evaluation_metric())
    error_search.on_value_change(
        lambda event: _set_table_filter(error_table, event.value)
    )
    candidate_table.on("rowClick", select_candidate)
    error_table.on("rowClick", select_error)
    pareto_chart.on("click", select_chart_candidate)
    ui.timer(0.1, refresh_sources, once=True)


def _table(
    names: tuple[str, ...],
    *,
    row_key: str,
    rows_per_page: int = 10,
):
    return (
        ui.table(
            columns=_columns(names),
            rows=[],
            row_key=row_key,
            pagination={"rowsPerPage": rows_per_page},
        )
        .props(TABLE_PROPS)
        .classes("w-full max-h-[520px] overflow-auto")
    )


def _columns(names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "label": name.replace("_", " ").title(),
            "field": name,
            "sortable": True,
            "align": "left",
        }
        for name in names
    ]


def _viewer(label: str, height: int):
    return (
        ui.textarea(label)
        .props("readonly")
        .classes(f"{TEXTAREA_CLASS} font-mono w-full h-[{height}px]")
    )


def _chart(title: str):
    return ui.echart(_empty_options(title)).classes(CHART_CLASS)


def _replace_chart(chart: Any, options: dict[str, Any]) -> None:
    replace_chart_options(chart, options)
    chart.update()


def _empty_options(title: str) -> dict[str, Any]:
    return {
        "backgroundColor": COLORS["surface"],
        "title": {
            "text": title,
            "left": "center",
            "top": "middle",
            "textStyle": {"color": COLORS["muted"], "fontSize": 14},
        },
        "xAxis": {"show": False},
        "yAxis": {"show": False},
        "series": [],
    }


def _base_options() -> dict[str, Any]:
    return {
        "backgroundColor": COLORS["surface"],
        "color": [
            COLORS["sky_blue"],
            COLORS["bronze"],
            COLORS["success"],
            COLORS["warning"],
            COLORS["info"],
            COLORS["error"],
        ],
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": COLORS["surface_alt"],
            "borderColor": COLORS["border"],
            "textStyle": {"color": COLORS["text"]},
        },
        "legend": {
            "type": "scroll",
            "textStyle": {"color": COLORS["text"]},
            "top": 4,
        },
        "grid": {
            "left": "6%",
            "right": "5%",
            "top": 48,
            "bottom": 58,
            "containLabel": True,
        },
    }


def _axis(name: str, axis_type: str = "value") -> dict[str, Any]:
    return {
        "type": axis_type,
        "name": name,
        "nameTextStyle": {"color": COLORS["text"]},
        "axisLabel": {"color": COLORS["muted"], "hideOverlap": True},
        "axisLine": {"lineStyle": {"color": COLORS["border"]}},
        "splitLine": {"lineStyle": {"color": COLORS["border"], "opacity": 0.45}},
    }


def _evolution_options(
    objective: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis("Generation", "category"),
                "data": [row["generation"] for row in rows],
            },
            "yAxis": _axis(objective),
            "series": [
                {
                    "name": name.title(),
                    "type": "line",
                    "connectNulls": False,
                    "data": [row.get(name) for row in rows],
                }
                for name in ("best", "mean", "median", "worst")
            ],
        }
    )
    return options


def _population_options(evolution: dict[str, Any]) -> dict[str, Any]:
    population = evolution.get("population", [])
    if not population:
        return _empty_options("Population progress unavailable")
    failures = {
        row["generation"]: row.get("rate")
        for row in evolution.get("failure_rate", [])
    }
    pareto = {
        row["generation"]: row.get("count")
        for row in evolution.get("pareto_front_size", [])
    }
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis("Generation", "category"),
                "data": [row["generation"] for row in population],
            },
            "yAxis": [_axis("Candidate count"), _axis("Failure rate")],
            "series": [
                {
                    "name": "Population",
                    "type": "line",
                    "data": [row.get("count") for row in population],
                },
                {
                    "name": "Valid candidates",
                    "type": "line",
                    "data": [row.get("valid_count") for row in population],
                },
                {
                    "name": "Pareto-front size",
                    "type": "line",
                    "data": [pareto.get(row["generation"]) for row in population],
                },
                {
                    "name": "Failure rate",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": [
                        failures.get(row["generation"]) for row in population
                    ],
                },
            ],
        }
    )
    return options


def _pareto_options(
    pareto: dict[str, Any], x_name: str, y_name: str
) -> dict[str, Any]:
    ids = pareto["pareto_ids"]
    points = []
    for row in pareto["rows"]:
        if row.get(x_name) is None or row.get(y_name) is None:
            continue
        candidate_id = str(row.get("candidate_id"))
        points.append(
            {
                "name": candidate_id,
                "value": [
                    row.get(x_name),
                    row.get(y_name),
                    candidate_id,
                    *[
                        f"{name}={row.get(name)}"
                        for name in pareto.get("objectives", [])
                    ],
                ],
                "symbolSize": 16 if candidate_id in ids else 9,
                "itemStyle": {
                    "color": (
                        COLORS["bronze"]
                        if candidate_id in ids
                        else COLORS["sky_blue"]
                    ),
                    "opacity": 0.85,
                },
            }
        )
    options = _base_options()
    options["tooltip"]["trigger"] = "item"
    options.update(
        {
            "xAxis": _axis(x_name),
            "yAxis": _axis(y_name),
            "series": [
                {"name": "Final population", "type": "scatter", "data": points}
            ],
        }
    )
    return options


def _ranking_options(
    rows: list[dict[str, Any]], objective: str, direction: str | None
) -> dict[str, Any]:
    valid = [
        row
        for row in rows
        if not row.get("failed") and row.get(objective) is not None
    ]
    valid.sort(
        key=lambda row: float(row[objective]),
        reverse=direction == "maximize",
    )
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis("Candidate", "category"),
                "data": [row["candidate_id"] for row in valid],
                "axisLabel": {
                    **_axis("", "category")["axisLabel"],
                    "rotate": 35,
                },
            },
            "yAxis": _axis(objective),
            "series": [
                {
                    "name": f"{objective} ({direction or 'direction unknown'})",
                    "type": "bar",
                    "data": [row[objective] for row in valid],
                }
            ],
        }
    )
    return options


def _histogram_options(
    objective: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis(objective, "category"),
                "data": [row["label"] for row in rows],
                "axisLabel": {
                    **_axis("", "category")["axisLabel"],
                    "rotate": 30,
                },
            },
            "yAxis": _axis("Valid candidates"),
            "series": [
                {
                    "name": "Frequency",
                    "type": "bar",
                    "data": [row["count"] for row in rows],
                }
            ],
        }
    )
    return options


def _operator_options(rows: list[dict[str, Any]]) -> dict[str, Any]:
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis("Operator", "category"),
                "data": [row["operator"] for row in rows],
            },
            "yAxis": [_axis("Count"), _axis("Rate")],
            "series": [
                {
                    "name": "Usage",
                    "type": "bar",
                    "data": [row["usage_count"] for row in rows],
                },
                {
                    "name": "Successful offspring",
                    "type": "bar",
                    "data": [row["successful_offspring"] for row in rows],
                },
                {
                    "name": "Success rate",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": [row["success_rate"] for row in rows],
                },
            ],
        }
    )
    return options


def _operator_history_options(rows: list[dict[str, Any]]) -> dict[str, Any]:
    options = _base_options()
    generations = sorted({row["generation"] for row in rows})
    operators = sorted({row["operator"] for row in rows})
    series = []
    for operator in operators:
        by_generation = {
            row["generation"]: row
            for row in rows
            if row["operator"] == operator
        }
        for field in ("reward", "probability"):
            if any(
                by_generation.get(generation, {}).get(field) is not None
                for generation in generations
            ):
                series.append(
                    {
                        "name": f"{operator} {field}",
                        "type": "line",
                        "data": [
                            by_generation.get(generation, {}).get(field)
                            for generation in generations
                        ],
                    }
                )
    options.update(
        {
            "xAxis": {
                **_axis("Generation", "category"),
                "data": generations,
            },
            "yAxis": _axis("Recorded reward / probability"),
            "series": series,
        }
    )
    return options


def _named_history_options(
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    name: str,
) -> dict[str, Any]:
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis(x_key.replace("_", " ").title(), "category"),
                "data": [row.get(x_key) for row in rows],
            },
            "yAxis": _axis(name),
            "series": [
                {
                    "name": name,
                    "type": "line",
                    "data": [row.get(y_key) for row in rows],
                }
            ],
        }
    )
    return options


def _group_bar_options(
    groups: dict[str, dict[str, Any]], name: str
) -> dict[str, Any]:
    if not groups:
        return _empty_options(f"{name} unavailable")
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis("Group", "category"),
                "data": list(groups),
                "axisLabel": {
                    **_axis("", "category")["axisLabel"],
                    "rotate": 25,
                },
            },
            "yAxis": _axis("Seconds"),
            "series": [
                {
                    "name": name,
                    "type": "bar",
                    "data": [value.get("total") for value in groups.values()],
                }
            ],
        }
    )
    return options


def _request_order_options(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _empty_options("LLM request timing unavailable")
    values = [
        {**row, "_order": index + 1} for index, row in enumerate(rows)
    ]
    return _named_history_options(
        values, "_order", "duration_seconds", "Request duration (seconds)"
    )


def _request_generation_options(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _empty_options("LLM timing by generation unavailable")
    totals: dict[Any, float] = {}
    for row in rows:
        generation = row.get("generation")
        totals[generation] = totals.get(generation, 0.0) + float(
            row.get("duration_seconds") or 0.0
        )
    values = [
        {"generation": generation, "duration_seconds": duration}
        for generation, duration in sorted(
            totals.items(), key=lambda item: (item[0] is None, item[0])
        )
    ]
    return _named_history_options(
        values,
        "generation",
        "duration_seconds",
        "LLM request time (seconds)",
    )


def _count_bar_options(values: dict[Any, int], name: str) -> dict[str, Any]:
    if not values:
        return _empty_options(f"{name} error data unavailable")
    options = _base_options()
    options.update(
        {
            "xAxis": {
                **_axis(name, "category"),
                "data": [str(key) for key in values],
                "axisLabel": {
                    **_axis("", "category")["axisLabel"],
                    "rotate": 25,
                },
            },
            "yAxis": _axis("Error count"),
            "series": [
                {
                    "name": "Errors",
                    "type": "bar",
                    "data": list(values.values()),
                }
            ],
        }
    )
    return options


def _display(value: Any, key: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if key == "failure_rate":
            return f"{value:.1%}"
        if key.endswith("_seconds"):
            return f"{value:.3f} s"
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _event_row_id(event: Any) -> str:
    args = getattr(event, "args", {})
    if not isinstance(args, dict):
        return ""
    row = args.get("row")
    if isinstance(row, dict):
        return str(row.get("candidate_id") or row.get("id") or "")
    return str(args.get("candidate_id") or args.get("id") or "")


def _set_table_filter(table: Any, value: Any) -> None:
    table.filter = str(value or "")
    table.update()
