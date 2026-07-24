"""Canonical JSON role topology for the EAGLE LLM stages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_ROLE_TOPOLOGY_PATH = Path("experiment_env/config/llm_topology.json")
REQUIRED_LLM_ROLES = ("reflector", "rewriter", "generator")


@dataclass(frozen=True)
class LLMProfile:
    """Runtime endpoint and model identity for one semantic EAGLE stage."""

    profile: str
    base_url: str
    model: str
    enabled: bool = True
    timeout_seconds: float = 120.0
    context_size: int | None = None
    temperature: float = 0.2
    max_output_tokens: int | None = None
    server_label: str = ""
    server_profile: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "enabled": self.enabled,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "context_size": self.context_size,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "server_label": self.server_label,
            "server_profile": self.server_profile,
        }


class EndpointConfigError(ValueError):
    """Raised when the canonical role topology is incomplete or unsafe."""


def load_role_profiles(
    path: str | Path,
    *,
    required_roles: tuple[str, ...] = REQUIRED_LLM_ROLES,
    require_enabled: bool = True,
) -> dict[str, LLMProfile]:
    """Load the required semantic roles from one JSON topology file."""

    topology_path = Path(path)
    if not topology_path.exists():
        raise EndpointConfigError(f"LLM role topology is missing: {topology_path}")
    try:
        payload = json.loads(topology_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EndpointConfigError(f"LLM role topology is invalid JSON: {topology_path}") from exc
    servers = payload.get("servers")
    roles = payload.get("roles")
    if not isinstance(servers, dict) or not isinstance(roles, dict):
        raise EndpointConfigError("LLM role topology must contain object-valued 'servers' and 'roles'.")

    profiles: dict[str, LLMProfile] = {}
    for role in required_roles:
        if role not in REQUIRED_LLM_ROLES:
            raise EndpointConfigError(f"Unknown LLM role requested: {role}")
        role_entry = roles.get(role)
        if not isinstance(role_entry, dict):
            raise EndpointConfigError(f"LLM role topology has no assignment for required role: {role}")
        server_id = str(role_entry.get("server_id", "")).strip()
        server = servers.get(server_id)
        if not server_id or not isinstance(server, dict):
            raise EndpointConfigError(f"LLM role {role!r} references an unknown server_id: {server_id}")
        base_url = str(server.get("base_url", "")).strip()
        model = str(server.get("model_id") or server.get("model") or "").strip()
        _validate_url(role, base_url)
        if not model:
            raise EndpointConfigError(f"LLM role {role!r} server {server_id!r} must define model_id.")
        enabled = bool(role_entry.get("enabled", server.get("enabled", True)))
        if require_enabled and not enabled:
            raise EndpointConfigError(f"LLM role {role!r} is disabled.")
        profiles[role] = LLMProfile(
            profile=role,
            base_url=base_url,
            model=model,
            enabled=enabled,
            timeout_seconds=float(role_entry.get("timeout_seconds", server.get("timeout_seconds", 120.0))),
            context_size=_optional_int(role_entry.get("context_size", server.get("context_size"))),
            temperature=float(role_entry.get("temperature", server.get("temperature", 0.2))),
            max_output_tokens=_optional_int(role_entry.get("max_output_tokens", server.get("max_output_tokens"))),
            server_label=str(server.get("label") or server.get("model_display_name") or server_id),
            server_profile=server_id,
        )
    return profiles


def save_role_profiles(path: str | Path, profiles: dict[str, LLMProfile]) -> None:
    """Persist semantic role assignments in the canonical JSON topology."""

    missing = sorted(set(REQUIRED_LLM_ROLES) - set(profiles))
    if missing:
        raise EndpointConfigError(f"Missing LLM roles: {', '.join(missing)}")
    topology_path = Path(path)
    if topology_path.exists():
        try:
            payload = json.loads(topology_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EndpointConfigError(f"LLM role topology is invalid JSON: {topology_path}") from exc
    else:
        payload = {"version": 1, "servers": {}, "roles": {}}
    servers = payload.setdefault("servers", {})
    roles = payload.setdefault("roles", {})
    if not isinstance(servers, dict) or not isinstance(roles, dict):
        raise EndpointConfigError("LLM role topology must contain object-valued 'servers' and 'roles'.")

    for role in REQUIRED_LLM_ROLES:
        profile = profiles[role]
        if profile.profile != role:
            raise EndpointConfigError(f"Role profile must be named {role!r}.")
        _validate_url(role, profile.base_url)
        if not profile.model.strip() or profile.timeout_seconds <= 0 or not 0 <= profile.temperature <= 2:
            raise EndpointConfigError(f"{role}: model, timeout, and temperature are invalid.")
        server_id = profile.server_profile or role
        server = servers.setdefault(server_id, {})
        if not isinstance(server, dict):
            raise EndpointConfigError(f"Server entry {server_id!r} must be an object.")
        server.update({
            "base_url": profile.base_url,
            "model_id": profile.model,
            "enabled": profile.enabled,
            "timeout_seconds": profile.timeout_seconds,
            "context_size": profile.context_size,
            "temperature": profile.temperature,
            "max_output_tokens": profile.max_output_tokens,
        })
        if profile.server_label:
            server["label"] = profile.server_label
        role_entry = roles.setdefault(role, {})
        if not isinstance(role_entry, dict):
            role_entry = {}
            roles[role] = role_entry
        role_entry.update({
            "server_id": server_id,
            "enabled": profile.enabled,
            "timeout_seconds": profile.timeout_seconds,
            "context_size": profile.context_size,
            "temperature": profile.temperature,
            "max_output_tokens": profile.max_output_tokens,
        })

    payload["version"] = int(payload.get("version", 1))
    topology_path.parent.mkdir(parents=True, exist_ok=True)
    topology_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _validate_url(role: str, value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise EndpointConfigError(f"[{role}].base_url must be a credential-free HTTP(S) URL.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise EndpointConfigError(f"[{role}].base_url has an invalid port.") from exc
    if port is None or not 1 <= port <= 65535:
        raise EndpointConfigError(f"[{role}].base_url must include a valid port.")