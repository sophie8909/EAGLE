"""NiceGUI dashboard prototype for EAGLE."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_gui_web import services


class DashboardState:
    """Mutable UI state for the dashboard session."""

    def __init__(self) -> None:
        """Create default dashboard state."""
        choices = services.config_choices()
        self.config_path = choices[0]
        self.config_name = services.timestamped_stem("gui_web_evolution")
        self.current_run_dir: Path | None = None
        self.prompt_records: dict[str, dict[str, Any]] = {}
        self.prompt_options: dict[str, str] = {}
        self.selected_prompt_id = ""
        self.last_log_text = ""
        self.last_analysis_body = ""
        self.last_prompt_signature: tuple[str | None, tuple[str, ...]] | None = None


state = DashboardState()


def status_color(status: str) -> str:
    """Return a NiceGUI color name for the process status."""
    return "positive" if status.startswith("running") else "grey"


def selected_run_path(value: Any) -> Path | None:
    """Convert a run selector value into a path."""
    if not value:
        return None
    return Path(str(value))


async def refresh_status() -> None:
    """Refresh the process status badge."""
    status = await asyncio.to_thread(services.process_status_text)
    status_badge.set_text(status)
    status_badge.props(f"color={status_color(status)}")


async def refresh_runs() -> None:
    """Refresh run selector choices without changing a valid selection."""
    runs = await asyncio.to_thread(services.run_choices)
    run_select.options = runs
    if state.current_run_dir is None and runs:
        state.current_run_dir = Path(runs[0])
        run_select.value = runs[0]
        await refresh_analysis()
        await refresh_prompts(force=True)
    elif state.current_run_dir is not None and str(state.current_run_dir) not in runs:
        state.current_run_dir = Path(runs[0]) if runs else None
        run_select.value = str(state.current_run_dir) if state.current_run_dir else None
        await refresh_analysis()
        await refresh_prompts(force=True)
    run_select.update()


async def refresh_log() -> None:
    """Refresh only the log textarea and process badge."""
    await refresh_status()
    text = await asyncio.to_thread(services.read_log_tail)
    if text != state.last_log_text:
        state.last_log_text = text
        log_textarea.value = text
        log_textarea.update()


async def refresh_analysis() -> None:
    """Refresh the analysis panel independently from log refreshes."""
    try:
        summary, body = await asyncio.to_thread(services.build_analysis, state.current_run_dir)
    except Exception as exc:
        summary, body = "Analysis load error", str(exc)
    analysis_summary.set_text(summary)
    if body != state.last_analysis_body:
        state.last_analysis_body = body
        analysis_textarea.value = body
        analysis_textarea.update()


async def refresh_prompts(*, force: bool = False) -> None:
    """Refresh prompt records on demand or when the selected run changes."""
    run_key = str(state.current_run_dir) if state.current_run_dir else None
    if not force and state.last_prompt_signature and state.last_prompt_signature[0] == run_key:
        return
    try:
        records = await asyncio.to_thread(services.load_prompt_records, state.current_run_dir)
    except Exception as exc:
        records = {
            "error": {
                "prompt": "",
                "llm_output": str(exc),
                "generation": "",
                "individual_id": "load error",
                "evaluation_mode": "",
            }
        }
    options = {record_id: services.prompt_record_label(record_id, record) for record_id, record in records.items()}
    signature = (run_key, tuple(options))
    if not force and signature == state.last_prompt_signature:
        return
    state.prompt_records = records
    state.prompt_options = options
    state.last_prompt_signature = signature
    prompt_select.options = options
    if options:
        state.selected_prompt_id = next(iter(options))
        prompt_select.value = state.selected_prompt_id
    else:
        state.selected_prompt_id = ""
        prompt_select.value = None
    prompt_select.update()
    render_selected_prompt()


def render_selected_prompt() -> None:
    """Render the currently selected prompt record."""
    record = state.prompt_records.get(state.selected_prompt_id, {})
    prompt_textarea.value = str(record.get("prompt") or "")
    llm_output_textarea.value = str(record.get("llm_output") or "")
    prompt_textarea.update()
    llm_output_textarea.update()


async def on_start() -> None:
    """Start an experiment from the selected config path."""
    success, message = await asyncio.to_thread(services.start_experiment, Path(state.config_path))
    ui.notify(message, type="positive" if success else "warning")
    await refresh_status()
    await refresh_log()


async def on_stop() -> None:
    """Stop the monitored experiment process tree."""
    message = await asyncio.to_thread(services.stop_experiment)
    ui.notify(message)
    await refresh_status()


async def on_refresh() -> None:
    """Refresh all lightweight dashboard panels."""
    await refresh_runs()
    await refresh_log()
    await refresh_analysis()


async def on_refresh_prompts() -> None:
    """Refresh prompt records for the current run."""
    await refresh_prompts(force=True)


async def on_run_changed(event: Any) -> None:
    """Update selected run and refresh run-scoped panels."""
    state.current_run_dir = selected_run_path(event.value)
    await refresh_analysis()
    await refresh_prompts(force=True)


def on_prompt_changed(event: Any) -> None:
    """Update the prompt and response textareas for the selector value."""
    state.selected_prompt_id = str(event.value or "")
    render_selected_prompt()


ui.colors(primary="#1f6f5b", secondary="#3b5d7a", accent="#b06d2c")

with ui.header().classes("items-center justify-between"):
    ui.label("EAGLE Dashboard").classes("text-h5")
    status_badge = ui.badge("not running", color="grey")

with ui.tabs().classes("w-full") as tabs:
    run_tab = ui.tab("Run")
    analysis_tab = ui.tab("Analysis")
    prompts_tab = ui.tab("Prompts")

with ui.tab_panels(tabs, value=run_tab).classes("w-full"):
    with ui.tab_panel(run_tab):
        with ui.row().classes("w-full gap-4"):
            config_select = ui.select(
                services.config_choices(),
                label="Base config",
                value=state.config_path,
                on_change=lambda event: setattr(state, "config_path", str(event.value)),
            ).classes("min-w-[360px]")
            ui.input(
                "Config name",
                value=state.config_name,
                on_change=lambda event: setattr(state, "config_name", str(event.value or "")),
            ).classes("min-w-[260px]")
        with ui.row().classes("items-center gap-2"):
            ui.button("Start experiment", on_click=on_start)
            ui.button("Stop process", on_click=on_stop, color="negative")
            ui.button("Refresh", on_click=on_refresh)
        ui.separator()
        run_select = ui.select(
            [],
            label="Run",
            on_change=on_run_changed,
        ).classes("w-full")
        ui.label("Live log").classes("text-subtitle1")
        log_textarea = ui.textarea(value="").props("readonly").classes("w-full font-mono")
        log_textarea.style("height: 460px")

    with ui.tab_panel(analysis_tab):
        with ui.row().classes("items-center gap-2"):
            analysis_summary = ui.label("No run selected")
            ui.button("Refresh analysis", on_click=refresh_analysis)
        analysis_textarea = ui.textarea(value="").props("readonly").classes("w-full font-mono")
        analysis_textarea.style("height: 620px")

    with ui.tab_panel(prompts_tab):
        with ui.row().classes("items-center gap-2 w-full"):
            prompt_select = ui.select(
                {},
                label="Prompt record",
                on_change=on_prompt_changed,
            ).classes("grow")
            ui.button("Refresh prompts", on_click=on_refresh_prompts)
        with ui.row().classes("w-full gap-4"):
            prompt_textarea = ui.textarea(label="Prompt", value="").props("readonly").classes("grow font-mono")
            llm_output_textarea = ui.textarea(label="LLM output", value="").props("readonly").classes("grow font-mono")
        prompt_textarea.style("height: 620px")
        llm_output_textarea.style("height: 620px")


ui.timer(0.1, refresh_status, once=True)
ui.timer(0.2, refresh_runs, once=True)
ui.timer(0.3, refresh_log, once=True)
ui.timer(3.0, refresh_log)
ui.timer(15.0, refresh_analysis)


def find_available_port(start: int = 8080, attempts: int = 50) -> int:
    """Return the first available local TCP port at or above the start port."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No available port found from {start} to {start + attempts - 1}.")


def main() -> None:
    """Run the NiceGUI dashboard."""
    port = find_available_port()
    ui.run(title="EAGLE Dashboard", reload=False, show=True, port=port)


if __name__ in {"__main__", "__mp_main__"}:
    main()
