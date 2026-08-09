"""Role-only settings layered over the one shared LLM client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CANONICAL_LLM_ROLES = ("match_commentator", "manager", "coach", "generator")


@dataclass(frozen=True)
class RoleSettings:
    enabled: bool = True
    temperature: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "temperature": self.temperature}


def parse_role_settings(value: object) -> dict[str, RoleSettings]:
    """Parse only role-local settings; endpoint/model keys are rejected."""

    raw = {} if value is None else value
    if not isinstance(raw, dict):
        raise ValueError("llm.roles must be a mapping")
    result: dict[str, RoleSettings] = {}
    forbidden = {"model", "model_name", "endpoint", "base_url", "port", "context_size", "server"}
    for role, payload in raw.items():
        if role not in CANONICAL_LLM_ROLES:
            raise ValueError(f"Unknown LLM role: {role}")
        if not isinstance(payload, dict):
            raise ValueError(f"llm.roles.{role} must be a mapping")
        duplicate = sorted(forbidden.intersection(payload))
        if duplicate:
            raise ValueError(f"llm.roles.{role} cannot define shared settings: {', '.join(duplicate)}")
        temperature = payload.get("temperature")
        result[str(role)] = RoleSettings(
            enabled=bool(payload.get("enabled", True)),
            temperature=None if temperature is None else float(temperature),
        )
    return {role: result.get(role, RoleSettings()) for role in CANONICAL_LLM_ROLES}
