"""Single LLM client configuration shared by all logical EAGLE operations."""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass(frozen=True)
class LLMProfile:
    profile: str
    base_url: str
    model: str
    enabled: bool = True
    timeout_seconds: float = 120.0
    context_size: int | None = None
    temperature: float = 0.2
    max_output_tokens: int | None = None
    server_label: str = "llm"
    server_profile: str = "single"

    def to_dict(self):
        return {"profile": self.profile,"enabled":self.enabled,"base_url":self.base_url,"model":self.model,"timeout_seconds":self.timeout_seconds,"context_size":self.context_size,"temperature":self.temperature,"max_output_tokens":self.max_output_tokens}

class EndpointConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LLMClient:
    """One immutable OpenAI-compatible client configuration for the whole EA."""

    base_url: str
    model: str
    timeout_seconds: float = 120.0
    temperature: float = 0.2
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise EndpointConfigError("LLM endpoint must be a valid HTTP(S) URL.")

    @property
    def profile(self) -> LLMProfile:
        return LLMProfile("shared", self.base_url.rstrip("/"), self.model, timeout_seconds=self.timeout_seconds, temperature=self.temperature, max_output_tokens=self.max_output_tokens)

    def generation_backend(self, *, logger=None):
        from generation.backend import build_generation_backend
        return build_generation_backend("openai", base_url=self.base_url, model=self.model, logger=logger, llm_profile="generation", timeout_sec=self.timeout_seconds, temperature=self.temperature, max_output_tokens=self.max_output_tokens)

    def prompt_backend(self, *, operation: str):
        from eagle.mutation import build_reflection_backend
        return build_reflection_backend("openai", base_url=self.base_url, model=self.model, llm_profile=operation, timeout_sec=self.timeout_seconds, temperature=self.temperature, max_output_tokens=self.max_output_tokens)

def build_shared_profile(base_url: str, model: str, **kwargs) -> LLMProfile:
    parsed=urlparse(base_url)
    if parsed.scheme not in {"http","https"} or not parsed.hostname:
        raise EndpointConfigError("LLM endpoint must be a valid HTTP(S) URL.")
    return LLMProfile("shared",base_url.rstrip("/"),model,**kwargs)

def load_role_profiles(path, **kwargs):
    raise EndpointConfigError("Legacy role topology is unsupported. Configure one endpoint in configs/runtime.yaml.")
