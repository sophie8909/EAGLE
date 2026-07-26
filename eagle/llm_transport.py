"""OpenAI-compatible response decoding shared by EAGLE LLM stages."""

from __future__ import annotations

import json
from typing import BinaryIO


# llama.cpp context includes both prompt and generated output.  Keeping the
# request below this bound leaves room for the configured response budget on a
# 32K context server while still retaining substantially more than the normal
# EAGLE prompts.  Large raw telemetry remains persisted in run artifacts.
DEFAULT_MAX_PROMPT_CHARS = 60_000


def truncate_prompt(prompt: str, *, max_chars: int = DEFAULT_MAX_PROMPT_CHARS) -> str:
    """Hard-limit an LLM prompt while preserving instructions and latest evidence."""
    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    if len(prompt) <= max_chars:
        return prompt
    marker = (
        "\n\n[ EAGLE: prompt truncated to fit the server context; "
        "raw evidence remains in artifacts ]\n\n"
    )
    available = max_chars - len(marker)
    head = available * 2 // 3
    tail = available - head
    return prompt[:head] + marker + prompt[-tail:]


def read_chat_completion_content(response: BinaryIO) -> str:
    """Read either an SSE streaming response or one JSON completion response."""

    try:
        lines = iter(response)
    except TypeError:
        return _content_from_payload(json.loads(response.read().decode("utf-8")))

    content: list[str] = []
    buffered: list[bytes] = []
    saw_sse = False
    for raw_line in lines:
        buffered.append(raw_line)
        line = raw_line.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        saw_sse = True
        data = line[5:].strip()
        if data == "[DONE]":
            break
        payload = json.loads(data)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            continue
        message = choice.get("delta") or choice.get("message") or {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content.append(message["content"])
    if saw_sse:
        return "".join(content)
    return _content_from_payload(json.loads(b"".join(buffered).decode("utf-8")))


def _content_from_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        raise TypeError("chat completion response must be an object")
    choices = payload["choices"]
    if not isinstance(choices, list) or not choices:
        raise KeyError("choices")
    message = choices[0]["message"]
    return str(message["content"])
