"""Generation backends for prompt-to-Java source."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from eagle.candidate import Candidate
from eagle.llm import LLMServerError, llm_request_progress, read_chat_completion_content, truncate_prompt
from eagle.timing import utc_now



if TYPE_CHECKING:
    from eagle.llm import LLMCallLogger


class GenerationBackend(ABC):
    @abstractmethod
    def generate(self, candidate: Candidate, class_name: str) -> str:
        """Return Java source code for a candidate prompt."""

    def authoritative_request(self, candidate: Candidate, class_name: str) -> str:
        """Render the exact immutable request used by bounded decoder attempts."""

        return self.prepare_request(candidate.generation_input(
            class_name=class_name,
            agent_template_path=getattr(self, "agent_template_path", None),
        ))

    def prepare_request(self, request_text: str) -> str:
        """Apply backend request bounds before an attempt persists its prompt."""

        return request_text

    def generate_from_request(
        self,
        candidate: Candidate,
        class_name: str,
        request_text: str,
    ) -> str:
        """Generate from a pre-rendered request.

        Custom/test backends that do not consume prompts retain the legacy
        ``generate`` contract. Production prompt backends override this method
        so each attempt consumes the exact request persisted for that attempt.
        """

        return self.generate(candidate, class_name)

    def set_generation_attempt_context(self, attempt: int, attempt_id: str) -> None:
        """Attach outer decoder-attempt identity to transport logging."""

    def set_generation_request_kind(self, request_kind: str) -> None:
        """Identify base generation versus compile-guided decoder repair."""

class MockGenerationBackend(GenerationBackend):
    """Deterministic backend for tests and local pipeline smoke runs."""

    def __init__(self, agent_template_path: Path | None = None) -> None:
        self.agent_template_path = agent_template_path

    def generate(self, candidate: Candidate, class_name: str) -> str:
        from .agent_template import JavaTemplatePaths, load_java_template

        if class_name != "CandidateAgent":
            raise ValueError("Repository template declares only CandidateAgent.")
        return load_java_template(
            JavaTemplatePaths()
            if self.agent_template_path is None
            else JavaTemplatePaths(self.agent_template_path)
        )


class InitialJavaSeedBackend(GenerationBackend):
    """Return the checked-in generation-zero phenotype without an LLM call."""

    operation = "initial_java_seed"
    model = None

    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path

    def generate(self, candidate: Candidate, class_name: str) -> str:
        if candidate.generation != 0:
            raise ValueError("The initial Java seed backend is generation-zero only.")
        if class_name != "CandidateAgent":
            raise ValueError("The initial Java seed declares only CandidateAgent.")
        return self.source_path.read_text(encoding="utf-8")

class OpenAICompatibleGenerationBackend(GenerationBackend):
    """Small llama.cpp/OpenAI-compatible chat-completions backend."""

    def __init__(self, base_url: str, model: str, timeout_sec: float = 120, max_retries: int = 2, logger: LLMCallLogger | None = None, operation: str | None = None, temperature: float = 0.2, max_output_tokens: int | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.operation = operation
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.logger = logger
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._active_request_started_at: str | None = None
        self._active_request_started_monotonic: float | None = None
        self._generation_attempt = 1
        self._generation_attempt_id: str | None = None
        self._generation_request_kind = "initial_decode"

    def set_generation_attempt_context(self, attempt: int, attempt_id: str) -> None:
        self._generation_attempt = attempt
        self._generation_attempt_id = attempt_id

    def set_generation_request_kind(self, request_kind: str) -> None:
        if request_kind not in {"initial_decode", "initial_decode_retry", "compile_repair"}:
            raise ValueError(f"Unsupported generation request kind: {request_kind}")
        self._generation_request_kind = request_kind

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate(self, candidate: Candidate, class_name: str) -> str:
        return self.generate_from_request(
            candidate,
            class_name,
            self.authoritative_request(candidate, class_name),
        )

    def authoritative_request(self, candidate: Candidate, class_name: str) -> str:
        return self.prepare_request(candidate.generation_input(
            class_name=class_name,
            agent_template_path=getattr(self, "agent_template_path", None),
        ))

    def prepare_request(self, request_text: str) -> str:
        return truncate_prompt(request_text)

    def generate_from_request(
        self,
        candidate: Candidate,
        class_name: str,
        request_text: str,
    ) -> str:
        genotype_before = (
            candidate.strategy_prompt,
            candidate.generation_prompt,
            candidate.inherited_java,
        )
        prompt = request_text
        assert (
            candidate.strategy_prompt,
            candidate.generation_prompt,
            candidate.inherited_java,
        ) == genotype_before
        module_name = (
            "java_compile_repair"
            if self._generation_request_kind == "compile_repair"
            else "complete_java_agent"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "chat_template_kwargs": {"enable_thinking": False},
            "stream": True,
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
            self._active_request_started_at = utc_now()
            self._active_request_started_monotonic = time.monotonic()
            try:
                with llm_request_progress(
                    stage="generation",
                    endpoint=self.chat_completions_url,
                    model=self.model,
                    candidate_id=candidate.id,
                ):
                    with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                        content = read_chat_completion_content(response)
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
                raise LLMServerError(f"llm server error: {message}") from exc
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
                raise LLMServerError(f"llm server error: {message}") from exc
            except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError) as exc:
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
        raise LLMServerError("llm server error: Generation backend returned no response.")

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
            attempt=self._generation_attempt,
            error=error,
            metadata={
                "class_name": generated_class_name(candidate.id),
                "url": self.chat_completions_url,
                "endpoint": self.base_url,
                "operation": self.operation,
                "operation_type": "mutation" if candidate.operator in {"mutation", "crossover+mutation"} else "crossover" if candidate.operator == "crossover" else None,
                "generation_attempt": self._generation_attempt,
                "generation_attempt_id": self._generation_attempt_id,
                "transport_attempt": attempt,
                "generation_request_kind": self._generation_request_kind,
            },
            started_at=self._active_request_started_at,
            finished_at=utc_now(),
            duration_seconds=None if self._active_request_started_monotonic is None else max(0.0, time.monotonic() - self._active_request_started_monotonic),
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
    model: str | None = None,
    logger: LLMCallLogger | None = None,
    operation: str | None = None,
    timeout_sec: float = 120,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> GenerationBackend:
    if name == "mock":
        return MockGenerationBackend()
    if name in {"openai", "openai"}:
        if not model:
            raise ValueError("An explicit model path is required for the OpenAI-compatible backend.")
        return OpenAICompatibleGenerationBackend(base_url=base_url, model=model, logger=logger, operation=operation, timeout_sec=timeout_sec, temperature=temperature, max_output_tokens=max_output_tokens)
    raise ValueError(f"Unknown generation backend: {name}")
