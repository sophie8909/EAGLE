"""Operator selection view."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_ui import services
from eagle_ui.theme import (
    BUTTON_CLASS,
    CARD_CLASS,
    GRID_CLASS,
    INPUT_CLASS,
    ROW_CLASS,
    SECTION_HEADER_CLASS,
    button_class,
)
from eagle_ui.ui_actions import safe_click
from eagle_ui.views.config_view import refresh_config_summary

def _field_card(title: str) -> Any:
    """Create a compact settings card."""
    card_classes = (
        "rounded-xl border border-[#2d4059] bg-[#0f1d2e] "
        "p-4 shadow-sm"
    )
    with ui.card().classes(f"{card_classes} w-full"):
        ui.label(title).classes(SECTION_HEADER_CLASS)
        return ui.column().classes("w-full gap-3")


def _options_with_value(options: Any, value: Any) -> list[Any]:
    """Return select options with the current value included."""
    result = list(options or [])
    if value not in (None, "") and value not in result:
        result.insert(0, value)
    return result


def _set_select_options(control: Any, options: Any, value: Any) -> None:
    """Update select options before assigning its value."""
    if isinstance(options, dict):
        safe_options = dict(options)
        if value not in (None, "") and value not in safe_options:
            safe_options[value] = str(value)
    else:
        safe_options = _options_with_value(options, value)
    control.options = safe_options
    control.value = value if value in safe_options else ""


def _fitness_metric_options(value: str = "") -> dict[str, str]:
    options = {
        "win_score": "win_score",
        "resource_advantage": "resource_advantage",
        "resource_diff_mean": "resource_diff_mean",
    }
    if value and value not in options:
        options[value] = value
    return options


def _surrogate_options(value: str = "") -> dict[str, str]:
    options = {
        "early_end": "Early End",
        "round": "Round",
        "policy_agent": "Policy Agent",
        "java_agent": "Java Agent",
    }
    if value and value not in options:
        options[value] = value
    return options


def build_operators_view(state: Any) -> dict[str, Any]:
    """Build the operator controls view."""
    controls: dict[str, Any] = {}

    def config_path_options() -> list[str]:
        options = ["", *services.config_choices()]
        for path in (state.config.base_config_path, state.config.generated_config_path):
            value = str(path or "")
            if value and value not in options:
                options.insert(1, value)
        return options

    async def load_base_config() -> None:
        if not state.config.base_config_path:
            ui.notify("Select a base config first.", type="warning")
            return
        try:
            config_path = Path(state.config.base_config_path)
            payload = await asyncio.to_thread(services.load_config_payload, config_path)
            services.apply_config_payload(state, payload, config_path)
            ui.notify(f"Loaded {config_path}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh()
        refresh_config_summary(state)
        for refresh_handle_name in ("objectives_refresh", "components_refresh"):
            refresh_handle = getattr(state.runtime, refresh_handle_name, None)
            if callable(refresh_handle):
                refresh_handle()

    async def save_config() -> None:
        try:
            path = await asyncio.to_thread(services.save_generated_config, state)
            ui.notify(f"Saved {path}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh()
        generated_label.set_text(f"Generated config: {state.config.generated_config_path or '(none)'}")
        component_path_label.set_text(f"Component path: {state.config.component_pool_path or '(none)'}")
        refresh_config_summary(state)

    def update_base_config_path(value: str) -> None:
        state.config.base_config_path = value

    def create_base_config_select(options: list[str], value: str) -> Any:
        try:
            return ui.select(
                options,
                label="Base config",
                value=value,
                on_change=lambda event: update_base_config_path(str(event.value or "")),
                with_input=True,
                clearable=True,
            )
        except TypeError:
            return ui.select(
                options,
                label="Base config",
                value=value,
                on_change=lambda event: update_base_config_path(str(event.value or "")),
            ).props("use-input clearable new-value-mode=add-unique")

    def refresh() -> None:
        services.sync_algorithm_defaults(state)
        _set_select_options(base_config_select, config_path_options(), state.config.base_config_path or "")
        base_config_select.update()
        generated_label.set_text(f"Generated config: {state.config.generated_config_path or '(none)'}")
        component_path_label.set_text(f"Component path: {state.config.component_pool_path or '(none)'}")
        _set_select_options(algorithm_select, services.ALGORITHM_CHOICES, state.config.algorithm)
        algorithm_select.update()
        _set_select_options(evaluator_select, services.EVALUATION_MODE_CHOICES, state.config.eval_mode)
        evaluator_select.update()
        surrogate_section.visible = (
            services.is_surrogate_algorithm(state.config.algorithm)
            and state.config.eval_mode != "early_end"
        )
        early_end_settings.visible = state.config.eval_mode == "early_end"
        real_eval_settings.visible = state.config.eval_mode == "gameplay"
        for name, control in config_controls.items():
            value = getattr(state.config, name, "")
            if name == "fitness_metric":
                _set_select_options(control, _fitness_metric_options(str(value)), value)
            elif name == "surrogate":
                _set_select_options(control, _surrogate_options(str(value)), value)
            elif hasattr(control, "options"):
                _set_select_options(control, getattr(control, "options", []), value)
            else:
                control.value = value
            control.update()
        for name, control in selects.items():
            value = getattr(state.operators, name, "")
            if name == "mutation_selection_mode":
                control.options = dict(services.MUTATION_SELECTION_MODE_CHOICES)
                control.value = value if value in services.MUTATION_SELECTION_MODE_CHOICES else "fixed"
            elif hasattr(control, "options"):
                _set_select_options(control, getattr(control, "options", []), value)
            else:
                control.value = value
            control.update()
        for key, control in reproduction_weight_inputs.items():
            control.value = state.operators.reproduction_weights.get(key, "0.0")
            control.update()
        mutation_mix_enabled = state.operators.mutation_operator == "mix"
        mutation_weight_section.visible = (
            mutation_mix_enabled
            and state.operators.mutation_selection_mode == "aos"
        )
        for key, control in mutation_weight_inputs.items():
            control.value = state.operators.mutation_weights.get(key, "0.0")
            if mutation_weight_section.visible:
                control.enable()
            else:
                control.disable()
            control.update()
        repair_row.visible = state.operators.crossover_operator == "uniform"

    def update_select(name: str, value: str) -> None:
        setattr(state.operators, name, value)
        if name == "mutation_selection_mode":
            state.operators.mutation_selection_mode = services.normalize_mutation_selection_mode(value)
        refresh()
        refresh_config_summary(state)

    def update_algorithm(value: str) -> None:
        state.config.algorithm = value
        services.sync_algorithm_defaults(state)
        refresh()
        refresh_config_summary(state)
        objectives_refresh = getattr(state.runtime, "objectives_refresh", None)
        if callable(objectives_refresh):
            objectives_refresh()

    def update_evaluator(value: str) -> None:
        state.config.eval_mode = services.normalize_eval_mode(value)
        state.config.evaluator = "gameplay"
        if state.config.eval_mode == "early_end":
            state.config.llm_call_limit = "10"
        refresh()
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

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Config").classes(SECTION_HEADER_CLASS)
        with ui.row().classes(f"{ROW_CLASS} items-end gap-3 w-full"):
            base_config_select = create_base_config_select(
                config_path_options(),
                state.config.base_config_path or "",
            ).classes(f"{INPUT_CLASS} grow min-w-[420px]")
            ui.button("Load", on_click=safe_click(load_base_config, label="Load config")).classes(BUTTON_CLASS)
            ui.button("Save generated config", on_click=safe_click(save_config, label="Save config")).classes(
                button_class(success=True)
            )
        generated_label = ui.label(f"Generated config: {state.config.generated_config_path or '(none)'}")
        component_path_label = ui.label(f"Component path: {state.config.component_pool_path or '(none)'}")

    with ui.column().classes(
        "w-full gap-3 rounded-xl border border-[#2d4059] bg-[#0f1d2e] p-4"
    ):
        ui.label("Algorithm").classes(SECTION_HEADER_CLASS)

        with ui.grid(columns=1).classes("w-full gap-3"):
            algorithm_select = ui.select(
                _options_with_value(services.ALGORITHM_CHOICES, state.config.algorithm),
                label="Algorithm",
                value=state.config.algorithm,
                on_change=lambda event: update_algorithm(str(event.value or "nsga2")),
            ).classes(f"{INPUT_CLASS} w-full")

        ui.label("Evaluation Mode").classes(SECTION_HEADER_CLASS)

        with ui.grid(columns=1).classes("w-full gap-3"):
            evaluator_select = ui.select(
                services.EVALUATION_MODE_CHOICES,
                label="Evaluation",
                value=state.config.eval_mode,
                on_change=lambda event: update_evaluator(str(event.value or "gameplay")),
            ).classes(f"{INPUT_CLASS} w-full")
            config_controls = {
                "agent_class": ui.select(
                    services.AGENT_CLASS_CHOICES,
                    label="LLM agent",
                    value=state.config.agent_class,
                    on_change=lambda event: update_config(
                        "agent_class",
                        services.normalize_agent_class(str(event.value or "")),
                    ),
                ).classes(f"{INPUT_CLASS} w-full"),
            }

        with ui.row().classes(f"{ROW_CLASS} items-center gap-3") as early_end_settings:
            ui.badge("Fitness: Resource Difference").classes("uppercase")

        with ui.grid(columns=3).classes("w-full gap-3"):
            config_controls.update(
                {
                    "llm_call_limit": ui.input(
                        "Eval LLM call limit",
                        value=state.config.llm_call_limit,
                        on_change=lambda event: update_config("llm_call_limit", str(event.value or "")),
                    ).classes(f"{INPUT_CLASS} w-full"),
                }
            )

        with ui.grid(columns=3).classes("w-full gap-3") as real_eval_settings:
            config_controls.update(
                {
                    "fitness_metric": ui.select(
                        _fitness_metric_options(state.config.fitness_metric),
                        label="Fitness metric",
                        value=state.config.fitness_metric,
                        on_change=lambda event: update_config("fitness_metric", str(event.value or "win_score")),
                    ).classes(f"{INPUT_CLASS} w-full"),
                    "gameplay_map_dir": ui.select(
                        _options_with_value(services.microrts_map_dir_choices(), state.config.gameplay_map_dir),
                        label="Eval map folder",
                        value=state.config.gameplay_map_dir,
                        on_change=lambda event: update_config("gameplay_map_dir", str(event.value or "8x8")),
                    ).classes(f"{INPUT_CLASS} w-full"),
                }
            )

        ui.separator().classes("opacity-20")

        ui.label("Experiment").classes(SECTION_HEADER_CLASS)

        with ui.grid(columns=3).classes("w-full gap-3"):
            config_controls.update(
                {
                    "config_name": ui.input(
                        "Config name",
                        value=state.config.config_name,
                        on_change=lambda event: update_config("config_name", str(event.value or "")),
                    ).classes(f"{INPUT_CLASS} w-full"),
                    "population_size": ui.input(
                        "Population size",
                        value=state.config.population_size,
                        on_change=lambda event: update_config("population_size", str(event.value or "")),
                    ).classes(f"{INPUT_CLASS} w-full"),
                    "num_generations": ui.input(
                        "Generations",
                        value=state.config.num_generations,
                        on_change=lambda event: update_config("num_generations", str(event.value or "")),
                    ).classes(f"{INPUT_CLASS} w-full"),
                    "tick_limit": ui.input(
                        "Tick limit",
                        value=state.config.tick_limit,
                        on_change=lambda event: update_config("tick_limit", str(event.value or "")),
                    ).classes(f"{INPUT_CLASS} w-full"),
                }
            )

        with ui.column().classes("w-full gap-3") as surrogate_section:
            ui.label("Surrogate").classes(SECTION_HEADER_CLASS)
            with ui.grid(columns=3).classes(f"{GRID_CLASS} gap-3"):
                config_controls.update(
                    {
                        "surrogate": ui.select(
                            _surrogate_options(state.config.surrogate),
                            label="Surrogate",
                            value=state.config.surrogate,
                            on_change=lambda event: update_config("surrogate", str(event.value or "early_end")),
                        ).classes(f"{INPUT_CLASS} w-64"),
                        "surrogate_top_ratio": ui.input(
                            "Early stop top ratio",
                            value=state.config.surrogate_top_ratio,
                            on_change=lambda event: update_config("surrogate_top_ratio", str(event.value or "")),
                        ).classes(f"{INPUT_CLASS} w-44"),
                        "surrogate_llm_call_limit": ui.input(
                            "Surrogate LLM call limit",
                            value=state.config.surrogate_llm_call_limit,
                            on_change=lambda event: update_config(
                                "surrogate_llm_call_limit",
                                str(event.value or ""),
                            ),
                        ).classes(f"{INPUT_CLASS} w-44"),
                        "archive_parent_ratio": ui.input(
                            "Archive parent ratio",
                            value=state.config.archive_parent_ratio,
                            on_change=lambda event: update_config("archive_parent_ratio", str(event.value or "")),
                        ).classes(f"{INPUT_CLASS} w-44"),
                        "gameplay_refresh_interval": ui.input(
                            "Gameplay refresh interval",
                            value=state.config.gameplay_refresh_interval,
                            on_change=lambda event: update_config(
                                "gameplay_refresh_interval",
                                str(event.value or ""),
                            ),
                        ).classes(f"{INPUT_CLASS} w-44"),
                    }
                )
    with ui.column().classes(
        "w-full gap-4 rounded-xl border border-[#2d4059] bg-[#0f1d2e] p-4"
    ):
        ui.label("Operators").classes(SECTION_HEADER_CLASS)

        with ui.row().classes("w-full gap-6 items-start"):
            with ui.column().classes("w-1/2 gap-3"):
                ui.label("Selection").classes("text-xs uppercase tracking-widest text-[#b08d57]")

                with ui.grid(columns=1).classes("w-full gap-3"):
                    selects = {
                        "parent_selection_operator": ui.select(
                            _options_with_value(
                                services.operator_choices("parent_selection"),
                                state.operators.parent_selection_operator,
                            ),
                            label="Parent selection",
                            value=state.operators.parent_selection_operator,
                            on_change=lambda event: update_select(
                                "parent_selection_operator",
                                str(event.value or ""),
                            ),
                        ).classes(f"{INPUT_CLASS} w-full"),
                        "env_selection_operator": ui.select(
                            _options_with_value(
                                services.operator_choices("env_selection"),
                                state.operators.env_selection_operator,
                            ),
                            label="Environment selection",
                            value=state.operators.env_selection_operator,
                            on_change=lambda event: update_select(
                                "env_selection_operator",
                                str(event.value or ""),
                            ),
                        ).classes(f"{INPUT_CLASS} w-full"),
                    }

            with ui.column().classes("w-1/2 gap-3"):
                ui.label("Crossover / Mutation").classes(
                    "text-xs uppercase tracking-widest text-[#b08d57]"
                )

                with ui.grid(columns=1).classes("w-full gap-3"):
                    selects.update(
                        {
                            "crossover_operator": ui.select(
                                _options_with_value(
                                    services.operator_choices("crossover"),
                                    state.operators.crossover_operator,
                                ),
                                label="Crossover",
                                value=state.operators.crossover_operator,
                                on_change=lambda event: update_select(
                                    "crossover_operator",
                                    str(event.value or ""),
                                ),
                            ).classes(f"{INPUT_CLASS} w-full"),
                            "mutation_operator": ui.select(
                                _options_with_value(
                                    services.operator_choices("mutation"),
                                    state.operators.mutation_operator,
                                ),
                                label="Mutation",
                                value=state.operators.mutation_operator,
                                on_change=lambda event: update_select(
                                    "mutation_operator",
                                    str(event.value or ""),
                                ),
                            ).classes(f"{INPUT_CLASS} w-full"),
                            "mutation_selection_mode": ui.select(
                                dict(services.MUTATION_SELECTION_MODE_CHOICES),
                                label="Operator Selection Mode",
                                value=state.operators.mutation_selection_mode,
                                on_change=lambda event: update_select(
                                    "mutation_selection_mode",
                                    str(event.value or "fixed"),
                                ),
                            ).classes(f"{INPUT_CLASS} w-full"),
                        }
                    )

                with ui.column().classes("gap-2 pt-1") as repair_row:
                    ui.checkbox(
                        "Crossover repair",
                        value=state.operators.crossover_repair_enabled,
                        on_change=lambda event: update_flag(
                            "crossover_repair_enabled",
                            bool(event.value),
                        ),
                    )

                ui.checkbox(
                    "Enable reflection operator",
                    value=state.operators.enable_reflection_operator,
                    on_change=lambda event: update_flag(
                        "enable_reflection_operator",
                        bool(event.value),
                    ),
                )

        ui.separator().classes("opacity-20")

        ui.label("Reproduction weights").classes(
            "text-xs uppercase tracking-widest text-[#b08d57]"
        )

        with ui.grid(columns=3).classes("w-full gap-3"):
            reproduction_weight_inputs = {}
            for key in ("crossover", "mutation", "reflection"):
                reproduction_weight_inputs[key] = ui.input(
                    key,
                    value=state.operators.reproduction_weights.get(key, "0.0"),
                    on_change=lambda event, item=key: update_reproduction_weight(
                        item,
                        str(event.value or "0"),
                    ),
                ).classes(f"{INPUT_CLASS} w-full")

        with ui.column().classes("w-full gap-3") as mutation_weight_section:
            ui.label("Mutation mix weights").classes(
                "text-xs uppercase tracking-widest text-[#b08d57]"
            )

            with ui.grid(columns=4).classes("w-full gap-3"):
                mutation_weight_inputs = {}
                for key in services.operator_choices("mutation"):
                    if key == "mix":
                        continue
                    state.operators.mutation_weights.setdefault(key, "0.0")
                    mutation_weight_inputs[key] = ui.input(
                        key,
                        value=state.operators.mutation_weights[key],
                        on_change=lambda event, item=key: update_mutation_weight(
                            item,
                            str(event.value or "0"),
                        ),
                    ).classes(f"{INPUT_CLASS} w-full")

    controls["refresh"] = refresh
    refresh()
    return controls
