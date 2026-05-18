"""Operator selection view."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.theme import CARD_CLASS, GRID_CLASS, INPUT_CLASS, ROW_CLASS, SECTION_HEADER_CLASS
from eagle_gui_web.views.config_view import refresh_config_summary


def build_operators_view(state: Any) -> dict[str, Any]:
    """Build the operator controls view."""
    controls: dict[str, Any] = {}

    def refresh() -> None:
        services.sync_algorithm_operator_defaults(state)
        algorithm_select.value = state.config.algorithm
        algorithm_select.update()
        evaluator_select.value = state.config.evaluator
        evaluator_select.update()
        surrogate_section.visible = services.is_surrogate_algorithm(state.config.algorithm)
        for name, control in config_controls.items():
            control.value = getattr(state.config, name)
            control.update()
        for name, control in selects.items():
            control.value = getattr(state.operators, name)
            control.update()
        for key, control in reproduction_weight_inputs.items():
            control.value = state.operators.reproduction_weights.get(key, "0.0")
            control.update()
        mutation_mix_enabled = state.operators.mutation_operator == "mix"
        for key, control in mutation_weight_inputs.items():
            control.value = state.operators.mutation_weights.get(key, "0.0")
            if mutation_mix_enabled:
                control.enable()
            else:
                control.disable()
            control.update()
        repair_row.visible = state.operators.crossover_operator == "uniform"

    def update_select(name: str, value: str) -> None:
        setattr(state.operators, name, value)
        refresh()
        refresh_config_summary(state)

    def update_algorithm(value: str) -> None:
        state.config.algorithm = value
        services.sync_algorithm_operator_defaults(state)
        refresh()
        refresh_config_summary(state)

    def update_evaluator(value: str) -> None:
        state.config.evaluator = value
        refresh_config_summary(state)

    def update_config(name: str, value: str) -> None:
        setattr(state.config, name, value)
        refresh_config_summary(state)

    def update_flag(name: str, value: bool) -> None:
        setattr(state.operators, name, value)
        refresh_config_summary(state)

    def update_reproduction_weight(key: str, value: str) -> None:
        state.operators.reproduction_weights[key] = value
        refresh_config_summary(state)

    def update_mutation_weight(key: str, value: str) -> None:
        state.operators.mutation_weights[key] = value
        refresh_config_summary(state)

    with ui.column().classes(f"{CARD_CLASS} w-full gap-4"):
        ui.label("Algorithm").classes(SECTION_HEADER_CLASS)
        with ui.grid(columns=2).classes(f"{GRID_CLASS} gap-3"):
            algorithm_select = ui.select(
                list(services.ALGORITHM_CHOICES),
                label="Algorithm",
                value=state.config.algorithm,
                on_change=lambda event: update_algorithm(str(event.value or "nsga2")),
            ).classes(f"{INPUT_CLASS} w-64")
            evaluator_select = ui.select(
                list(services.EVALUATOR_CHOICES),
                label="Eval mode",
                value=state.config.evaluator,
                on_change=lambda event: update_evaluator(str(event.value or "gameplay")),
            ).classes(f"{INPUT_CLASS} w-64")

        with ui.column().classes("w-full gap-3") as surrogate_section:
            ui.label("Surrogate").classes(SECTION_HEADER_CLASS)
            with ui.grid(columns=3).classes(f"{GRID_CLASS} gap-3"):
                config_controls = {
                    "surrogate": ui.select(
                        list(services.SURROGATE_CHOICES),
                        label="Surrogate mode",
                        value=state.config.surrogate,
                        on_change=lambda event: update_config("surrogate", str(event.value or "round")),
                    ).classes(f"{INPUT_CLASS} w-64"),
                    "surrogate_top_ratio": ui.input(
                        "Surrogate top ratio",
                        value=state.config.surrogate_top_ratio,
                        on_change=lambda event: update_config("surrogate_top_ratio", str(event.value or "")),
                    ).classes(f"{INPUT_CLASS} w-44"),
                    "archive_parent_ratio": ui.input(
                        "Archive parent ratio",
                        value=state.config.archive_parent_ratio,
                        on_change=lambda event: update_config("archive_parent_ratio", str(event.value or "")),
                    ).classes(f"{INPUT_CLASS} w-44"),
                }

        ui.label("Operators").classes(SECTION_HEADER_CLASS)
        ui.label("Selection").classes(SECTION_HEADER_CLASS)
        with ui.grid(columns=2).classes(f"{GRID_CLASS} gap-3"):
            selects = {
                "parent_selection_operator": ui.select(
                    list(services.operator_choices("parent_selection")),
                    label="Parent selection",
                    value=state.operators.parent_selection_operator,
                    on_change=lambda event: update_select("parent_selection_operator", str(event.value or "")),
                ).classes(f"{INPUT_CLASS} w-64"),
                "env_selection_operator": ui.select(
                    list(services.operator_choices("env_selection")),
                    label="Environment selection",
                    value=state.operators.env_selection_operator,
                    on_change=lambda event: update_select("env_selection_operator", str(event.value or "")),
                ).classes(f"{INPUT_CLASS} w-64"),
            }

        ui.label("Crossover / Mutation").classes(SECTION_HEADER_CLASS)
        with ui.grid(columns=2).classes(f"{GRID_CLASS} gap-3"):
            selects.update(
                {
                "crossover_operator": ui.select(
                    list(services.operator_choices("crossover")),
                    label="Crossover",
                    value=state.operators.crossover_operator,
                    on_change=lambda event: update_select("crossover_operator", str(event.value or "")),
                ).classes(f"{INPUT_CLASS} w-64"),
                "mutation_operator": ui.select(
                    list(services.operator_choices("mutation")),
                    label="Mutation",
                    value=state.operators.mutation_operator,
                    on_change=lambda event: update_select("mutation_operator", str(event.value or "")),
                ).classes(f"{INPUT_CLASS} w-64"),
                }
            )

        with ui.row().classes(f"{ROW_CLASS} gap-6") as repair_row:
            ui.checkbox(
                "Crossover repair",
                value=state.operators.crossover_repair_enabled,
                on_change=lambda event: update_flag("crossover_repair_enabled", bool(event.value)),
            )
        ui.checkbox(
            "Enable reflection operator",
            value=state.operators.enable_reflection_operator,
            on_change=lambda event: update_flag("enable_reflection_operator", bool(event.value)),
        )

        ui.label("Reproduction operator weights").classes(SECTION_HEADER_CLASS)
        with ui.grid(columns=3).classes(f"{GRID_CLASS} gap-3"):
            reproduction_weight_inputs = {}
            for key in ("crossover", "mutation", "reflection"):
                reproduction_weight_inputs[key] = ui.input(
                    key,
                    value=state.operators.reproduction_weights.get(key, "0.0"),
                    on_change=lambda event, item=key: update_reproduction_weight(item, str(event.value or "0")),
                ).classes(f"{INPUT_CLASS} w-44")

        ui.label("Mutation mix weights").classes(SECTION_HEADER_CLASS)
        with ui.grid(columns=4).classes(f"{GRID_CLASS} gap-3"):
            mutation_weight_inputs = {}
            for key in services.operator_choices("mutation"):
                if key == "mix":
                    continue
                state.operators.mutation_weights.setdefault(key, "0.0")
                mutation_weight_inputs[key] = ui.input(
                    key,
                    value=state.operators.mutation_weights[key],
                    on_change=lambda event, item=key: update_mutation_weight(item, str(event.value or "0")),
                ).classes(f"{INPUT_CLASS} w-56")

    controls["refresh"] = refresh
    refresh()
    return controls
