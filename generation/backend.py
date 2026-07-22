"""Generation backends for prompt-to-Java source."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from eagle.candidate import Candidate



if TYPE_CHECKING:
    from eagle.llm_logging import LLMCallLogger


class GenerationBackend(ABC):
    @abstractmethod
    def generate(self, candidate: Candidate, class_name: str) -> str:
        """Return Java source code for a candidate prompt."""

class GenerationBackendUnavailable(RuntimeError):
    """Raised when the configured generation service cannot be reached."""


class MockGenerationBackend(GenerationBackend):
    """Deterministic backend for tests and local pipeline smoke runs."""

    def generate(self, candidate: Candidate, class_name: str) -> str:
        from .agent_template import JavaTemplatePaths, load_java_template

        if class_name != "CandidateAgent":
            raise ValueError("Repository template declares only CandidateAgent.")
        return load_java_template(JavaTemplatePaths())

class OpenAICompatibleGenerationBackend(GenerationBackend):
    """Small llama.cpp/OpenAI-compatible chat-completions backend."""

    def __init__(self, base_url: str, model: str, timeout_sec: float = 120, max_retries: int = 2, logger: LLMCallLogger | None = None, llm_profile: str | None = None, temperature: float = 0.2, max_output_tokens: int | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.llm_profile = llm_profile
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.logger = logger
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate(self, candidate: Candidate, class_name: str) -> str:
        prompt = candidate.generation_input(class_name=class_name)
        module_name = "complete_java_agent"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        request = urllib.request.Request(
            self.chat_completions_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for attempt_index in range(self.max_retries + 1):
            attempt = attempt_index + 1
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    response_text = response.read().decode("utf-8")
                body = json.loads(response_text)
                content = str(body["choices"][0]["message"]["content"])
                self._log_call(
                    candidate=candidate,
                    module_name=module_name,
                    prompt=prompt,
                    response_text=content,
                    status="success",
                    attempt=attempt,
                )
                return content
            except urllib.error.HTTPError as exc:
                response_text = exc.read().decode("utf-8", errors="replace")
                message = backend_http_error_message(
                    exc,
                    url=self.chat_completions_url,
                    model=self.model,
                    request_body_size=len(request.data or b""),
                    response_body=response_text,
                )
                self._log_call(
                    candidate=candidate,
                    module_name=module_name,
                    prompt=prompt,
                    response_text=response_text,
                    status="error",
                    attempt=attempt,
                    error=message,
                )
                if exc.code == 400 or attempt_index >= self.max_retries:
                    raise GenerationBackendUnavailable(message) from exc
                time.sleep(2**attempt_index)
            except (urllib.error.URLError, TimeoutError) as exc:
                message = f"Generation backend request failed: {exc}"
                self._log_call(
                    candidate=candidate,
                    module_name=module_name,
                    prompt=prompt,
                    status="error",
                    attempt=attempt,
                    error=message,
                )
                if attempt_index >= self.max_retries:
                    raise GenerationBackendUnavailable(message) from exc
                time.sleep(2**attempt_index)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                message = f"Generation backend returned invalid JSON: {exc}"
                self._log_call(
                    candidate=candidate,
                    module_name=module_name,
                    prompt=prompt,
                    response_text=locals().get("response_text", ""),
                    status="error",
                    attempt=attempt,
                    error=message,
                )
                raise RuntimeError(message) from exc
        raise GenerationBackendUnavailable("Generation backend returned no response.")

    def _log_call(
        self,
        *,
        candidate: Candidate,
        module_name: str,
        prompt: str,
        status: str,
        attempt: int,
        response_text: str = "",
        error: str | None = None,
    ) -> None:
        if self.logger is None:
            return
        self.logger.write(
            stage="generation",
            input_text=prompt,
            response_text=response_text,
            status=status,
            backend="openai_compatible",
            model=self.model,
            candidate_id=candidate.id,
            generation=candidate.generation,
            module_name=module_name,
            attempt=attempt,
            error=error,
            metadata={"class_name": generated_class_name(candidate.id), "url": self.chat_completions_url, "llm_profile": self.llm_profile},
        )


def backend_http_error_message(
    exc: urllib.error.HTTPError,
    *,
    url: str,
    model: str,
    request_body_size: int,
    response_body: str = "",
) -> str:
    response_body = response_body[:300]
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
    logger: LLMCallLogger | None = None,
    llm_profile: str | None = None,
    timeout_sec: float = 120,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> GenerationBackend:
    if name == "mock":
        return MockGenerationBackend()
    if name in {"openai", "llama_cpp"}:
        return OpenAICompatibleGenerationBackend(base_url=base_url, model=model, logger=logger, llm_profile=llm_profile, timeout_sec=timeout_sec, temperature=temperature, max_output_tokens=max_output_tokens)
    raise ValueError(f"Unknown generation backend: {name}")
