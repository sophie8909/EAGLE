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
        for name, control in selects.items():
            control.value = getattr(state.operators, name)
            control.update()
        repair_row.visible = state.operators.crossover_operator == "uniform"
        mutation_weight_grid.visible = state.operators.mutation_operator == "mix"

    def update_select(name: str, value: str) -> None:
        setattr(state.operators, name, value)
        refresh()
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
        ui.label("Operators").classes(SECTION_HEADER_CLASS)
        with ui.grid(columns=4).classes(f"{GRID_CLASS} gap-3"):
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
            for key in ("crossover", "mutation", "reflection"):
                ui.input(
                    key,
                    value=state.operators.reproduction_weights.get(key, "0.0"),
                    on_change=lambda event, item=key: update_reproduction_weight(item, str(event.value or "0")),
                ).classes(f"{INPUT_CLASS} w-44")

        ui.label("Mutation mix weights").classes(SECTION_HEADER_CLASS)
        with ui.grid(columns=4).classes(f"{GRID_CLASS} gap-3") as mutation_weight_grid:
            for key in services.operator_choices("mutation"):
                if key == "mix":
                    continue
                state.operators.mutation_weights.setdefault(key, "0.0")
                ui.input(
                    key,
                    value=state.operators.mutation_weights[key],
                    on_change=lambda event, item=key: update_mutation_weight(item, str(event.value or "0")),
                ).classes(f"{INPUT_CLASS} w-56")

    controls["refresh"] = refresh
    refresh()
    return controls
