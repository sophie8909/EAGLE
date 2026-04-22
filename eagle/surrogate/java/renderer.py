"""Render Java surrogate agents from a constrained template."""

from __future__ import annotations

import re
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "base_agent.java"
CLASS_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _render_rule_block(rule_text: str, fallback_call: str) -> str:
    """Convert one extracted rule into a safe Java block."""
    lines = [line.strip() for line in str(rule_text).splitlines() if line.strip()]
    rendered_lines: list[str] = []
    if not lines:
        rendered_lines.append("        // No extracted rule was available for this slot.")
    else:
        rendered_lines.append("        // Extracted strategy rule:")
        for line in lines:
            sanitized = line.replace("*/", "* /")
            rendered_lines.append(f"        // {sanitized}")
    rendered_lines.append(f"        return {fallback_call};")
    return "\n".join(rendered_lines)


def render_java_agent(strategy: dict, class_name: str) -> str:
    """
    Fill predefined Java template using strategy slots.
    """
    if not CLASS_NAME_PATTERN.match(class_name):
        raise ValueError(f"Invalid Java class name: {class_name}")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{CLASS_NAME}}": class_name,
        "{{STRATEGY_IDENTITY}}": str(strategy.get("strategy_identity", "balanced")).strip().lower() or "balanced",
        "{{WORKER_RULE}}": _render_rule_block(strategy.get("worker_rule", ""), "fallbackWorkerAction(u, gs)"),
        "{{BASE_RULE}}": _render_rule_block(strategy.get("base_rule", ""), "fallbackBaseAction(u, gs)"),
        "{{BARRACKS_RULE}}": _render_rule_block(strategy.get("barracks_rule", ""), "fallbackBarracksAction(u, gs)"),
        "{{COMBAT_RULE}}": _render_rule_block(strategy.get("combat_rule", ""), "fallbackCombatAction(u, gs)"),
        "{{DEFENSE_RULE}}": _render_rule_block(strategy.get("defense_rule", ""), "fallbackDefenseAction(u, gs)"),
    }

    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered
