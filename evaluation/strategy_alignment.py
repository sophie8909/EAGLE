"""LLM-based strategy alignment evaluator."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eagle.llm_logging import LLMCallLogger


@dataclass(frozen=True)
class StrategyAlignmentResult:
    score: float
    rationale: str
    raw_response: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_strategy_alignment(
    *,
    strategy_prompt: str,
    generated_java_code: str,
    match_summary: str | None = None,
    backend: str = "mock",
    base_url: str = "http://localhost:8080",
    model: str = "local-model",
    logger: LLMCallLogger | None = None,
    candidate_id: str | None = None,
    generation: int | None = None,
) -> StrategyAlignmentResult:
    """Score whether generated Java behavior matches the evolved prompt."""

    if backend == "mock":
        return mock_strategy_alignment(strategy_prompt, generated_java_code, match_summary)
    if backend not in {"openai", "llama_cpp"}:
        raise ValueError(f"Unknown alignment backend: {backend}")
    return llm_strategy_alignment(
        strategy_prompt=strategy_prompt,
        generated_java_code=generated_java_code,
        match_summary=match_summary,
        base_url=base_url,
        model=model,
        logger=logger,
        candidate_id=candidate_id,
        generation=generation,
    )


def mock_strategy_alignment(
    strategy_prompt: str,
    generated_java_code: str,
    match_summary: str | None = None,
) -> StrategyAlignmentResult:
    prompt_terms = set(re.findall(r"[a-zA-Z]{4,}", strategy_prompt.lower()))
    code_terms = set(re.findall(r"[a-zA-Z]{4,}", generated_java_code.lower()))
    overlap = len(prompt_terms & code_terms)
    base = 0.45 if "RandomBiasedAI" in generated_java_code else 0.2
    score = min(1.0, base + overlap / max(8.0, len(prompt_terms) or 1.0))
    rationale = "Mock alignment rewards compilable Java structure and term overlap with the strategy prompt."
    if match_summary:
        rationale += " Match summary was included."
    return StrategyAlignmentResult(score=round(score, 4), rationale=rationale)


def llm_strategy_alignment(
    *,
    strategy_prompt: str,
    generated_java_code: str,
    match_summary: str | None,
    base_url: str,
    model: str,
    timeout_sec: int = 120,
    logger: LLMCallLogger | None = None,
    candidate_id: str | None = None,
    generation: int | None = None,
) -> StrategyAlignmentResult:
    base_url = base_url.rstrip("/")
    url = f"{base_url}/chat/completions" if base_url.endswith("/v1") else f"{base_url}/v1/chat/completions"
    user_prompt = (
        "Score how well this Java MicroRTS agent matches the strategy prompt. "
        "Return strict JSON with keys score and rationale. score must be a number from 0 to 1.\n\n"
        f"Strategy prompt:\n{strategy_prompt}\n\n"
        f"Generated Java code:\n{generated_java_code}\n\n"
        f"Match summary:\n{match_summary or 'not available'}"
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": 0.0,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            response_text = response.read().decode("utf-8")
        body = json.loads(response_text)
        content = str(body["choices"][0]["message"]["content"])
        parsed = _extract_json_object(content)
        score = max(0.0, min(1.0, float(parsed.get("score", 0.0))))
        rationale = str(parsed.get("rationale", "")).strip() or "No rationale returned."
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        message = f"Strategy alignment backend HTTP {exc.code}: {exc.reason}"
        _log_alignment_call(
            logger, user_prompt, response_text, "error", model, candidate_id, generation, message, url
        )
        raise RuntimeError(message) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        message = f"Strategy alignment backend request failed: {exc}"
        _log_alignment_call(
            logger, user_prompt, locals().get("response_text", ""), "error",
            model, candidate_id, generation, message, url
        )
        raise RuntimeError(message) from exc
    _log_alignment_call(
        logger, user_prompt, content, "success", model, candidate_id, generation, None, url
    )
    return StrategyAlignmentResult(score=score, rationale=rationale, raw_response=content)


def _log_alignment_call(
    logger: LLMCallLogger | None,
    input_text: str,
    response_text: str,
    status: str,
    model: str,
    candidate_id: str | None,
    generation: int | None,
    error: str | None,
    url: str,
) -> None:
    if logger is None:
        return
    logger.write(
        stage="alignment",
        input_text=input_text,
        response_text=response_text,
        status=status,
        backend="openai_compatible",
        model=model,
        candidate_id=candidate_id,
        generation=generation,
        attempt=1,
        error=error,
        metadata={"url": url},
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise RuntimeError("Strategy alignment response did not contain JSON.")
    return json.loads(match.group(0))

