"""Servers surface: resolved configuration, lifecycle, and durable diagnostics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nicegui import ui

from eagle.runtime.server_manager import canonical_local_model_id
from eagle_ui.components.log_panel import create_log_panel
from eagle_ui.controllers.llm_controller import LLMConfigController
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def build_llm_view(
    controller: LLMConfigController, repository_root: Path
) -> None:
    model_options = {
        str(path): canonical_local_model_id(path) or path.name
        for path in controller.server_models()
    }
    default_model = next(iter(model_options), None)
    display_options = model_options or {"": "No .gguf models discovered"}

    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Servers").classes("text-h6")
        ui.label(
            "Local managed lifecycle or remote LAN endpoint validation"
        ).classes("text-caption")
        with ui.grid(columns=4).classes("w-full gap-3"):
            server_id = ui.input(
                "Server identifier", value="local-llm"
            ).classes(INPUT_CLASS)
            location = ui.select(
                {
                    "local": "Local managed",
                    "remote": "Remote",
                },
                label="Server type",
                value="local",
            ).classes(INPUT_CLASS)
            model_path = ui.select(
                display_options,
                label="Local model",
                value=default_model,
                with_input=False,
            ).classes(INPUT_CLASS)
            model_id = ui.input(
                "Served model ID",
                value=(
                    canonical_local_model_id(Path(default_model))
                    if default_model
                    else ""
                ),
            ).classes(INPUT_CLASS)
            server_path = ui.input(
                "llama-server executable (empty uses PATH)"
            ).classes(INPUT_CLASS)
            bind_host = ui.input("Bind host", value="127.0.0.1").classes(
                INPUT_CLASS
            )
            client_host = ui.input(
                "Client host", value="127.0.0.1"
            ).classes(INPUT_CLASS)
            port = ui.number(
                "Port", value=8080, min=1, max=65535
            ).classes(INPUT_CLASS)
            context_size = ui.number(
                "Context size", value=32768, min=1
            ).classes(INPUT_CLASS)
            gpu_layers = ui.input(
                "GPU layers (0, count, or auto)", value="auto"
            ).classes(INPUT_CLASS)
            gpu_required = ui.checkbox(
                "Require usable GPU backend", value=False
            )
            device = ui.input(
                "llama.cpp device (optional)"
            ).classes(INPUT_CLASS)
            cuda_visible_devices = ui.input(
                "CUDA_VISIBLE_DEVICES (optional)"
            ).classes(INPUT_CLASS)
            roles = ui.select(
                ["reflector", "rewriter", "generator"],
                label="Assigned roles",
                multiple=True,
                value=["reflector", "rewriter", "generator"],
            ).classes(f"{INPUT_CLASS} w-full")
        with ui.row().classes("gap-2"):
            start_button = ui.button("Start / validate").classes(BUTTON_CLASS)
            stop_button = ui.button("Stop").classes(BUTTON_CLASS)
            restart_button = ui.button("Restart").classes(BUTTON_CLASS)
            refresh_button = ui.button("Refresh status").classes(BUTTON_CLASS)
        server_select = ui.select(
            {}, label="Selected server"
        ).classes(f"{INPUT_CLASS} w-full")
        status = ui.textarea("Server status").props(
            "readonly autogrow=false"
        ).classes(f"{INPUT_CLASS} w-full h-80")
        log = create_log_panel(
            height_px=320,
            on_clear=lambda: controller.clear_server_logs(
                str(server_select.value or "")
            ),
        )

    def update_model_id(event) -> None:
        selected = str(event.value or "")
        if selected:
            model_id.value = (
                canonical_local_model_id(Path(selected)) or Path(selected).stem
            )
            model_id.update()

    model_path.on_value_change(update_model_id)

    def spec_values() -> dict[str, object]:
        location_type = str(location.value or "local")
        selected = str(model_path.value or "")
        configured_model_id = str(model_id.value or "").strip()
        if not configured_model_id:
            raise ValueError("Enter the model ID exposed by the server.")
        if location_type == "local" and not selected:
            raise ValueError(
                "Select an existing .gguf model before starting a local server."
            )
        raw_gpu_layers = str(gpu_layers.value or "").strip()
        parsed_gpu_layers: int | str | None
        if not raw_gpu_layers:
            parsed_gpu_layers = None
        elif raw_gpu_layers.lstrip("-").isdigit():
            parsed_gpu_layers = int(raw_gpu_layers)
        else:
            parsed_gpu_layers = raw_gpu_layers
        environment = ()
        cuda_value = str(cuda_visible_devices.value or "").strip()
        if cuda_value:
            environment = (("CUDA_VISIBLE_DEVICES", cuda_value),)
        return {
            "server_id": str(server_id.value or "").strip(),
            "model_path": Path(selected) if selected and location_type == "local" else None,
            "server_path": str(server_path.value or "").strip() or None,
            "model_id": configured_model_id,
            "host": str(bind_host.value or "127.0.0.1").strip(),
            "client_host": str(client_host.value or "").strip(),
            "port": int(port.value or 0),
            "context_size": int(context_size.value or 0),
            "roles": tuple(str(item) for item in (roles.value or ())),
            "location_type": location_type,
            "gpu_layers": parsed_gpu_layers,
            "gpu_required": bool(gpu_required.value),
            "device": str(device.value or "").strip() or None,
            "environment_overrides": environment,
        }

    async def refresh_status() -> None:
        try:
            items = await asyncio.to_thread(controller.server_statuses)
        except RuntimeError as exc:
            status.value = f"Cannot read server status: {exc}"
            status.update()
            return
        server_select.options = {item.server_id: item.server_id for item in items}
        if items and not server_select.value:
            server_select.value = items[0].server_id
        server_select.update()
        selected = next(
            (item for item in items if item.server_id == server_select.value),
            None,
        )
        if selected:
            status.value = json.dumps(
                {
                    "server_id": selected.server_id,
                    "server_type": selected.location_type,
                    "state": selected.state,
                    "pid": selected.pid,
                    "exit_code": selected.exit_code,
                    "executable": selected.executable,
                    "model_id": selected.model_id,
                    "model_path": selected.model_path,
                    "roles": selected.roles,
                    "bind_host": selected.bind_host,
                    "client_host": selected.client_host,
                    "port": selected.port,
                    "base_url": selected.base_url,
                    "api_endpoint": selected.api_endpoint,
                    "health_url": selected.health_url,
                    "startup_elapsed_seconds": selected.elapsed_startup_seconds,
                    "last_health_check": selected.last_health_check,
                    "gpu_expected": selected.gpu_expected,
                    "gpu_backend_available": selected.gpu_backend_available,
                    "cuda_startup_evidence": selected.cuda_evidence,
                    "working_directory": selected.working_directory,
                    "environment_overrides": selected.environment_overrides,
                    "log_path": selected.log_path,
                    "failure_reason": selected.error,
                    "command": selected.command,
                },
                ensure_ascii=False,
                indent=2,
            )
            status.update()
            log.set_buffer(
                type(
                    "SelectedLog",
                    (),
                    {"snapshot": lambda self: selected.logs},
                )()
            )
        else:
            status.value = (
                "No server records. Start a local server or validate a remote "
                "endpoint to see its lifecycle and output."
            )
            status.update()

    async def start() -> None:
        try:
            values = spec_values()
            item = await asyncio.to_thread(controller.start_server, **values)
        except (OSError, ValueError, RuntimeError):
            await refresh_status()
            return
        server_select.value = item.server_id
        server_select.update()
        await refresh_status()

    async def stop() -> None:
        selected_id = str(server_select.value or server_id.value or "").strip()
        try:
            await asyncio.to_thread(controller.stop_server, selected_id)
        except (OSError, ValueError, RuntimeError) as exc:
            status.value = f"Stop failed: {exc}"
            status.update()
            return
        await refresh_status()

    async def restart() -> None:
        await stop()
        await start()

    start_button.on_click(start)
    stop_button.on_click(stop)
    restart_button.on_click(restart)
    refresh_button.on_click(refresh_status)
    server_select.on_value_change(lambda _: refresh_status())
    ui.timer(0.5, refresh_status)


def build_profile_configuration(
    controller: LLMConfigController, repository_root: Path
) -> None:
    path = ui.input(
        "Role endpoint configuration",
        value=str(
            repository_root / "experiment_env" / "config" / "llm_topology.json"
        ),
    ).classes(f"{INPUT_CLASS} w-full")
    result = ui.textarea("Role assignment status").props(
        "readonly"
    ).classes(f"{INPUT_CLASS} w-full h-32")
    load_button = ui.button("Load role assignments").classes(BUTTON_CLASS)

    async def load() -> None:
        try:
            profiles = await asyncio.to_thread(
                controller.load, Path(str(path.value))
            )
        except (OSError, ValueError) as exc:
            result.value = f"Cannot load role assignments: {exc}"
            result.update()
            return
        result.value = json.dumps(
            {role: profile.to_dict() for role, profile in profiles.items()},
            ensure_ascii=False,
            indent=2,
        )
        result.update()

    load_button.on_click(load)
