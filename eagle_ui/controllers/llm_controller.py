"""LLM role configuration and llama.cpp endpoint inspection."""

from __future__ import annotations

import json

import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from eagle.llm_profiles import DEFAULT_ROLE_TOPOLOGY_PATH, LLMProfile, load_role_profiles, save_role_profiles
from eagle.llm_profiles import DEFAULT_MAX_OUTPUT_TOKENS
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
        model_path: Path | None,
        server_path: Path | str | None,
        model_id: str,
        host: str,
        port: int,
        context_size: int,
        roles: tuple[str, ...],
        location_type: str = "local",
        client_host: str | None = None,
        gpu_layers: int | str | None = None,
        gpu_required: bool = False,
        device: str | None = None,
        backend: str | None = None,
        fit_to_vram: bool = False,
        environment_overrides: tuple[tuple[str, str], ...] = (),
    ) -> ServerStatus:
        spec = ServerSpec(
            server_id=server_id,
            model_path=model_path,
            server_path=server_path,
            model_id=model_id,
            host=host,
            port=port,
            context_size=context_size,
            roles=roles,
            location_type=location_type,
            client_host=client_host,
            gpu_layers=gpu_layers,
            gpu_required=gpu_required,
            device=device,
            backend=backend,
            fit_to_vram=fit_to_vram,
            environment_overrides=environment_overrides,
        )
        status = self.server_manager.start(spec)
        self._sync_server_topology(self.server_manager.server_spec(server_id))
        return status

    def _sync_server_topology(self, spec: ServerSpec) -> None:
        """Make the Servers form the authoritative EA endpoint/model source."""
        path = self.repository_root / DEFAULT_ROLE_TOPOLOGY_PATH
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "servers": {}, "roles": {}}
        servers = payload.setdefault("servers", {})
        roles = payload.setdefault("roles", {})
        servers[spec.server_id] = {
            "base_url": spec.endpoint,
            "model_id": spec.model_id,
            "model_display_name": spec.model_id,
            "location_type": spec.location_type,
            "hostname": spec.connection_host,
            "bind_host": spec.bind_host,
            "client_host": spec.connection_host,
            "port": spec.port,
            "roles": list(spec.roles),
            "protocol": "openai-compatible",
            "health_path": "/health",
            "enabled": True,
            "timeout_seconds": 300,
            "context_size": spec.context_size,
            "executable": str(spec.server_path) if spec.server_path is not None else None,
            "model_path": str(spec.model_path) if spec.model_path is not None else None,
            "gpu_layers": spec.gpu_layers,
            "gpu_required": spec.gpu_required,
            "backend": spec.execution_backend,
            "fit_to_vram": spec.fit_to_vram,
            "device": spec.device,
            "additional_args": list(spec.additional_args),
            "environment_overrides": dict(spec.environment_overrides),
            "working_directory": str(spec.workdir) if spec.workdir is not None else None,
        }
        for role in spec.roles:
            roles[role] = {
                "server_id": spec.server_id,
                "enabled": True,
                "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS[role],
            }
        payload["version"] = int(payload.get("version", 1))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def stop_server(self, server_id: str) -> ServerStatus:
        return self.server_manager.stop(server_id)

    def restart_server(self, spec: ServerSpec) -> ServerStatus:
        return self.server_manager.restart(spec)

    def server_statuses(self) -> list[ServerStatus]:
        return self.server_manager.statuses()

    def shutdown(self) -> None:
        self.server_manager.shutdown()

    def clear_server_logs(self, server_id: str) -> None:
        self.server_manager.clear_logs(server_id)

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
