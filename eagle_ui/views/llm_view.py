"""Servers view for local and configured remote EAGLE LLM endpoints."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from nicegui import ui

from eagle.llm_profiles import LLMProfile
from eagle_ui.controllers.llm_controller import LLMConfigController
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def build_llm_view(controller: LLMConfigController, repository_root: Path) -> None:
    model_choices = controller.server_models()
    model_options = {str(path): path.name for path in model_choices}
    if not model_options:
        model_options = {"": "No .gguf models discovered"}
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Servers").classes("text-h6")
        ui.label("One GUI-owned local server lifecycle; remote endpoints are inspected and assigned, not launched here.").classes("text-caption")
        with ui.grid(columns=4).classes("w-full gap-3"):
            server_id = ui.input("Server identifier", value="local-llm").classes(INPUT_CLASS)
            location = ui.select({"local": "Current EA machine", "remote": "Configured LAN machine"}, label="Location", value="local").classes(INPUT_CLASS)
            model_path = ui.select(model_options, label="Discovered .gguf model", with_input=True).classes(INPUT_CLASS)
            model_id = ui.input("Model identifier", value="local-model").classes(INPUT_CLASS)
            server_path = ui.input("llama-server executable (empty uses PATH)").classes(INPUT_CLASS)
            host = ui.input("Bind host", value="127.0.0.1").classes(INPUT_CLASS)
            port = ui.number("Port", value=8080, min=1, max=65535).classes(INPUT_CLASS)
            context_size = ui.number("Context size", value=32768, min=1).classes(INPUT_CLASS)
            roles = ui.select(["reflector", "rewriter", "generator"], label="Assigned roles", multiple=True, value=["reflector", "rewriter", "generator"]).classes(f"{INPUT_CLASS} w-full")
        with ui.row().classes("gap-2"):
            start_button = ui.button("Start server").classes(BUTTON_CLASS)
            stop_button = ui.button("Stop server").classes(BUTTON_CLASS)
            restart_button = ui.button("Restart server").classes(BUTTON_CLASS)
            refresh_button = ui.button("Refresh status").classes(BUTTON_CLASS)
        status = ui.textarea("Server status and captured output").props("readonly").classes("w-full h-48 font-mono")

    async def refresh_status() -> None:
        try:
            items = await asyncio.to_thread(controller.server_statuses)
        except RuntimeError:
            items = []
        status.value = json.dumps([item.__dict__ for item in items], ensure_ascii=False, indent=2)
        status.update()

    def spec_values() -> dict[str, object]:
        selected_model = str(model_path.value or "")
        if not selected_model:
            raise ValueError("Select an existing .gguf model before starting a local server.")
        if location.value == "remote":
            raise ValueError("Remote servers must be configured through their endpoint and tested from the GUI.")
        return {
            "server_id": str(server_id.value or "").strip(),
            "model_path": Path(selected_model),
            "server_path": str(server_path.value or "").strip() or None,
            "model_id": str(model_id.value or "").strip(),
            "host": str(host.value or "127.0.0.1").strip(),
            "port": int(port.value or 0),
            "context_size": int(context_size.value or 0),
            "roles": tuple(str(item) for item in (roles.value or ())),
        }

    async def start() -> None:
        try:
            values = spec_values()
            item = await asyncio.to_thread(controller.start_server, **values)
        except (OSError, ValueError, RuntimeError) as exc:
            status.value = f"Start failed: {exc}"
            status.update()
            return
        status.value = json.dumps(item.__dict__, ensure_ascii=False, indent=2)
        status.update()

    async def stop() -> None:
        try:
            item = await asyncio.to_thread(controller.stop_server, str(server_id.value or "").strip())
        except (OSError, ValueError, RuntimeError) as exc:
            status.value = f"Stop failed: {exc}"
            status.update()
            return
        status.value = json.dumps(item.__dict__, ensure_ascii=False, indent=2)
        status.update()

    async def restart() -> None:
        try:
            values = spec_values()
            item = await asyncio.to_thread(controller.stop_server, str(values["server_id"]))
            item = await asyncio.to_thread(controller.start_server, **values)
        except (OSError, ValueError, RuntimeError) as exc:
            status.value = f"Restart failed: {exc}"
            status.update()
            return
        status.value = json.dumps(item.__dict__, ensure_ascii=False, indent=2)
        status.update()

    start_button.on_click(start)
    stop_button.on_click(stop)
    restart_button.on_click(restart)
    refresh_button.on_click(refresh_status)
    ui.timer(0.5, refresh_status)


def build_profile_configuration(controller: LLMConfigController, repository_root: Path) -> None:
    """Keep endpoint assignment editing in the same Servers surface."""
    path = ui.input("Role endpoint configuration", value=str(repository_root / "experiment_env" / "config" / "llm_topology.json")).classes(f"{INPUT_CLASS} w-full")
    result = ui.textarea("Role assignment status").props("readonly").classes("w-full h-32 font-mono")
    load_button = ui.button("Load role assignments").classes(BUTTON_CLASS)

    async def load() -> None:
        try:
            profiles = await asyncio.to_thread(controller.load, Path(str(path.value)))
        except (OSError, ValueError) as exc:
            result.value = f"Cannot load role assignments: {exc}"
            result.update()
            return
        result.value = json.dumps({role: profile.to_dict() for role, profile in profiles.items()}, ensure_ascii=False, indent=2)
        result.update()

    load_button.on_click(load)