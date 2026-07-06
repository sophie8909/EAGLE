"""Generation backends for prompt-to-Java source."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from eagle.candidate import Candidate

from .agent_template import render_blank_strategy_agent


class GenerationBackend(ABC):
    @abstractmethod
    def generate(self, candidate: Candidate, class_name: str) -> str:
        """Return Java source code for a candidate prompt."""


class GenerationBackendUnavailable(RuntimeError):
    """Raised when the configured generation service cannot be reached."""


class MockGenerationBackend(GenerationBackend):
    """Deterministic backend for tests and local pipeline smoke runs."""

    def generate(self, candidate: Candidate, class_name: str) -> str:
        return render_blank_strategy_agent(class_name)


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
            "Generate exactly one complete compilable Java MicroRTS AI class. "
            "Return raw Java source only. No markdown, no explanation, no code fences. "
            f"The class must use package ai.generated and must be named {class_name}. "
            "Use the supplied MicroRTS operation template when present. "
            "Replace any CLASS_NAME placeholder with the requested class name. "
            "Keep the complete operation helper methods, fill only deterministic strategy logic, "
            "never replace helper methods with comments or ellipses, "
            "only call helper methods that exist in the template: commandMove, commandHarvest, "
            "commandTrain, commandBuild, commandAttack, commandIdle, isIdleAlly, nearestUnit, "
            "nearestEnemy, nearestResource, ownBase, applyAutoDefense, "
            "do not invent helper methods and never call nearestIdleAlly, "
            "when iterating game units, copy them first with new ArrayList<>(gs.getUnits()) "
            "or new ArrayList<>(pgs.getUnits()), "
            "do not modify collections returned directly by GameState or PhysicalGameState while iterating, "
            "do not redeclare local variables in the same method, "
            "reuse existing variables or choose unique names, "
            "do not assign UnitType values to Unit variables, "
            "prefer the simple MicroRTS API usage shown in the template, "
            "and do not call any network, file, subprocess, environment, or LLM API at runtime.\n\n"
            f"Requested class name: {class_name}\n\n"
            f"Candidate prompt:\n{candidate.strategy_prompt}"
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
        body = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                message = backend_http_error_message(
                    exc,
                    url=self.chat_completions_url,
                    model=self.model,
                    request_body_size=len(request.data or b""),
                )
                if exc.code == 400 or attempt >= self.max_retries:
                    raise GenerationBackendUnavailable(message) from exc
                time.sleep(2**attempt)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise GenerationBackendUnavailable(f"Generation backend request failed: {exc}") from exc
                time.sleep(2**attempt)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Generation backend returned invalid JSON: {exc}") from exc
        if body is None:
            raise GenerationBackendUnavailable("Generation backend returned no response.")
        return str(body["choices"][0]["message"]["content"])


def backend_http_error_message(
    exc: urllib.error.HTTPError,
    *,
    url: str,
    model: str,
    request_body_size: int,
) -> str:
    response_body = exc.read().decode("utf-8", errors="replace")[:300]
    return (
        f"Generation backend HTTP {exc.code}: {exc.reason}. "
        f"url={url} model={model} request_body_size={request_body_size} "
        f"response_body_start={response_body!r}"
    )


def generated_class_name(candidate_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", candidate_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"Candidate_{cleaned}"
    return f"GeneratedAgent_{cleaned}"


def build_generation_backend(
    name: str,
    *,
    base_url: str = "http://localhost:8080",
    model: str = "local-model",
) -> GenerationBackend:
    if name == "mock":
        return MockGenerationBackend()
    if name in {"openai", "llama_cpp"}:
        return OpenAICompatibleGenerationBackend(base_url=base_url, model=model)
    raise ValueError(f"Unknown generation backend: {name}")
