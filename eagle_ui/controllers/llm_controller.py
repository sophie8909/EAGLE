"""LLM role configuration and llama.cpp endpoint inspection."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from eagle.llm_profiles import LLMProfile, load_role_profiles, save_role_profiles
from eagle.runtime.server_manager import LLMServerManager, ServerSpec, ServerStatus


class LLMConfigController:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.server_manager = LLMServerManager(repository_root)

    def load(self, path: Path) -> dict[str, LLMProfile]:
        return load_role_profiles(path, require_enabled=False)

    def save(self, path: Path, profiles: dict[str, LLMProfile]) -> None:
        save_role_profiles(path, profiles)

    def discovered_models(self, profiles: dict[str, LLMProfile] | None = None) -> list[str]:
        aliases = {profile.model for profile in (profiles or {}).values() if profile.model}
        for root in (self.repository_root / "experiment_env" / "model", self.repository_root / "models"):
            if root.exists():
                aliases.update(path.stem for path in root.rglob("*.gguf"))
        return sorted(aliases)

    def server_models(self) -> list[Path]:
        return self.server_manager.discover_models()

    def start_server(
        self,
        *,
        server_id: str,
        model_path: Path,
        server_path: Path | str,
        model_id: str,
        host: str,
        port: int,
        context_size: int,
        roles: tuple[str, ...],
    ) -> ServerStatus:
        spec = ServerSpec(
            server_id=server_id,
            model_path=model_path,
            server_path=self.server_manager.resolve_server_path(server_path),
            model_id=model_id,
            host=host,
            port=port,
            context_size=context_size,
            roles=roles,
        )
        return self.server_manager.start(spec)

    def stop_server(self, server_id: str) -> ServerStatus:
        return self.server_manager.stop(server_id)

    def restart_server(self, spec: ServerSpec) -> ServerStatus:
        return self.server_manager.restart(spec)

    def server_statuses(self) -> list[ServerStatus]:
        return self.server_manager.statuses()
    def test_connection(self, profile: LLMProfile) -> dict[str, object]:
        parsed = urlparse(profile.base_url)
        api_root = profile.base_url.rstrip("/")
        server_root = f"{parsed.scheme}://{parsed.netloc}"
        health = self._read_json_or_text(f"{server_root}/health", profile.timeout_seconds)
        models = self._read_json_or_text(f"{api_root}/models" if api_root.endswith("/v1") else f"{api_root}/v1/models", profile.timeout_seconds)
        return {"role": profile.profile, "health": health, "models": models}

    @staticmethod
    def _read_json_or_text(url: str, timeout: float) -> object:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"GET {url} returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"GET {url} failed: {exc}") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
