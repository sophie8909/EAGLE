"""Shared LLM, mutation, and operator-controller bootstrap for search/resume."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generation.backend import MockGenerationBackend

from .aos import ReflectionOperatorController, build_reflection_operator_controller
from .config import ExperimentConfig
from .llm import LLMCallLogger, LLMClient, LLMServerError
from .mutation import build_reflection_backend
from .prompts import load_prompt
from .rewrite import PromptRewriteMutation
from .strategy_reflection import MockRoleBackend, StrategyReflectionMutation


@dataclass(frozen=True)
class SearchRuntime:
    client: LLMClient
    generation_backend: Any
    mutations: dict[str, Any]
    operator_controller: ReflectionOperatorController


def build_search_runtime(
    config: ExperimentConfig,
    *,
    mock: bool,
    run_dir: Path,
    candidates_dir: Path,
    controller_state: dict[str, Any] | None = None,
) -> SearchRuntime:
    """Build the dependencies that must be identical for fresh and resumed search."""

    backend_name = "mock" if mock else config.execution_mode
    client = LLMClient(
        config.llm_base_url,
        config.llm_model,
        temperature=config.llm_temperature,
        max_output_tokens=config.llm_max_tokens,
    )
    if not mock:
        preflight_llm_endpoint(client)
    logger = LLMCallLogger(
        run_dir / "llm_logs",
        run_id=run_dir.name,
        timing_path=run_dir / "timing.jsonl",
    )
    generation_backend = (
        MockGenerationBackend(config.agent_template_path)
        if mock else client.generation_backend(logger=logger)
    )
    # The mock and production generator must render the same configured
    # immutable scaffold, including inherited-Java requests.
    generation_backend.agent_template_path = config.agent_template_path
    if mock:
        reflection_backend = build_reflection_backend("mock")
        rewrite_backend = reflection_backend
        strategy_role_backend = MockRoleBackend()
    else:
        reflection_backend = client.prompt_backend(operation="reflection")
        rewrite_backend = client.prompt_backend(operation="rewrite")
        strategy_role_backend = client.prompt_backend(
            operation="match_commentator",
            temperature=config.match_commentator_temperature,
        )
    enabled_roles = {"coach"}
    if config.match_commentator_enabled:
        enabled_roles.add("match_commentator")
    mutations = {
        "strategy": StrategyReflectionMutation(
            strategy_role_backend,
            max_attempts=config.mutation_max_attempts,
            max_prompt_chars=60_000,
            model_identity=None if mock else client.model,
            enabled_roles=enabled_roles,
            selection_seed=config.random_seed,
            sample_budget=config.match_commentator_sample_count,
            timing_logger=logger,
        ),
        "code": PromptRewriteMutation(
            config,
            mutation_type="code",
            reflection_backend=reflection_backend,
            rewrite_backend=rewrite_backend,
            artifact_root=candidates_dir,
            logger=logger,
            backend_name=backend_name,
        ),
    }
    return SearchRuntime(
        client=client,
        generation_backend=generation_backend,
        mutations=mutations,
        operator_controller=build_reflection_operator_controller(config, state=controller_state),
    )


def preflight_llm_endpoint(client: LLMClient) -> None:
    """Verify the one configured endpoint with one small request."""

    api_root = client.base_url.rstrip("/")
    if not api_root.endswith("/v1"):
        api_root += "/v1"
    url = f"{api_root}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps({
            "model": client.model,
            "messages": [{"role": "user", "content": load_prompt("endpoint_preflight")}],
            "temperature": 0,
            "max_tokens": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=min(15.0, client.timeout_seconds)) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload.get("choices"), list):
            raise RuntimeError("response has no choices array")
    except (OSError, urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        raise LLMServerError(f"Configured llama.cpp endpoint preflight failed at {url}: {exc}") from exc
