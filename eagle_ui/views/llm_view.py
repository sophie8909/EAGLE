"""LLM role configuration page."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse

from nicegui import ui

from eagle.llm_profiles import LLMProfile
from eagle_ui.controllers.llm_controller import LLMConfigController
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS


def build_llm_view(controller: LLMConfigController, repository_root: Path) -> None:
    role_controls: dict[str, dict[str, object]] = {}
    loaded: dict[str, LLMProfile] = {}
    config_path = ui.input(
        "Configuration source file",
        value=str(repository_root / "config" / "llm_endpoints.toml"),
    ).classes(f"{INPUT_CLASS} w-full")
    result = ui.textarea("Connection result").props("readonly").classes("w-full h-44 font-mono")

    with ui.row().classes("gap-2"):
        load_button = ui.button("Load configuration").classes(BUTTON_CLASS)
        save_button = ui.button("Save configuration").classes(BUTTON_CLASS)
        reload_button = ui.button("Reload").classes(BUTTON_CLASS)
    container = ui.row().classes("w-full gap-3 items-start")

    def render(profiles: dict[str, LLMProfile]) -> None:
        loaded.clear()
        loaded.update(profiles)
        role_controls.clear()
        container.clear()
        with container:
            models = controller.discovered_models(profiles)
            for role in ("reflector", "rewriter", "generator"):
                profile = profiles[role]
                with ui.column().classes(f"{CARD_CLASS} min-w-[320px] flex-1 gap-2"):
                    ui.label(role).classes("text-h6")
                    controls = {
                        "enabled": ui.checkbox("Enabled", value=profile.enabled),
                        "host": ui.input("Endpoint host", value=urlparse(profile.base_url).hostname or "").props("readonly").classes(f"{INPUT_CLASS} w-full"),
                        "port": ui.number("Endpoint port", value=urlparse(profile.base_url).port).props("readonly").classes(f"{INPUT_CLASS} w-full"),
                        "base_url": ui.input("Base URL", value=profile.base_url).classes(f"{INPUT_CLASS} w-full"),
                        "model": ui.select(
                            models or [profile.model],
                            label="Model identifier",
                            value=profile.model,
                            with_input=True,
                            new_value_mode="add-unique",
                        ).classes(f"{INPUT_CLASS} w-full"),
                        "timeout": ui.number("Request timeout", value=profile.timeout_seconds, min=1),
                        "context": ui.number("Context size", value=profile.context_size, min=1),
                        "temperature": ui.number("Temperature", value=profile.temperature, min=0, max=2, step=0.05),
                        "max_tokens": ui.number("Maximum output tokens", value=profile.max_output_tokens, min=1),
                        "server_label": ui.input("Server / computer label", value=profile.server_label),
                        "server_profile": ui.input("Launcher server profile", value=profile.server_profile),
                    }
                    ui.button("Test connection", on_click=lambda _, role_name=role: test(role_name)).classes(BUTTON_CLASS)
                    role_controls[role] = controls

    def collect() -> dict[str, LLMProfile]:
        profiles: dict[str, LLMProfile] = {}
        for role, controls in role_controls.items():
            value = lambda key: controls[key].value  # type: ignore[attr-defined]
            profiles[role] = LLMProfile(
                profile=role,
                enabled=bool(value("enabled")),
                base_url=str(value("base_url") or ""),
                model=str(value("model") or ""),
                timeout_seconds=float(value("timeout") or 120),
                context_size=int(value("context")) if value("context") is not None else None,
                temperature=float(value("temperature") or 0),
                max_output_tokens=int(value("max_tokens")) if value("max_tokens") is not None else None,
                server_label=str(value("server_label") or ""),
                server_profile=str(value("server_profile") or ""),
            )
        return profiles

    async def load() -> None:
        try:
            profiles = await asyncio.to_thread(controller.load, Path(str(config_path.value)))
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot load LLM configuration {config_path.value}: {exc}", type="negative")
            return
        render(profiles)

    async def save() -> None:
        try:
            await asyncio.to_thread(controller.save, Path(str(config_path.value)), collect())
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot save LLM configuration {config_path.value}: {exc}", type="negative")
            return
        ui.notify(f"Saved {config_path.value}", type="positive")

    async def test(role: str) -> None:
        try:
            payload = await asyncio.to_thread(controller.test_connection, collect()[role])
        except (OSError, ValueError, RuntimeError) as exc:
            result.value = f"{role}: {exc}"
            result.update()
            return
        import json
        result.value = json.dumps(payload, ensure_ascii=False, indent=2)
        result.update()

    load_button.on_click(load)
    reload_button.on_click(load)
    save_button.on_click(save)
