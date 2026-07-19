"""Logical LLM profiles and the repository endpoint handoff file."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_ENDPOINT_CONFIG_PATH = Path("config/llm_endpoints.toml")
DEFAULT_CONTEXT_SIZE = 32768
DEFAULT_PROFILES = {
    "general": {
        "model": "qwen3.5-9b",
        "port": 8080,
        "bind_host": "127.0.0.1",
    },
    "coder": {
        "model": "qwen2.5-coder-7b",
        "port": 8081,
        "bind_host": "0.0.0.0",
    },
}


@dataclass(frozen=True)
class LLMProfile:
    """Non-sensitive runtime identity used by one EAGLE stage."""

    profile: str
    base_url: str
    model: str

    def to_dict(self) -> dict[str, str]:
        return {"profile": self.profile, "base_url": self.base_url, "model": self.model}


class EndpointConfigError(ValueError):
    """Raised when the repository endpoint handoff is incomplete or unsafe."""


def load_endpoint_profiles(
    path: str | Path,
    *,
    allow_coder_loopback: bool = False,
) -> dict[str, LLMProfile]:
    """Load and validate both logical profiles from one repository config."""

    config_path = Path(path)
    if not config_path.exists():
        raise EndpointConfigError(
            f"LLM endpoint config is missing: {config_path}. Run the profile launcher on both machines first."
        )
    sections = _read_toml_sections(config_path)
    profiles: dict[str, LLMProfile] = {}
    for name in ("general", "coder"):
        values = sections.get(name)
        if not values:
            raise EndpointConfigError(f"LLM endpoint config must contain [{name}].")
        profile = str(values.get("profile", "")).strip()
        base_url = str(values.get("base_url", "")).strip()
        model = str(values.get("model", "")).strip()
        if profile != name:
            raise EndpointConfigError(f"[{name}].profile must be {name!r}.")
        _validate_url(name, base_url, allow_coder_loopback=allow_coder_loopback)
        if not model or _is_placeholder(model):
            raise EndpointConfigError(f"[{name}].model must be a configured model alias.")
        profiles[name] = LLMProfile(profile=name, base_url=base_url, model=model)
    return profiles


def update_endpoint_profile(path: str | Path, profile: LLMProfile) -> None:
    """Atomically update only one profile section and preserve the other."""

    if profile.profile not in {"general", "coder"}:
        raise EndpointConfigError(f"Unknown LLM profile: {profile.profile}")
    _validate_url(profile.profile, profile.base_url, allow_coder_loopback=True)
    if not profile.model.strip() or _is_placeholder(profile.model):
        raise EndpointConfigError("Model alias must be non-empty and must not be a placeholder.")

    config_path = Path(path)
    sections = _read_toml_sections(config_path) if config_path.exists() else {}
    sections[profile.profile] = {
        "profile": profile.profile,
        "base_url": profile.base_url,
        "model": profile.model,
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.",
        suffix=".tmp",
        dir=config_path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_render_toml_sections(sections))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, config_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def validate_coder_for_dual_host(profile: LLMProfile, *, allow_loopback: bool = False) -> None:
    """Apply the two-machine safety rule to the coder client endpoint."""

    if profile.profile != "coder":
        raise EndpointConfigError("Dual-host validation expects the coder profile.")
    _validate_url("coder", profile.base_url, allow_coder_loopback=allow_loopback)


def _validate_url(name: str, value: str, *, allow_coder_loopback: bool) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise EndpointConfigError(f"[{name}].base_url must be a valid HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise EndpointConfigError(f"[{name}].base_url must not contain credentials.")
    if _is_placeholder(parsed.hostname) or "<" in value or ">" in value:
        raise EndpointConfigError(f"[{name}].base_url still contains a placeholder host or port.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise EndpointConfigError(f"[{name}].base_url has an invalid port.") from exc
    if port is None or not 1 <= port <= 65535:
        raise EndpointConfigError(f"[{name}].base_url must include a valid port.")
    if name == "general" and parsed.hostname == "0.0.0.0":
        raise EndpointConfigError("[general].base_url must not use the all-interface bind address 0.0.0.0.")
    if name == "coder" and parsed.hostname in {"127.0.0.1", "localhost", "::1"} and not allow_coder_loopback:
        raise EndpointConfigError(
            "[coder].base_url uses loopback; set allow_coder_loopback explicitly for single-machine testing."
        )


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return not lowered or lowered in {"general-model", "coder-model", "local-model", "<machine-a-private-ip>"}


def _read_toml_sections(path: Path) -> dict[str, dict[str, object]]:
    """Read the small, flat TOML shape used by endpoint handoff files."""

    sections: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section_name = line[1:-1].strip()
            if not section_name:
                raise EndpointConfigError(f"Empty TOML section at line {line_number}.")
            current = sections.setdefault(section_name, {})
            continue
        if current is None or "=" not in line:
            raise EndpointConfigError(f"Unsupported endpoint TOML at line {line_number}.")
        key, raw_value = (item.strip() for item in line.split("=", 1))
        if not key:
            raise EndpointConfigError(f"Empty endpoint key at line {line_number}.")
        try:
            current[key] = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise EndpointConfigError(f"Endpoint value at line {line_number} must be a quoted string or number.") from exc
    return sections


def _render_toml_sections(sections: dict[str, dict[str, object]]) -> str:
    lines: list[str] = []
    for section_name in sorted(sections):
        values = sections[section_name]
        lines.append(f"[{section_name}]")
        for key in ("profile", "base_url", "model"):
            if key in values:
                lines.append(f"{key} = {json.dumps(values[key], ensure_ascii=False)}")
        for key, value in values.items():
            if key not in {"profile", "base_url", "model"}:
                lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)
