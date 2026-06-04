"""NiceGUI entrypoint for the EAGLE desktop workflow."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nicegui import app as nicegui_app
from nicegui import Client
from nicegui import ui

from eagle_ui import services
from eagle_ui.state import AppState
from eagle_ui.theme import (
    BRAND_CLASS,
    BRAND_IMAGE_CLASS,
    CARD_CLASS,
    HEADER_CLASS,
    PAGE_CLASS,
    SUBTITLE_CLASS,
    TAB_CLASS,
    install_theme,
    button_class,
    title_class,
)
from eagle_ui.ui_actions import safe_click
from eagle_ui.views.analysis_view import build_analysis_view
from eagle_ui.views.components_view import build_components_view
from eagle_ui.views.config_view import build_config_summary_view
from eagle_ui.views.examples_view import build_examples_view
from eagle_ui.views.final_test_view import build_final_test_view
from eagle_ui.views.microrts_view import build_microrts_view
from eagle_ui.views.objectives_view import build_objectives_view
from eagle_ui.views.operators_view import build_operators_view
from eagle_ui.views.llm_calls_view import build_llm_calls_view
from eagle_ui.views.run_view import build_run_view


services.configure_runtime_logging()
LOGGER = logging.getLogger(__name__)
state = AppState()
EAGLE_IMAGE_URL = "/assets/eagle.png"
EAGLE_FAVICON_URL = "/assets/eagle.png"
HEARTBEAT_INTERVAL_SEC = 2.0
HEARTBEAT_WARN_DELAY_SEC = 5.0


def on_client_connect(client: Any | None = None) -> None:
    """Log NiceGUI client connections without changing runtime behavior."""
    state.runtime.connected_client_count = connected_client_count()
    LOGGER.info(
        "client connected client_id=%s connected_client_count=%s",
        getattr(client, "id", None),
        state.runtime.connected_client_count,
    )


def on_client_disconnect(client: Any | None = None) -> None:
    """Log NiceGUI client disconnections without stopping the GUI or experiments."""
    state.runtime.connected_client_count = connected_client_count()
    LOGGER.info(
        "client disconnected client_id=%s connected_client_count=%s",
        getattr(client, "id", None),
        state.runtime.connected_client_count,
    )


def connected_client_count() -> int:
    """Return the number of NiceGUI client documents with an active socket."""
    count = 0
    for client in Client.instances.values():
        connections = getattr(client, "_num_connections", {})
        count += sum(1 for value in connections.values() if value > 0)
    return count


def heartbeat() -> None:
    """Record event-loop heartbeat timing for disconnect diagnostics."""
    now = time.monotonic()
    previous = state.runtime.last_heartbeat_monotonic
    state.runtime.last_heartbeat_monotonic = now
    state.runtime.last_heartbeat_timestamp = datetime.now().isoformat(timespec="seconds")
    if previous is None:
        LOGGER.info("event loop heartbeat started timestamp=%s", state.runtime.last_heartbeat_timestamp)
        return
    delay = now - previous
    if delay > HEARTBEAT_WARN_DELAY_SEC:
        LOGGER.warning("event loop heartbeat delayed delay_sec=%.3f", delay)


nicegui_app.on_connect(on_client_connect)
nicegui_app.on_disconnect(on_client_disconnect)


def build_layout() -> dict[str, dict[str, Any]]:
    """Build the tabbed NiceGUI layout and return view refresh handles."""
    nicegui_app.add_static_files("/assets", services.ROOT / "assets")
    install_theme()
    ui.add_head_html(f'<link rel="icon" type="image/png" href="{EAGLE_FAVICON_URL}">')
    ui.query(".nicegui-content").classes(PAGE_CLASS)

    controls: dict[str, dict[str, Any]] = {}

    async def stop_experiment() -> None:
        """Stop active experiment processes while keeping the GUI alive."""
        if state.is_stopping:
            ui.notify("Stop already in progress", type="warning")
            return
        ui.notify("Stopping experiment...")
        message = await asyncio.to_thread(services.stop_experiment, state)
        ui.notify(message, type="positive")
        for group, name in (("run", "refresh_status"), ("final_test", "refresh_status"), ("microrts", "refresh_status")):
            refresh = controls.get(group, {}).get(name)
            if refresh:
                await refresh()

    async def shutdown_gui() -> None:
        """Stop runtime helpers and exit the NiceGUI app."""
        if state.is_shutting_down:
            ui.notify("GUI shutdown already in progress", type="warning")
            return
        state.is_shutting_down = True
        ui.notify("Shutting down GUI...")
        await asyncio.sleep(0.2)
        await asyncio.to_thread(services.shutdown_runtime, state)
        services.shutdown_app(state, nicegui_app)

    async def full_refresh_current_page() -> None:
        """Refresh only the currently visible page to keep UI actions responsive."""
        page = state.runtime.current_page
        LOGGER.info("manual refresh start page=%s", page)
        if page == "experiment":
            for group in ("components", "examples", "operators", "objectives", "config_summary"):
                refresh = controls.get(group, {}).get("refresh")
                if refresh:
                    result = refresh()
                    if asyncio.iscoroutine(result):
                        await result
            await controls["run"]["full_refresh"]()
        elif page == "run":
            await controls["run"]["full_refresh"]()
        elif page == "final_test":
            await controls["final_test"]["refresh_all"]()
        elif page == "analysis":
            analysis_refresh_runs = controls.get("analysis", {}).get("refresh_runs")
            if analysis_refresh_runs:
                await analysis_refresh_runs()
            await controls["analysis"]["refresh_analysis"]()
        elif page == "LLM Calls":
            await controls["llm_calls"]["refresh_llm_calls"](True)
        elif page == "microrts":
            await controls["microrts"]["refresh_status"]()
        else:
            refresh = controls.get(page, {}).get("refresh")
            if refresh:
                result = refresh()
                if asyncio.iscoroutine(result):
                    await result
        LOGGER.info("manual refresh end page=%s", page)

    with ui.header().classes(f"{HEADER_CLASS} items-center justify-between"):
        with ui.row().classes(f"{BRAND_CLASS} items-center"):
            ui.image(EAGLE_IMAGE_URL).classes(BRAND_IMAGE_CLASS)
            with ui.column().classes("gap-0"):
                ui.label("Eagle").classes(title_class("text-h5"))
                ui.label("EA for Gameplay LLM-agEnt").classes(SUBTITLE_CLASS)
        with ui.row().classes("items-center gap-2"):
            ui.button("Full Refresh", on_click=safe_click(full_refresh_current_page, label="Full refresh")).classes(
                button_class(success=True)
            )
            ui.button("Stop Experiment", on_click=safe_click(stop_experiment, label="Stop Experiment")).classes(
                button_class(danger=True)
            )
            ui.button("Shutdown GUI", on_click=safe_click(shutdown_gui, label="Shutdown GUI")).classes(
                button_class(danger=True)
            )

    with ui.tabs().classes(f"{CARD_CLASS} w-full") as tabs:
        experiment_tab = ui.tab("Experiment").classes(TAB_CLASS)
        final_test_tab = ui.tab("Final Test").classes(TAB_CLASS)
        analysis_tab = ui.tab("Analysis").classes(TAB_CLASS)
        llm_calls_tab = ui.tab("LLM Calls").classes(TAB_CLASS)
        microrts_tab = ui.tab("MicroRTS").classes(TAB_CLASS)

    with ui.tab_panels(tabs, value=experiment_tab).classes(f"{PAGE_CLASS} w-full"):
        with ui.tab_panel(experiment_tab):
            with ui.row().classes("w-full gap-4 items-start flex-wrap xl:flex-nowrap"):
                with ui.column().classes("w-full xl:flex-[3_1_0] min-w-[0] gap-3"):
                    with ui.tabs().classes(f"{CARD_CLASS} w-full") as experiment_tabs:
                        components_tab = ui.tab("Components").classes(TAB_CLASS)
                        examples_tab = ui.tab("Examples").classes(TAB_CLASS)
                        operators_tab = ui.tab("Algorithm").classes(TAB_CLASS)
                        objectives_tab = ui.tab("Objectives").classes(TAB_CLASS)
                    with ui.tab_panels(experiment_tabs, value=components_tab).classes(f"{PAGE_CLASS} w-full"):
                        with ui.tab_panel(components_tab):
                            controls["components"] = build_components_view(state)
                            state.runtime.components_refresh = controls["components"].get("refresh")
                        with ui.tab_panel(examples_tab):
                            controls["examples"] = build_examples_view(state)
                        with ui.tab_panel(operators_tab):
                            controls["operators"] = build_operators_view(state)
                            state.runtime.operators_refresh = controls["operators"].get("refresh")
                        with ui.tab_panel(objectives_tab):
                            controls["objectives"] = build_objectives_view(state)
                            state.runtime.objectives_refresh = controls["objectives"].get("refresh")
                with ui.column().classes("w-full xl:flex-[2_1_420px] min-w-[360px] gap-3"):
                    controls["run"] = build_run_view(state, log_height=300)
                    controls["config_summary"] = build_config_summary_view(state)
        with ui.tab_panel(final_test_tab):
            controls["final_test"] = build_final_test_view(state)
        with ui.tab_panel(analysis_tab):
            controls["analysis"] = build_analysis_view(state)
            state.runtime.analysis_runs_refresh = controls["analysis"].get("refresh_runs")
        with ui.tab_panel(llm_calls_tab):
            controls["llm_calls"] = build_llm_calls_view(state)
        with ui.tab_panel(microrts_tab):
            controls["microrts"] = build_microrts_view(state)

    async def on_tab_change(event: Any) -> None:
        """Refresh tab-specific data when the user changes the top-level page."""
        selected = event.args

        if selected == experiment_tab:
            state.runtime.current_page = "experiment"
            await controls["run"]["refresh_log"]()
        elif selected == final_test_tab:
            state.runtime.current_page = "final_test"
            await controls["final_test"]["refresh_all"]()
        elif selected == llm_calls_tab:
            state.runtime.current_page = "llm_calls"
            await controls["llm_calls"]["refresh_llm_calls"](True)
        elif selected == analysis_tab:
            state.runtime.current_page = "analysis"
            analysis_refresh_runs = controls.get("analysis", {}).get("refresh_runs")
            if analysis_refresh_runs:
                await analysis_refresh_runs()
            await controls["analysis"]["refresh_analysis"]()
        elif selected == microrts_tab:
            state.runtime.current_page = "microrts"

    tabs.on("update:model-value", on_tab_change)
    return controls


controls = build_layout()


async def startup_refresh() -> None:
    """Load initial config, run choices, and logs after the UI is mounted."""
    try:
        payload = await asyncio.to_thread(services.load_config_payload, Path(state.config.base_config_path))
        services.apply_config_payload(state, payload, Path(state.config.base_config_path))
    except (OSError, ValueError):
        LOGGER.exception("Startup refresh failed to load initial config path=%s", state.config.base_config_path)
        pass
    for group, name in (
        ("objectives", "refresh"),
        ("operators", "refresh"),
        ("components", "refresh"),
        ("config_summary", "refresh"),
        ("microrts", "refresh_trace_choices"),
    ):
        refresh = controls.get(group, {}).get(name)
        if refresh:
            refresh()
    await controls["run"]["refresh_runs"]()
    analysis_refresh_runs = controls.get("analysis", {}).get("refresh_runs")
    if analysis_refresh_runs:
        await analysis_refresh_runs()
    await controls["final_test"]["refresh_runs"]()
    await controls["final_test"]["refresh_all"]()
    await controls["run"]["refresh_log"]()


startup_timer = ui.timer(0.1, safe_click(startup_refresh, label="Startup refresh"), once=True)
heartbeat_timer = ui.timer(HEARTBEAT_INTERVAL_SEC, heartbeat)
state.active_timers.extend([startup_timer, heartbeat_timer])


def main() -> None:
    """Run the NiceGUI application."""
    port = services.find_available_port()
    host = None
    reload = False
    show = True
    native = False
    LOGGER.info("GUI starting")
    LOGGER.info("host=%s", host or "NiceGUI default")
    LOGGER.info("port=%s", port)
    LOGGER.info("reload=%s native=%s show=%s", reload, native, show)
    LOGGER.info("python_version=%s", sys.version.replace(os.linesep, " "))
    LOGGER.info("working_directory=%s", Path.cwd())
    LOGGER.info("runtime_log_path=%s", services.RUNTIME_LOG_PATH)
    ui.run(title="Eagle", reload=reload, show=show, port=port)


if __name__ in {"__main__", "__mp_main__"}:
    main()
