"""Render the generated eagleJava agent with the same behavior as eaglePolicy."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ...project import PROJECT_ROOT
from ..compiler.eagle_policy_spec import compile_prompt_to_eagle_policy_spec


EAGLE_JAVA_CLASS_NAME = "eagleJava"
EAGLE_POLICY_SOURCE_PATH = (
    PROJECT_ROOT / "third_party" / "microrts" / "src" / "ai" / "abstraction" / "eaglePolicy.java"
)
SPEC_START_MARKER = "    // EAGLE_POLICY_SPEC_START"
SPEC_END_MARKER = "    // EAGLE_POLICY_SPEC_END"
PROMPT_START_MARKER = "    // EAGLE_POLICY_PROMPT_START"
PROMPT_END_MARKER = "    // EAGLE_POLICY_PROMPT_END"


def _java_string_literal(text: str) -> str:
    """Encode one Python string as a Java string literal."""
    return json.dumps(text)


def _java_bool(value: bool) -> str:
    """Convert a Python boolean into Java's lowercase literal form."""
    return "true" if value else "false"


def _render_prompt_array(prompt: str) -> str:
    """Render prompt text into the Java embedded prompt block."""
    prompt_lines = [line.rstrip() for line in prompt.splitlines() if line.strip()]
    rendered_lines = [PROMPT_START_MARKER, "    private static final String[] EMBEDDED_PROMPT_LINES = {"]
    for index, line in enumerate(prompt_lines):
        suffix = "," if index < len(prompt_lines) - 1 else ""
        rendered_lines.append(f"        {_java_string_literal(line)}{suffix}")
    rendered_lines.append("    };")
    rendered_lines.append(PROMPT_END_MARKER)
    return "\n".join(rendered_lines)


def _render_spec_block(spec: dict) -> str:
    """Render an eaglePolicy-compatible strategy spec into Java constants."""
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


def _replace_marked_block(source: str, start_marker: str, end_marker: str, replacement: str) -> str:
    """Replace one marked Java block exactly once."""
    pattern = re.compile(rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL)
    if pattern.search(source) is None:
        raise ValueError(f"Failed to locate Java marker block: {start_marker}")
    return pattern.sub(lambda _: replacement, source, count=1)


def render_eagle_java(prompt: str, spec: dict) -> str:
    """Render `eagleJava.java` from the fixed-policy Java source and spec."""
    source = EAGLE_POLICY_SOURCE_PATH.read_text(encoding="utf-8")
    source = _replace_marked_block(source, SPEC_START_MARKER, SPEC_END_MARKER, _render_spec_block(spec))
    source = _replace_marked_block(source, PROMPT_START_MARKER, PROMPT_END_MARKER, _render_prompt_array(prompt))
    source = source.replace("eaglePolicy", EAGLE_JAVA_CLASS_NAME)
    source = source.replace("EAGLE_POLICY_", "EAGLE_JAVA_")
    return source


def render_eagle_java_from_prompt(prompt: str) -> str:
    """Compile a prompt into the shared policy spec and render `eagleJava.java`."""
    _policy, spec = compile_prompt_to_eagle_policy_spec(prompt)
    return render_eagle_java(prompt, spec)
