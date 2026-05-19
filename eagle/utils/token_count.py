"""Token counting helpers for prompt-size objectives and GUI display."""

from __future__ import annotations


def estimate_prompt_token_count(prompt: str) -> int:
    """Estimate prompt tokens with a whitespace split when exact tokenization is unavailable."""
    if not prompt:
        return 0
    return len(prompt.split())


def count_prompt_tokens(prompt: str) -> tuple[int, bool]:
    """Return a prompt token count and whether it came from an exact tokenizer."""
    if not prompt:
        return 0, True
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(prompt)), True
    except ImportError:
        return estimate_prompt_token_count(prompt), False
    except (OSError, RuntimeError, ValueError):
        return estimate_prompt_token_count(prompt), False
