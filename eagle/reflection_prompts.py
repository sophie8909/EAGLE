"""Mutation-specific reflection prompt formatting and deterministic budgets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .candidate import Candidate
from .prompts import render_prompt
from .reflection_context import ReflectionContext, coerce_structured_context


REFLECTION_PROMPT_SCHEMA_VERSION = "reflection-prompt-v1"
STRATEGY_BUDGETS = {
    "current_strategy_prompt": 12_000,
    "aggregate_game_performance": 4_000,
    "parent_comparison": 2_000,
    "mutation_targets": 4_000,
    "opponent_commentaries": 18_000,
    "behaviors_to_preserve": 3_000,
}
CODE_BUDGETS = {
    "candidate_prompts": 8_000,
    "generated_code": 16_000,
    "code_diagnostics": 9_000,
    "gameplay_note": 1_500,
    "evolution": 2_000,
    "previous_reflection": 2_400,
}


@dataclass(frozen=True)
class ReflectionPrompt:
    text: str
    metadata: dict[str, object]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bounded_text(value: object, budget: int, *, section: str, truncated: list[str]) -> str:
    text = str(value or "")
    if len(text) <= budget:
        return text
    truncated.append(section)
    return text[:budget] + f"\n[section {section} bounded; omitted={len(text) - budget} chars]"


def _bounded_code(source: str, budget: int, diagnostics: dict[str, object], truncated: list[str]) -> str:
    if len(source) <= budget:
        return source
    lines = source.splitlines()
    line_numbers: list[int] = []
    for value in diagnostics.get("compile_errors", ()) or ():
        match = re.search(r":(\d+)(?::\d+)?", str(value))
        if match:
            line_numbers.append(int(match.group(1)))
    if line_numbers:
        center = max(1, min(len(lines), line_numbers[0]))
        radius = max(4, budget // 120)
        start = max(0, center - radius - 1)
        end = min(len(lines), start + radius * 2)
        snippet = "\n".join(lines[start:end])
        if len(snippet) <= budget:
            truncated.append("generated_code")
            return f"// lines {start + 1}-{end} around compiler diagnostic\n{snippet}"
    marker = "\n// generated code middle omitted\n"
    side_budget = max(1, (budget - len(marker)) // 2)
    head = "\n".join(lines[: max(1, side_budget // 80)])
    tail = "\n".join(lines[-max(1, side_budget // 80):])
    truncated.append("generated_code")
    return (head + marker + tail)[:budget]


def _metadata(section_values: dict[str, str], omitted: list[str], truncated: list[str], text: str) -> dict[str, object]:
    return {
        "estimated_prompt_size": len(text),
        "section_sizes": {key: len(value) for key, value in section_values.items()},
        "omitted_sections": list(dict.fromkeys(omitted)),
        "truncated_sections": list(dict.fromkeys(truncated)),
        "context_schema_version": REFLECTION_PROMPT_SCHEMA_VERSION,
    }


def build_strategy_reflection_prompt_bundle(candidate: Candidate, context: ReflectionContext) -> ReflectionPrompt:
    context = coerce_structured_context(context, candidate)
    truncated: list[str] = []
    omitted: list[str] = []
    aggregation = context.commentary_aggregation or {}
    objective = context.objectives.to_dict() | {
        "commented_match_count": aggregation.get("commented_match_count", 0),
        "failed_commentary_count": aggregation.get("failed_commentary_count", 0),
    }
    parent = context.parent_comparison or {"available": False, "reason": "No equivalent parent matches were supplied."}
    targets = aggregation.get("priority_strategy_changes") or []
    opponents = aggregation.get("opponent_summaries") or [item.to_dict() for item in context.opponents]
    preserve = aggregation.get("behaviors_to_preserve") or []
    sections = {
        "current_strategy_prompt": f"candidate_id: {context.candidate.candidate_id}\n{context.candidate.strategy_prompt}",
        "aggregate_game_performance": _bounded_text(_json(objective), STRATEGY_BUDGETS["aggregate_game_performance"], section="aggregate_game_performance", truncated=truncated),
        "parent_comparison": _bounded_text(parent, STRATEGY_BUDGETS["parent_comparison"], section="parent_comparison", truncated=truncated),
        "mutation_targets": _bounded_text(_json(targets[:8]), STRATEGY_BUDGETS["mutation_targets"], section="mutation_targets", truncated=truncated),
        "opponent_commentaries": _bounded_text(_json(opponents), STRATEGY_BUDGETS["opponent_commentaries"], section="opponent_commentaries", truncated=truncated),
        "behaviors_to_preserve": _bounded_text(_json(preserve), STRATEGY_BUDGETS["behaviors_to_preserve"], section="behaviors_to_preserve", truncated=truncated),
    }
    text = render_prompt("strategy_reflection", sections)
    return ReflectionPrompt(text, _metadata(sections, omitted, truncated, text))


def build_code_reflection_prompt_bundle(candidate: Candidate, context: ReflectionContext) -> ReflectionPrompt:
    context = coerce_structured_context(context, candidate)
    truncated: list[str] = []
    omitted: list[str] = []
    diagnostics = context.code_diagnostics.to_dict()
    candidate_prompts = _json({
        "candidate_id": context.candidate.candidate_id,
        "strategy_prompt": context.candidate.strategy_prompt,
        "code_generation_prompt": context.candidate.code_generation_prompt,
    })
    # Candidate prompts are highest priority and are never truncated.
    generated_code = _bounded_code(context.candidate.generated_code, CODE_BUDGETS["generated_code"], diagnostics, truncated)
    code_diagnostics = _bounded_text(_json(diagnostics), CODE_BUDGETS["code_diagnostics"], section="code_diagnostics", truncated=truncated)
    game_performance = context.objectives.game_performance
    game_note = "(omitted: code reflection is driven by code diagnostics)"
    if context.code_diagnostics.runtime_failure or (
        context.code_diagnostics.compile_success is True and game_performance is not None
    ):
        weakest = min(context.opponents, key=lambda item: item.raw_score if item.raw_score is not None else float("inf"), default=None)
        game_note = _json({
            "game_performance": game_performance,
            "runtime_failure": context.code_diagnostics.runtime_failure,
            "weakest_opponent": None if weakest is None else {"name": weakest.opponent_name, "score": weakest.raw_score},
        })
    else:
        omitted.append("gameplay_note")
    evolution = _json(context.evolution.to_dict())
    previous = context.previous_reflection or "(none)"
    if previous == "(none)":
        omitted.append("previous_reflection")
    sections = {
        "candidate_prompts": candidate_prompts,
        "generated_code": generated_code,
        "code_diagnostics": code_diagnostics,
        "gameplay_note": _bounded_text(game_note, CODE_BUDGETS["gameplay_note"], section="gameplay_note", truncated=truncated),
        "evolution": _bounded_text(evolution, CODE_BUDGETS["evolution"], section="evolution", truncated=truncated),
        "previous_reflection": _bounded_text(previous, CODE_BUDGETS["previous_reflection"], section="previous_reflection", truncated=truncated),
    }
    text = render_prompt("code_reflection", sections)
    return ReflectionPrompt(text, _metadata(sections, omitted, truncated, text))


def build_strategy_reflection_prompt(candidate: Candidate, context: ReflectionContext) -> str:
    return build_strategy_reflection_prompt_bundle(candidate, context).text


def build_code_reflection_prompt(candidate: Candidate, context: ReflectionContext) -> str:
    return build_code_reflection_prompt_bundle(candidate, context).text
