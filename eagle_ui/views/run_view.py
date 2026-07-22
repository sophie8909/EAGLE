"""EA run-control page backed by :class:`RunController`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from eagle_ui.components.log_panel import create_log_panel
from eagle_ui.controllers.run_controller import RunController
from eagle_ui.state import AppState
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def build_run_view(state: AppState, controller: RunController) -> None:
    choices = {str(path): path.name for path in controller.config_choices()}
    loaded_values: dict[str, object] = {}
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("EA Run Control").classes("text-h6")
        config_select = ui.select(
            choices,
            label="Experiment configuration",
            value=str(state.repository_root / state.run.config_path),
        ).classes(f"{INPUT_CLASS} w-full")
        with ui.grid(columns=3).classes("w-full gap-3"):
            population = ui.number("Population size", min=1).classes(INPUT_CLASS)
            generations_input = ui.number("Generation count", min=1).classes(INPUT_CLASS)
            seed = ui.number("Seed", min=0).classes(INPUT_CLASS)
            opponent = ui.input("Evaluation opponent").props("readonly").classes(INPUT_CLASS)
            map_path = ui.select(controller.map_choices(), label="MicroRTS map").classes(INPUT_CLASS)
            runs_dir_input = ui.input("Output run directory").classes(INPUT_CLASS)
        effective_config = ui.label("Effective configuration: not loaded").classes("text-caption")
        mock = ui.checkbox("Dry run / mock evaluation", value=state.run.mock)
        with ui.row().classes("items-center gap-2"):
            load_button = ui.button("Load configuration").classes(BUTTON_CLASS)
            validate_button = ui.button("Validate edits").classes(BUTTON_CLASS)
            save_button = ui.button("Save canonical configuration").classes(BUTTON_CLASS)
            start_button = ui.button("Start EA run").classes(BUTTON_CLASS)
            status = ui.badge("idle")
        ui.label("Stop is not exposed because the current EA runner has no checkpoint-safe termination API.").classes("text-caption")
        with ui.grid(columns=3).classes("w-full gap-3"):
            generation = _status_field("Current generation", "—")
            candidate = _status_field("Current candidate", "—")
            counts = _status_field("Completed / failed", "0 / 0")
        run_dir = _status_field("Current run directory", "—")
        log = create_log_panel()

    async def start() -> None:
        try:
            selected = Path(str(config_select.value))
            if collect() != loaded_values:
                raise ValueError("Run controls contain unsaved edits; save or reload the canonical config first.")
            await asyncio.to_thread(controller.start, selected, mock=bool(mock.value))
        except (OSError, ValueError, RuntimeError) as exc:
            ui.notify(f"Cannot start EA run: {exc}", type="negative")
            return
        refresh()

    def collect() -> dict[str, object]:
        return {
            "population_size": int(population.value or 0),
            "generations": int(generations_input.value or 0),
            "random_seed": int(seed.value or 0),
            "map_path": str(map_path.value or ""),
            "runs_dir": str(runs_dir_input.value or ""),
        }

    async def load_config() -> None:
        try:
            values = await asyncio.to_thread(controller.load_fields, Path(str(config_select.value)))
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot load experiment configuration {config_select.value}: {exc}", type="negative")
            return
        loaded_values.clear()
        loaded_values.update({key: values[key] for key in ("population_size", "generations", "random_seed", "map_path", "runs_dir")})
        population.value = values["population_size"]
        generations_input.value = values["generations"]
        seed.value = values["random_seed"]
        opponent.value = values["opponent"]
        map_path.value = values["map_path"]
        runs_dir_input.value = values["runs_dir"]
        effective_config.set_text(f"Effective configuration: {config_select.value}")
        for control in (population, generations_input, seed, opponent, map_path, runs_dir_input):
            control.update()

    async def validate_edits() -> None:
        try:
            selected = Path(str(config_select.value))
            original = await asyncio.to_thread(selected.read_text, encoding="utf-8")
            with __import__("tempfile").TemporaryDirectory() as directory:
                temporary = Path(directory) / selected.name
                temporary.write_text(original, encoding="utf-8")
                from eagle_ui.controllers.config_controller import update_minimal_yaml
                update_minimal_yaml(temporary, collect())
                await asyncio.to_thread(controller.validate, temporary)
        except (OSError, ValueError) as exc:
            ui.notify(f"Invalid run configuration for {config_select.value}: {exc}", type="negative")
            return
        ui.notify("Run configuration is valid.", type="positive")

    async def save_config() -> None:
        try:
            await asyncio.to_thread(controller.save_fields, Path(str(config_select.value)), collect())
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot save experiment configuration {config_select.value}: {exc}", type="negative")
            return
        await load_config()
        ui.notify(f"Saved {config_select.value}", type="positive")

    def refresh() -> None:
        status.set_text("running" if state.run.running else f"exit {state.run.returncode}" if state.run.returncode is not None else "idle")
        generation.set_text("—" if state.run.current_generation is None else str(state.run.current_generation))
        candidate.set_text(state.run.current_candidate or "—")
        counts.set_text(f"{state.run.completed_candidates} / {state.run.failed_candidates}")
        run_dir.set_text(str(state.run.effective_run_dir or "—"))
        log.value = "\n".join(state.run.log_lines[-2000:])
        log.update()
        start_button.set_enabled(not state.run.running)

    start_button.on_click(start)
    load_button.on_click(load_config)
    validate_button.on_click(validate_edits)
    save_button.on_click(save_config)
    config_select.on_value_change(lambda _: load_config())
    ui.timer(0.5, refresh)
    ui.timer(0.1, load_config, once=True)


def _status_field(label: str, value: str):
    with ui.column().classes("gap-0"):
        ui.label(label).classes("text-caption")
        return ui.label(value).classes("font-mono break-all")
