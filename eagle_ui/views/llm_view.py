"""Servers surface: configuration plus one selected-server diagnostic log."""
from __future__ import annotations
import asyncio, json
from pathlib import Path
from nicegui import ui
from eagle.llm_profiles import LLMProfile
from eagle_ui.components.log_panel import create_log_panel
from eagle_ui.controllers.llm_controller import LLMConfigController
from eagle.runtime.server_manager import canonical_local_model_id
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS

def build_llm_view(controller: LLMConfigController, repository_root: Path) -> None:
    model_options = {str(path): canonical_local_model_id(path) or path.name for path in controller.server_models()}
    if not model_options: model_options = {"": "No .gguf models discovered"}
    with ui.column().classes(f"{CARD_CLASS} w-full gap-3"):
        ui.label("Servers").classes("text-h6")
        ui.label("Local server lifecycle and endpoint diagnostics").classes("text-caption")
        with ui.grid(columns=4).classes("w-full gap-3"):
            server_id=ui.input("Server identifier", value="local-llm").classes(INPUT_CLASS)
            location=ui.select({"local":"Current EA machine","remote":"Configured LAN machine"}, label="Location", value="local").classes(INPUT_CLASS)
            model_path=ui.select(model_options, label="Local model", with_input=False).classes(INPUT_CLASS)
            server_path=ui.input("llama-server executable (empty uses PATH)").classes(INPUT_CLASS)
            host=ui.input("Bind host", value="127.0.0.1").classes(INPUT_CLASS)
            port=ui.number("Port", value=8080, min=1, max=65535).classes(INPUT_CLASS)
            context_size=ui.number("Context size", value=32768, min=1).classes(INPUT_CLASS)
            roles=ui.select(["reflector","rewriter","generator"], label="Assigned roles", multiple=True, value=["reflector","rewriter","generator"]).classes(f"{INPUT_CLASS} w-full")
        with ui.row().classes("gap-2"):
            start_button=ui.button("Start server").classes(BUTTON_CLASS); stop_button=ui.button("Stop server").classes(BUTTON_CLASS); restart_button=ui.button("Restart server").classes(BUTTON_CLASS); refresh_button=ui.button("Refresh status").classes(BUTTON_CLASS)
        server_select=ui.select({}, label="Selected server").classes(f"{INPUT_CLASS} w-full")
        status=ui.textarea("Server status").props("readonly autogrow=false").classes(f"{INPUT_CLASS} w-full h-32")
        log=create_log_panel(height_px=320, on_clear=lambda: controller.clear_server_logs(str(server_select.value or "")))

    def spec_values():
        selected=str(model_path.value or "")
        if not selected: raise ValueError("Select an existing .gguf model before starting a local server.")
        if location.value == "remote": raise ValueError("Remote servers must be configured through their endpoint and tested from the GUI.")
        return {"server_id":str(server_id.value or "").strip(),"model_path":Path(selected),"server_path":str(server_path.value or "").strip() or None,"model_id":canonical_local_model_id(Path(selected)) or Path(selected).stem,"host":str(host.value or "127.0.0.1").strip(),"port":int(port.value or 0),"context_size":int(context_size.value or 0),"roles":tuple(str(item) for item in (roles.value or ()))}

    async def refresh_status() -> None:
        try: items=await asyncio.to_thread(controller.server_statuses)
        except RuntimeError: items=[]
        server_select.options={item.server_id:item.server_id for item in items}
        if items and not server_select.value: server_select.value=items[0].server_id
        server_select.update()
        selected=next((item for item in items if item.server_id == server_select.value), None)
        if selected:
            status.value=json.dumps({"server_id":selected.server_id,"state":selected.state,"endpoint":selected.endpoint,"model_id":selected.model_id,"roles":selected.roles,"pid":selected.pid,"returncode":selected.state.split(":",1)[1] if ":" in selected.state else None}, indent=2); status.update(); log.set_buffer(type("B",(),{"snapshot":lambda self:selected.logs})())
        elif not items:
            status.value="No managed servers. Start a local server to see its output."; status.update()

    async def start():
        try: await asyncio.to_thread(controller.start_server, **spec_values())
        except (OSError,ValueError,RuntimeError) as exc: status.value=f"Start failed: {exc}"; status.update(); return
        await refresh_status()
    async def stop():
        try: await asyncio.to_thread(controller.stop_server, str(server_id.value or "").strip())
        except (OSError,ValueError,RuntimeError) as exc: status.value=f"Stop failed: {exc}"; status.update(); return
        await refresh_status()
    async def restart():
        await stop(); await start()
    start_button.on_click(start); stop_button.on_click(stop); restart_button.on_click(restart); refresh_button.on_click(refresh_status); server_select.on_value_change(lambda _: refresh_status()); ui.timer(0.5, refresh_status)

def build_profile_configuration(controller: LLMConfigController, repository_root: Path) -> None:
    path=ui.input("Role endpoint configuration", value=str(repository_root/"experiment_env"/"config"/"llm_topology.json")).classes(f"{INPUT_CLASS} w-full")
    result=ui.textarea("Role assignment status").props("readonly").classes(f"{INPUT_CLASS} w-full h-32")
    load_button=ui.button("Load role assignments").classes(BUTTON_CLASS)
    async def load():
        try: profiles=await asyncio.to_thread(controller.load, Path(str(path.value)))
        except (OSError,ValueError) as exc: result.value=f"Cannot load role assignments: {exc}"; result.update(); return
        result.value=json.dumps({role:profile.to_dict() for role,profile in profiles.items()}, ensure_ascii=False, indent=2); result.update()
    load_button.on_click(load)