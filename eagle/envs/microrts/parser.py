"""Log parsing helpers exposed through the MicroRTS adapter layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...utils.log_parse import (
    collect_recent_dynamic_prompts,
    parse_dynamic_prompt_state,
    parse_log,
    parse_log_file,
    sample_recent_dynamic_prompt,
    sample_recent_dynamic_prompts,
)


def parse_game_log(log_text: str, target_agent: str = "EAGLE") -> dict[str, Any]:
    """Parse one complete MicroRTS runtime log."""
    return parse_log(log_text, target_agent=target_agent)


__all__ = [
    "collect_recent_dynamic_prompts",
    "parse_dynamic_prompt_state",
    "parse_game_log",
    "parse_log_file",
    "sample_recent_dynamic_prompt",
    "sample_recent_dynamic_prompts",
]
