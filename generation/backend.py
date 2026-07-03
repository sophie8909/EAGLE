"""Generation backends for prompt-to-Java source."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from eagle.candidate import Candidate


class GenerationBackend(ABC):
    @abstractmethod
    def generate(self, candidate: Candidate, class_name: str) -> str:
        """Return Java source code for a candidate prompt."""


class MockGenerationBackend(GenerationBackend):
    """Deterministic backend for tests and local pipeline smoke runs."""

    def generate(self, candidate: Candidate, class_name: str) -> str:
        return render_random_biased_agent(class_name, candidate.id)


class OpenAICompatibleGenerationBackend(GenerationBackend):
    """Small llama.cpp/OpenAI-compatible chat-completions backend."""

    def __init__(self, base_url: str, model: str, timeout_sec: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec

    def generate(self, candidate: Candidate, class_name: str) -> str:
        prompt = (
            "Generate exactly one Java MicroRTS AI class. "
            "Return only Java source code. "
            "The class must use package ai.generated, extend ai.RandomBiasedAI, "
            f"be named {class_name}, and provide a constructor that accepts UnitTypeTable.\n\n"
            f"Candidate prompt:\n{candidate.prompt}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Generation backend request failed: {exc}") from exc
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
