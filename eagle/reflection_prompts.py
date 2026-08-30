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
    "policy_prompt": 8_000,
    "generated_java": 24_000,
    "structural_evidence": 9_000,
}
BALANCE_BUDGETS = {"win_loss_table": 18_000}


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
    all_diagnostics = context.code_diagnostics.to_dict()
    diagnostics = {
        key: all_diagnostics.get(key)
        for key in (
            "generation_failure",
            "validation_failure",
            "compile_success",
            "compile_errors",
            "compile_warnings",
            "missing_functions",
            "invalid_functions",
        )
        if all_diagnostics.get(key) not in (None, (), [], {}, "")
    }
    if (
        candidate.inherited_java
        and context.candidate.generated_code != candidate.inherited_java
    ):
        # A failed Java parent passes through its earlier inherited component;
        # diagnostics from the failed attempted phenotype do not describe that
        # fallback source and must not be presented as if they did.
        diagnostics = {}
    # In inherited-genotype mode the child may have independently selected
    # policy, generation prompt, and Java. Review the exact child inputs;
    # diagnostics come from the selected Java parent context.
    policy_prompt = (
        candidate.strategy_prompt
        if candidate.inherited_java
        else context.candidate.strategy_prompt
    )
    generated_code = _bounded_code(
        candidate.inherited_java or context.candidate.generated_code,
        CODE_BUDGETS["generated_java"],
        diagnostics,
        truncated,
    )
    structural_evidence = _bounded_text(
        _json(diagnostics),
        CODE_BUDGETS["structural_evidence"],
        section="structural_evidence",
        truncated=truncated,
    )
    sections = {
        "policy_prompt": policy_prompt,
        "generated_java": generated_code,
        "structural_evidence": structural_evidence,
    }
    text = render_prompt("code_reflection", sections)
    return ReflectionPrompt(text, _metadata(sections, omitted, truncated, text))


def build_balance_reflection_prompt_bundle(candidate: Candidate, context: ReflectionContext) -> ReflectionPrompt:
    """Render balance-only evidence without exposing Java, prompts, or raw traces."""

    context = coerce_structured_context(context, candidate)
    truncated: list[str] = []
    table: list[dict[str, object]] = []
    for opponent in context.opponents:
        for map_result in opponent.map_results:
            table.append({
                "opponent": opponent.opponent_id,
                "map": map_result.map_name,
                "p0": _win_loss_draw(map_result.p0_result),
                "p1": _win_loss_draw(map_result.p1_result),
                "total": {
                    "wins": map_result.wins,
                    "losses": map_result.losses,
                    "draws": map_result.draws,
                    "games": map_result.games,
                },
            })
    sections = {
        "win_loss_table": _bounded_text(
            _json(table),
            BALANCE_BUDGETS["win_loss_table"],
            section="win_loss_table",
            truncated=truncated,
        ),
    }
    text = render_prompt("balance_reflection", sections)
    return ReflectionPrompt(text, _metadata(sections, [], truncated, text))


def _win_loss_draw(value: dict[str, object]) -> dict[str, int]:
    return {
        key: int(value.get(key) or 0)
        for key in ("wins", "losses", "draws", "games")
    }


def build_strategy_reflection_prompt(candidate: Candidate, context: ReflectionContext) -> str:
    return build_strategy_reflection_prompt_bundle(candidate, context).text


def build_code_reflection_prompt(candidate: Candidate, context: ReflectionContext) -> str:
    return build_code_reflection_prompt_bundle(candidate, context).text


def build_balance_reflection_prompt(candidate: Candidate, context: ReflectionContext) -> str:
    return build_balance_reflection_prompt_bundle(candidate, context).text
