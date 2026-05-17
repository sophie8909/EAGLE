"""Config editor view for the NiceGUI EAGLE workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_gui_web import services


def _bind_input(label: str, value: str, setter: Any, classes: str = "w-56") -> Any:
    return ui.input(label, value=value, on_change=lambda event: setter(str(event.value or ""))).classes(classes)


def build_config_view(state: Any) -> dict[str, Any]:
    """Build the config load/edit/save view."""
    controls: dict[str, Any] = {}

    async def load_base_config() -> None:
        try:
            payload = await asyncio.to_thread(services.load_config_payload, Path(state.config.base_config_path))
            services.apply_config_payload(state, payload, Path(state.config.base_config_path))
            ui.notify(f"Loaded {state.config.base_config_path}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh_form()

    async def save_config() -> None:
        try:
            path = await asyncio.to_thread(services.save_generated_config, state)
            ui.notify(f"Saved {path}", type="positive")
        except (OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        generated_label.set_text(f"Generated config: {path}")

    def refresh_form() -> None:
        for key, control in controls.items():
            owner, name = key.split(".", 1)
            control.value = getattr(getattr(state, owner), name)
            control.update()
        component_path_label.set_text(f"Component path: {state.config.component_pool_path or '(none)'}")
        generated_label.set_text(f"Generated config: {state.config.generated_config_path or '(none)'}")

    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("items-end gap-3"):
            controls["config.base_config_path"] = ui.select(
                services.config_choices(),
                label="Base config",
                value=state.config.base_config_path,
                on_change=lambda event: setattr(state.config, "base_config_path", str(event.value or "")),
            ).classes("min-w-[420px]")
            ui.button("Load", on_click=load_base_config)
            ui.button("Save generated config", on_click=save_config)

        generated_label = ui.label("Generated config: (none)")
        component_path_label = ui.label(f"Component path: {state.config.component_pool_path or '(none)'}")

        with ui.grid(columns=4).classes("w-full gap-3"):
            controls["config.config_name"] = _bind_input(
                "Config name", state.config.config_name, lambda value: setattr(state.config, "config_name", value)
            )
            controls["config.algorithm"] = ui.select(
                list(services.ALGORITHM_CHOICES),
                label="Algorithm",
                value=state.config.algorithm,
                on_change=lambda event: _set_algorithm(state, str(event.value or "nsga2")),
            ).classes("w-56")
            controls["config.surrogate"] = ui.select(
                list(services.SURROGATE_CHOICES),
                label="Surrogate",
                value=state.config.surrogate,
                on_change=lambda event: setattr(state.config, "surrogate", str(event.value or "round")),
            ).classes("w-56")
            controls["config.gameplay_map_dir"] = ui.select(
                list(services.microrts_map_dir_choices()),
                label="Eval map folder",
                value=state.config.gameplay_map_dir,
                on_change=lambda event: setattr(state.config, "gameplay_map_dir", str(event.value or "8x8")),
            ).classes("w-56")

            for name, label in (
                ("population_size", "Population"),
                ("num_generations", "Generations"),
                ("tick_limit", "Tick limit"),
                ("llm_call_limit", "LLM call limit"),
                ("gameplay_rate", "Gameplay rate"),
                ("gameplay_refresh_interval", "Gameplay refresh"),
                ("surrogate_top_ratio", "Surrogate top ratio"),
                ("archive_parent_ratio", "Archive parent ratio"),
                ("one_eval_rounds", "One eval rounds"),
                ("final_test_max_front", "Final max front"),
                ("opponents_text", "Gameplay opponents"),
            ):
                controls[f"config.{name}"] = _bind_input(
                    label,
                    getattr(state.config, name),
                    lambda value, field=name: setattr(state.config, field, value),
                )

        with ui.row().classes("items-center gap-6"):
            ui.checkbox(
                "Include identity in prompt preview",
                value=state.config.include_strategy_identity_in_prompt,
                on_change=lambda event: setattr(
                    state.config,
                    "include_strategy_identity_in_prompt",
                    bool(event.value),
                ),
            )
            ui.checkbox(
                "Fixed training example count",
                value=state.config.training_example_fixed_count,
                on_change=lambda event: setattr(state.config, "training_example_fixed_count", bool(event.value)),
            )

        with ui.row().classes("gap-3"):
            for name, label in (
                ("training_example_sample_min", "Sample min"),
                ("training_example_sample_max", "Sample max"),
                ("training_example_fixed_sample_count", "Fixed sample count"),
            ):
                controls[f"config.{name}"] = _bind_input(
                    label,
                    getattr(state.config, name),
                    lambda value, field=name: setattr(state.config, field, value),
                    "w-44",
                )

    return {"refresh": refresh_form}


def _set_algorithm(state: Any, value: str) -> None:
    state.config.algorithm = value
    services.sync_algorithm_operator_defaults(state)
