"""Objective selection view."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from eagle_gui_web import services


def build_objectives_view(state: Any) -> dict[str, Any]:
    """Build the objective registry and selection view."""
    controls: dict[str, Any] = {}
    initial_choices = list(services.objective_choices(state))
    if initial_choices and state.objectives.single_objective not in initial_choices:
        state.objectives.single_objective = initial_choices[0]

    def refresh() -> None:
        services.sync_algorithm_operator_defaults(state)
        choices = list(services.objective_choices(state))
        single_select.options = choices
        if state.objectives.single_objective not in choices and choices:
            state.objectives.single_objective = choices[0]
        single_select.value = state.objectives.single_objective
        single_select.update()
        mode_select.value = state.objectives.mode
        mode_select.update()
        table.rows = services.objective_rows(state)
        table.update()
        update_detail()

    def toggle_selected() -> None:
        key = selected_key.value
        if not key:
            return
        if key in state.objectives.selected:
            state.objectives.selected.remove(key)
        else:
            state.objectives.selected.add(key)
        refresh()

    def update_weight() -> None:
        key = selected_key.value
        if key:
            state.objectives.weights[key] = str(weight_input.value or "1.0")
        refresh()

    def update_detail() -> None:
        key = state.objectives.single_objective if state.objectives.mode == "single" else selected_key.value
        rows = {row["key"]: row for row in services.objective_rows(state)}
        row = rows.get(key or "")
        detail_label.set_text(
            "No objective selected."
            if not row
            else f"{row['key']}: {row['label']}; direction={row['direction']}; eval_mode=full_game."
        )

    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("items-end gap-3"):
            mode_select = ui.select(
                ["single", "weighted_mix", "multi"],
                label="Mode",
                value=state.objectives.mode,
                on_change=lambda event: _set_mode(state, str(event.value or "multi"), refresh),
            ).classes("w-52")
            single_select = ui.select(
                initial_choices,
                label="Single objective",
                value=state.objectives.single_objective,
                on_change=lambda event: setattr(state.objectives, "single_objective", str(event.value or "")),
            ).classes("w-72")
            selected_key = ui.select([], label="Selected row").classes("w-72")
            weight_input = ui.input("Weight", value="1.0").classes("w-32")
            ui.button("Toggle selected", on_click=toggle_selected)
            ui.button("Set weight", on_click=update_weight)

        table = ui.table(
            columns=[
                {"name": "selected", "label": "Use", "field": "selected"},
                {"name": "key", "label": "Objective key", "field": "key", "align": "left"},
                {"name": "label", "label": "Label", "field": "label", "align": "left"},
                {"name": "direction", "label": "Direction", "field": "direction"},
                {"name": "weight", "label": "Weight", "field": "weight"},
            ],
            rows=[],
            row_key="key",
            on_select=lambda event: _on_select(event, selected_key, weight_input, state, update_detail),
        ).classes("w-full")
        detail_label = ui.label(state.objectives.detail).classes("w-full")

    controls["refresh"] = refresh
    refresh()
    return controls


def _set_mode(state: Any, value: str, refresh: Any) -> None:
    if state.config.algorithm not in services.GA_ALGORITHMS:
        state.objectives.mode = "multi"
    else:
        state.objectives.mode = value
    refresh()


def _on_select(event: Any, selected_key: Any, weight_input: Any, state: Any, update_detail: Any) -> None:
    rows = event.selection or []
    if not rows:
        return
    key = str(rows[0].get("key", ""))
    selected_key.options = [key]
    selected_key.value = key
    selected_key.update()
    weight_input.value = state.objectives.weights.get(key, "1.0")
    weight_input.update()
    update_detail()
