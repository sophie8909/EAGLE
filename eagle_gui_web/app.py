"""NiceGUI entrypoint for the EAGLE desktop workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nicegui import app as nicegui_app
from nicegui import ui

from eagle_gui_web import services
from eagle_gui_web.state import AppState
from eagle_gui_web.theme import (
    BRAND_CLASS,
    BRAND_IMAGE_CLASS,
    CARD_CLASS,
    HEADER_CLASS,
    PAGE_CLASS,
    SUBTITLE_CLASS,
    TAB_CLASS,
    install_theme,
    title_class,
)
from eagle_gui_web.views.analysis_view import build_analysis_view
from eagle_gui_web.views.components_view import build_components_view
from eagle_gui_web.views.config_view import build_config_view
from eagle_gui_web.views.final_test_view import build_final_test_view
from eagle_gui_web.views.microrts_view import build_microrts_view
from eagle_gui_web.views.objectives_view import build_objectives_view
from eagle_gui_web.views.operators_view import build_operators_view
from eagle_gui_web.views.prompts_view import build_prompts_view
from eagle_gui_web.views.run_view import build_run_view


state = AppState()
EAGLE_IMAGE_URL = "/assets/eagle.png"


def _selected_run_path(value: Any) -> Path | None:
    if not value:
        return None
    return Path(str(value))


def build_layout() -> dict[str, dict[str, Any]]:
    """Build the tabbed NiceGUI layout and return view refresh handles."""
    nicegui_app.add_static_files("/assets", services.ROOT / "assets")
    install_theme()
    ui.query(".nicegui-content").classes(PAGE_CLASS)

    controls: dict[str, dict[str, Any]] = {}
    with ui.header().classes(f"{HEADER_CLASS} items-center justify-between"):
        with ui.row().classes(f"{BRAND_CLASS} items-center"):
            ui.image(EAGLE_IMAGE_URL).classes(BRAND_IMAGE_CLASS)
            with ui.column().classes("gap-0"):
                ui.label("Eagle Observatory").classes(title_class("text-h5"))
                ui.label("Research dashboard").classes(SUBTITLE_CLASS)

    with ui.tabs().classes(f"{CARD_CLASS} w-full") as tabs:
        run_tab = ui.tab("Run").classes(TAB_CLASS)
        final_test_tab = ui.tab("Final Test").classes(TAB_CLASS)
        config_tab = ui.tab("Config").classes(TAB_CLASS)
        components_tab = ui.tab("Components").classes(TAB_CLASS)
        objectives_tab = ui.tab("Objectives").classes(TAB_CLASS)
        operators_tab = ui.tab("Operators").classes(TAB_CLASS)
        analysis_tab = ui.tab("Analysis").classes(TAB_CLASS)
        prompts_tab = ui.tab("Prompts").classes(TAB_CLASS)
        microrts_tab = ui.tab("MicroRTS").classes(TAB_CLASS)

    with ui.tab_panels(tabs, value=run_tab).classes(f"{PAGE_CLASS} w-full"):
        with ui.tab_panel(run_tab):
            controls["run"] = build_run_view(state)
        with ui.tab_panel(final_test_tab):
            controls["final_test"] = build_final_test_view(state)
        with ui.tab_panel(config_tab):
            controls["config"] = build_config_view(state)
        with ui.tab_panel(components_tab):
            controls["components"] = build_components_view(state)
        with ui.tab_panel(objectives_tab):
            controls["objectives"] = build_objectives_view(state)
        with ui.tab_panel(operators_tab):
            controls["operators"] = build_operators_view(state)
        with ui.tab_panel(analysis_tab):
            controls["analysis"] = build_analysis_view(state)
        with ui.tab_panel(prompts_tab):
            controls["prompts"] = build_prompts_view(state)
        with ui.tab_panel(microrts_tab):
            controls["microrts"] = build_microrts_view(state)

    async def on_tab_change(event: Any) -> None:
        selected = event.args

        if selected == prompts_tab:
            await controls["prompts"]["refresh_prompts"](True)

        if selected == analysis_tab:
            await controls["analysis"]["refresh_analysis"]()

    tabs.on("update:model-value", on_tab_change)
    return controls


controls = build_layout()


async def startup_refresh() -> None:
    """Load initial config, run choices, and logs after the UI is mounted."""
    try:
        payload = await asyncio.to_thread(services.load_config_payload, Path(state.config.base_config_path))
        services.apply_config_payload(state, payload, Path(state.config.base_config_path))
    except (OSError, ValueError):
        pass
    for group, name in (
        ("config", "refresh"),
        ("objectives", "refresh"),
        ("operators", "refresh"),
        ("components", "refresh"),
        ("microrts", "refresh_trace_choices"),
    ):
        refresh = controls.get(group, {}).get(name)
        if refresh:
            refresh()
    await controls["run"]["refresh_runs"]()
    await controls["final_test"]["refresh_runs"]()
    await controls["run"]["refresh_log"]()


async def refresh_log_timer() -> None:
    """Refresh process logs only; prompt loading is intentionally excluded."""
    await controls["run"]["refresh_log"]()
    await controls["final_test"]["refresh_log"]()
    await controls["microrts"]["refresh_status"]()


async def refresh_analysis_timer() -> None:
    """Refresh analysis independently from the log timer."""
    await controls["analysis"]["refresh_analysis"]()


ui.timer(0.1, startup_refresh, once=True)
ui.timer(3.0, refresh_log_timer)
ui.timer(15.0, refresh_analysis_timer)


def main() -> None:
    """Run the NiceGUI application."""
    port = services.find_available_port()
    ui.run(title="Eagle Observatory", favicon=EAGLE_IMAGE_URL, reload=False, show=True, port=port)


if __name__ in {"__main__", "__mp_main__"}:
    main()
