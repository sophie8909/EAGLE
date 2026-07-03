"""Generation backends for prompt-to-Java source."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from eagle.candidate import Candidate


class GenerationBackend(ABC):
    @abstractmethod
    def generate(self, candidate: Candidate, class_name: str) -> str:
        """Return Java source code for a candidate prompt."""


class GenerationBackendUnavailable(RuntimeError):
    """Raised when the configured generation service cannot be reached."""


class MockGenerationBackend(GenerationBackend):
    """Deterministic backend for tests and local pipeline smoke runs."""

    def generate(self, candidate: Candidate, class_name: str) -> str:
        return render_random_biased_agent(class_name, candidate.id)


class OpenAICompatibleGenerationBackend(GenerationBackend):
    """Small llama.cpp/OpenAI-compatible chat-completions backend."""

    def __init__(self, base_url: str, model: str, timeout_sec: int = 120, max_retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate(self, candidate: Candidate, class_name: str) -> str:
        prompt = (
            "Generate exactly one Java MicroRTS AI class. "
            "Return only Java source code. "
            "The class must use package ai.generated, extend ai.RandomBiasedAI, "
            f"be named {class_name}, and provide a constructor that accepts UnitTypeTable. "
            "Use import ai.RandomBiasedAI; and import rts.units.UnitTypeTable;. "
            "Do not import ai.UnitTypeTable. "
            "Do not add an act() method.\n\n"
            f"Candidate prompt:\n{candidate.prompt}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            self.chat_completions_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise GenerationBackendUnavailable(f"Generation backend request failed: {exc}") from exc
                time.sleep(2**attempt)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Generation backend returned invalid JSON: {exc}") from exc
        return str(body["choices"][0]["message"]["content"])


def generated_class_name(candidate_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", candidate_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"Candidate_{cleaned}"
    return f"GeneratedAgent_{cleaned}"


def render_random_biased_agent(class_name: str, candidate_id: str) -> str:
    return f"""package ai.generated;

import ai.RandomBiasedAI;
import rts.units.UnitTypeTable;

public class {class_name} extends RandomBiasedAI {{
    public static final String CANDIDATE_ID = "{candidate_id}";

    public {class_name}(UnitTypeTable utt) {{
        super(utt);
    }}
}}
"""


def build_generation_backend(name: str, *, base_url: str = "http://localhost:8080", model: str = "local-model") -> GenerationBackend:
    if name == "mock":
        return MockGenerationBackend()
    if name in {"openai", "llama_cpp"}:
        return OpenAICompatibleGenerationBackend(base_url=base_url, model=model)
    raise ValueError(f"Unknown generation backend: {name}")
