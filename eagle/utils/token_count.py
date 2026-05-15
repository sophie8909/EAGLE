"""Token counting helpers for prompt-size objectives and GUI display."""

from __future__ import annotations

import re


def count_prompt_tokens(prompt: str) -> tuple[int, bool]:
    """Return a prompt token count and whether it came from an exact tokenizer."""
    if not prompt:
        return 0, True
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(prompt)), True
    except Exception:
        return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", prompt)), False
