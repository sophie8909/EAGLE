"""Render surrogate prompt/spec data into the generated Java agent source."""

from __future__ import annotations

import json
import re
from pathlib import Path


SPEC_START_MARKER = "    // SURROGATE_SPEC_START"
SPEC_END_MARKER = "    // SURROGATE_SPEC_END"
PROMPT_START_MARKER = "    // SURROGATE_PROMPT_START"
PROMPT_END_MARKER = "    // SURROGATE_PROMPT_END"


def _java_string_literal(text: str) -> str:
    """Encode one Python string as a Java string literal."""
    return json.dumps(text)


def _render_prompt_array(prompt: str) -> str:
    """Render the embedded prompt lines block inserted into the Java agent."""
    prompt_lines = [line.rstrip() for line in prompt.splitlines() if line.strip()]

    rendered_lines = [PROMPT_START_MARKER, "    private static final String[] EMBEDDED_PROMPT_LINES = {"]
    for index, line in enumerate(prompt_lines):
        suffix = "," if index < len(prompt_lines) - 1 else ""
        rendered_lines.append(f"        {_java_string_literal(line)}{suffix}")
    rendered_lines.append("    };")
    rendered_lines.append(PROMPT_END_MARKER)
    return "\n".join(rendered_lines)


def _java_bool(value: bool) -> str:
    """Convert a Python boolean into Java's lowercase literal form."""
    return "true" if value else "false"


def _render_spec_block(spec: dict) -> str:
    """Render one surrogate strategy spec into the Java constant block."""
    production_priority = list(spec.get("production_priority", []) or [])
    rendered_lines = [
        SPEC_START_MARKER,
        f"    private static final boolean INJECTED_STRATEGY_ENABLED = {_java_bool(bool(spec.get('enabled', False)))};",
        f"    private static final int WORKER_TARGET_BEFORE_BARRACKS = {int(spec.get('worker_target_before_barracks', 0))};",
        f"    private static final int WORKER_TARGET_AFTER_BARRACKS = {int(spec.get('worker_target_after_barracks', 0))};",
        f"    private static final int HARVESTER_TARGET = {int(spec.get('harvester_target', 0))};",
        f"    private static final int DESIRED_BARRACKS = {int(spec.get('desired_barracks', 0))};",
        f"    private static final boolean WORKER_HARASS_ENABLED = {_java_bool(bool(spec.get('worker_harass_enabled', False)))};",
        f"    private static final boolean ATTACK_WORKERS_FIRST = {_java_bool(bool(spec.get('attack_workers_first', False)))};",
        f"    private static final boolean ATTACK_STRUCTURES_FIRST = {_java_bool(bool(spec.get('attack_structures_first', False)))};",
        f"    private static final boolean PROTECT_BARRACKS = {_java_bool(bool(spec.get('protect_barracks', False)))};",
        f"    private static final int MIN_LIGHTS = {int(spec.get('min_lights', 0))};",
        f"    private static final int MIN_RANGED = {int(spec.get('min_ranged', 0))};",
        f"    private static final int MIN_HEAVIES = {int(spec.get('min_heavies', 0))};",
        "    private static final String[] PRODUCTION_PRIORITY = {",
    ]
    for index, name in enumerate(production_priority):
        suffix = "," if index < len(production_priority) - 1 else ""
        rendered_lines.append(f"        {_java_string_literal(str(name))}{suffix}")
    rendered_lines.append("    };")
    rendered_lines.append(SPEC_END_MARKER)
    return "\n".join(rendered_lines)


def render_surrogate_agent(repo_root: Path, prompt: str, spec: dict) -> Path:
    """Inject the prompt and surrogate spec into `EAGLESurrogate.java`."""
    java_path = repo_root / "src" / "ai" / "abstraction" / "EAGLESurrogate.java"
    content = java_path.read_text(encoding="utf-8")
    spec_pattern = re.compile(
        rf"{re.escape(SPEC_START_MARKER)}.*?{re.escape(SPEC_END_MARKER)}",
        re.DOTALL,
    )
    prompt_pattern = re.compile(
        rf"{re.escape(PROMPT_START_MARKER)}.*?{re.escape(PROMPT_END_MARKER)}",
        re.DOTALL,
    )
    spec_match = spec_pattern.search(content)
    prompt_match = prompt_pattern.search(content)
    if spec_match is None or prompt_match is None:
        missing_blocks: list[str] = []
        if spec_match is None:
            missing_blocks.append("spec")
        if prompt_match is None:
            missing_blocks.append("prompt")
        missing_text = ", ".join(missing_blocks)
        raise ValueError(f"Failed to locate surrogate {missing_text} markers in {java_path}")

    updated = spec_pattern.sub(_render_spec_block(spec), content, count=1)
    updated = prompt_pattern.sub(_render_prompt_array(prompt), updated, count=1)
    java_path.write_text(updated, encoding="utf-8")
    return java_path
