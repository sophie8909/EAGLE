"""Objective selection view."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from eagle_ui import services
from eagle_ui.theme import CARD_CLASS, INPUT_CLASS, ROW_CLASS, SECTION_HEADER_CLASS
from eagle_ui.views.config_view import refresh_config_summary


OBJECTIVE_MODE_OPTIONS = ("single", "multi")


def build_objectives_view(state: Any) -> dict[str, Any]:
    """Build the objective registry and selection view."""
    controls: dict[str, Any] = {}
    objective_controls: dict[str, dict[str, Any]] = {}
    initial_choices = list(services.objective_choices(state))
    _ensure_valid_objective_state(state, initial_choices)

    def refresh() -> None:
        choices = list(services.objective_choices(state))
        _ensure_valid_objective_state(state, choices)
        rows = {row["key"]: row for row in services.objective_rows(state)}

        mode_select.options = list(OBJECTIVE_MODE_OPTIONS)
        mode_select.value = state.objectives.mode
        mode_select.update()

        single_panel.visible = state.objectives.mode == "single"
        multi_panel.visible = state.objectives.mode == "multi"

        single_select.options = choices
        single_select.value = state.objectives.single_objective
        single_select.update()
        selected_row = rows.get(state.objectives.single_objective, {})
        single_direction.set_text(str(selected_row.get("direction", "")))
        single_weight.value = state.objectives.weights.get(state.objectives.single_objective, "1.0")
        single_weight.update()

        for key, row_controls in objective_controls.items():
            selected = key in state.objectives.selected
            row_controls["checkbox"].value = selected
            row_controls["checkbox"].update()
            row_controls["weight"].value = state.objectives.weights.get(key, "1.0")
            if selected:
                row_controls["weight"].enable()
            else:
                row_controls["weight"].disable()
            row_controls["weight"].update()
        refresh_config_summary(state)

    def update_mode(value: str) -> None:
        state.objectives.mode = value if value in OBJECTIVE_MODE_OPTIONS else "multi"
        choices = list(services.objective_choices(state))
        _ensure_valid_objective_state(state, choices)
        refresh()

    def update_single_objective(value: str) -> None:
        if value:
            state.objectives.single_objective = value
            state.objectives.weights.setdefault(value, "1.0")
        _ensure_single_selection(state)
        refresh()

    def update_single_weight(value: str) -> None:
        key = state.objectives.single_objective
        if key:
            state.objectives.weights[key] = value or "1.0"
        refresh_config_summary(state)

    def update_multi_selected(key: str, selected: bool) -> None:
        if selected:
            state.objectives.selected.add(key)
            state.objectives.weights.setdefault(key, "1.0")
        else:
            state.objectives.selected.discard(key)
        refresh()

    def update_multi_weight(key: str, value: str) -> None:
        state.objectives.weights[key] = value or "1.0"
        refresh_config_summary(state)

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Objectives").classes(SECTION_HEADER_CLASS)
        mode_select = ui.select(
            list(OBJECTIVE_MODE_OPTIONS),
            label="Mode",
            value=state.objectives.mode,
            on_change=lambda event: update_mode(str(event.value or "multi")),
        ).classes(f"{INPUT_CLASS} w-52")

        with ui.column().classes("w-full gap-3") as single_panel:
            single_select = ui.select(
                initial_choices,
                label="Objective",
                value=state.objectives.single_objective,
                on_change=lambda event: update_single_objective(str(event.value or "")),
            ).classes(f"{INPUT_CLASS} w-72")
            with ui.row().classes(f"{ROW_CLASS} items-end gap-3"):
                ui.label("Direction:").classes("w-24")
                single_direction = ui.label().classes("w-48")
                single_weight = ui.input(
                    "Weight",
                    value=state.objectives.weights.get(state.objectives.single_objective, "1.0"),
                    on_change=lambda event: update_single_weight(str(event.value or "1.0")),
                ).classes(f"{INPUT_CLASS} w-32")

        with ui.column().classes("w-full gap-2") as multi_panel:
            ui.label("Available objectives").classes(SECTION_HEADER_CLASS)
            for row in services.objective_rows(state):
                key = row["key"]
                with ui.row().classes(f"{ROW_CLASS} w-full items-center gap-3"):
                    checkbox = ui.checkbox(
                        key,
                        value=key in state.objectives.selected,
                        on_change=lambda event, item=key: update_multi_selected(item, bool(event.value)),
                    ).classes("w-72")
                    ui.label(row["direction"]).classes("w-28")
                    ui.label(row["label"]).classes("grow")
                    weight = ui.input(
                        "Weight",
                        value=state.objectives.weights.get(key, "1.0"),
                        on_change=lambda event, item=key: update_multi_weight(item, str(event.value or "1.0")),
                    ).classes(f"{INPUT_CLASS} w-32")
                    objective_controls[key] = {"checkbox": checkbox, "weight": weight}

    controls["refresh"] = refresh
    refresh()
    return controls


def _ensure_valid_objective_state(state: Any, choices: list[str]) -> None:
    """Keep objective mode and selected objective values inside current choices."""
    if state.objectives.mode == "weighted_mix":
        state.objectives.mode = "multi"
    if state.objectives.mode not in OBJECTIVE_MODE_OPTIONS:
        state.objectives.mode = "multi"
    if choices and state.objectives.single_objective not in choices:
        state.objectives.single_objective = choices[0]
    for key in choices:
        state.objectives.weights.setdefault(key, "1.0")
    state.objectives.selected.intersection_update(choices)
    if state.objectives.mode == "single":
        _ensure_single_selection(state)


def _ensure_single_selection(state: Any) -> None:
    """Store the single objective as the only enabled objective."""
    if state.objectives.single_objective:
        state.objectives.selected = {state.objectives.single_objective}
