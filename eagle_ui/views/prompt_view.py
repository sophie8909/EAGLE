"""Initial-candidate and meta-prompt editor page."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from eagle_ui.controllers.prompt_controller import InitialPromptController, InitialPromptData, MetaPromptController
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS, TEXTAREA_CLASS


SEED_SEPARATOR = "\n\n--- EAGLE SEED PROMPT ---\n\n"


def build_prompt_view(repository_root: Path, initial: InitialPromptController, meta: MetaPromptController) -> None:
    with ui.tabs() as tabs:
        initial_tab = ui.tab("Initial candidate")
        meta_tab = ui.tab("Meta prompts")
    with ui.tab_panels(tabs, value=initial_tab).classes("w-full"):
        with ui.tab_panel(initial_tab):
            _build_initial(repository_root, initial)
        with ui.tab_panel(meta_tab):
            _build_meta(meta)


def _build_initial(repository_root: Path, controller: InitialPromptController) -> None:
    loaded: InitialPromptData | None = None
    config_path = ui.select(
        {str(path): path.name for path in sorted((repository_root / "configs").glob("*.yaml"))},
        label="Experiment config",
        value=str(repository_root / "configs" / "eagle_minimal.yaml"),
    ).classes(f"{INPUT_CLASS} w-full")
    source = ui.label("No configuration loaded")
    strategy = ui.textarea("Strategy descriptions (separator preserves multiple seeds)").classes(f"{TEXTAREA_CLASS} w-full h-48")
    generation = ui.textarea("Generation instructions").classes(f"{TEXTAREA_CLASS} w-full h-40")
    java_context = ui.textarea("Existing / seed Java context").classes(f"{TEXTAREA_CLASS} w-full h-72")
    preview = ui.textarea("Final assembled prompt preview").props("readonly").classes(f"{TEXTAREA_CLASS} w-full h-72")

    def show(data: InitialPromptData) -> None:
        nonlocal loaded
        loaded = data
        strategy.value = SEED_SEPARATOR.join(data.strategy_prompts)
        generation.value = data.generation_prompt
        java_context.value = data.java_context
        source.set_text(f"Config: {data.config_path} | Java: {data.java_template_path}")
        for control in (strategy, generation, java_context):
            control.update()

    async def load() -> None:
        try:
            data = await asyncio.to_thread(controller.load, Path(str(config_path.value)))
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot load initial prompts from {config_path.value}: {exc}", type="negative")
            return
        show(data)

    def seeds() -> tuple[str, ...]:
        return tuple(value.strip() for value in str(strategy.value or "").split(SEED_SEPARATOR) if value.strip())

    async def render_preview() -> None:
        try:
            controller.validate(seeds(), str(generation.value or ""), str(java_context.value or ""))
            preview.value = controller.preview(seeds()[0], str(generation.value), str(java_context.value))
        except ValueError as exc:
            ui.notify(f"Cannot preview initial prompt: {exc}", type="negative")
            return
        preview.update()

    async def save() -> None:
        if loaded is None:
            ui.notify("Load an experiment config before saving.", type="warning")
            return
        try:
            await asyncio.to_thread(controller.save, loaded, seeds(), str(generation.value or ""), str(java_context.value or ""))
            data = await asyncio.to_thread(controller.load, loaded.config_path)
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot save initial prompts for {loaded.config_path}: {exc}", type="negative")
            return
        show(data)
        ui.notify("Initial prompt configuration saved.", type="positive")

    with ui.row().classes("gap-2"):
        ui.button("Load", on_click=load).classes(BUTTON_CLASS)
        ui.button("Reload", on_click=load).classes(BUTTON_CLASS)
        ui.button("Restore loaded", on_click=lambda: show(loaded) if loaded else None).classes(BUTTON_CLASS)
        ui.button("Preview", on_click=render_preview).classes(BUTTON_CLASS)
        ui.button("Save", on_click=save).classes(BUTTON_CLASS)


def _build_meta(controller: MetaPromptController) -> None:
    templates = controller.load()
    selected = ui.select({key: key for key in templates}, label="Stable prompt ID", value=next(iter(templates))).classes(f"{INPUT_CLASS} w-full")
    info = ui.label()
    validation_state = ui.label("Missing variables: none")
    body = ui.textarea("Editable template").classes(f"{TEXTAREA_CLASS} w-full h-96")
    preview = ui.textarea("Rendered mock preview").props("readonly").classes(f"{TEXTAREA_CLASS} w-full h-72")

    def load_selected() -> None:
        item = controller.load()[str(selected.value)]
        body.value = item.template
        info.set_text(
            f"Role: {item.role} | Stages: {', '.join(item.stages)} | Source: {item.source_path} | Required: {', '.join(item.required_variables)}"
        )
        validation_state.set_text("Missing variables: none | Unsupported variables: none")
        body.update()

    def render_preview() -> None:
        try:
            preview.value = controller.preview(str(selected.value), str(body.value or ""))
        except ValueError as exc:
            validation_state.set_text(str(exc))
            ui.notify(f"Template validation failed: {exc}", type="negative")
            return
        validation_state.set_text("Missing variables: none | Unsupported variables: none")
        preview.update()

    def save() -> None:
        try:
            controller.save(str(selected.value), str(body.value or ""))
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot save {selected.value} in {controller.source_path}: {exc}", type="negative")
            return
        load_selected()
        ui.notify(f"Saved {selected.value}", type="positive")

    selected.on_value_change(lambda _: load_selected())
    with ui.row().classes("gap-2"):
        ui.button("Reload", on_click=load_selected).classes(BUTTON_CLASS)
        ui.button("Restore loaded", on_click=load_selected).classes(BUTTON_CLASS)
        ui.button("Validate & preview", on_click=render_preview).classes(BUTTON_CLASS)
        ui.button("Save", on_click=save).classes(BUTTON_CLASS)
    load_selected()
