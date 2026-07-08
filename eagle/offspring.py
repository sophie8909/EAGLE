"""Prompt size helpers."""

from __future__ import annotations


def normalize_prompt(prompt: str, *, max_chars: int, max_lines: int) -> str:
    """Clean and cap evolved prompts before sending them to the backend."""

    lines: list[str] = []
    previous_blank = False
    for line in prompt.strip().splitlines():
        if not line.strip():
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line.rstrip())
        previous_blank = False

    while lines and not lines[-1]:
        lines.pop()

    prompt = "\n".join(lines[:max_lines])
    return prompt[:max_chars].rstrip()


def prompt_length(prompt: str) -> dict[str, int]:
    """Return the simple prompt size numbers saved with each candidate."""

    return {
        "chars": len(prompt),
        "lines": len(prompt.splitlines()),
    }
