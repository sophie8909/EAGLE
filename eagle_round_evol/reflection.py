"""Round-level reflection operator."""

from __future__ import annotations

import json
from typing import Any

import requests

from eagle.config import EAConfig
from eagle.utils.component_pool import ComponentPool

from .individual import Individual


class RoundReflection:
    """Rewrite one prompt component using feedback from round-level evaluation."""

    FORMAT_TARGETS = [
        "actions",
        "raw_move_format",
        "game_state_format",
        "field_requirements",
    ]
    STRATEGY_TARGETS = [
        "decision_priority",
        "early_game_plan",
        "mid_game_plan",
        "late_game_plan",
        "tactical_heuristics",
        "anti_stall_rules",
        "combat_evaluation",
        "decision_rule",
        "strategy_identity",
    ]

    @classmethod
    def reflect_individual(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        config: EAConfig,
    ) -> Individual:
        """Create one reflected child by rewriting a single component."""
        child = individual.copy()
        target = cls._select_target(child, component_pool)
        if target is None:
            child.reflection_metadata = {
                "reflection_applied": False,
                "reason": "no_mutable_target",
            }
            return child

        current_text = cls._component_text(component_pool, child, target)
        instruction = cls._build_instruction(
            individual=child,
            component_pool=component_pool,
            target=target,
            current_text=current_text,
        )
        rewritten_text = cls._rewrite_component(
            current_text=current_text,
            instruction=instruction,
            model=str(getattr(config, "round_eval_model", "llama3.1:8b")),
        )
        if not rewritten_text.strip():
            rewritten_text = current_text

        rewritten_component = component_pool.parse_component_str(rewritten_text)
        if target in component_pool.strategy_keys:
            new_index = component_pool.add_strategy_component(target, rewritten_component)
            child.strategy[target] = new_index
        else:
            new_index = component_pool.add_component(target, rewritten_component)
            child.set_component_index(target, new_index)
        if hasattr(child, "_sync_component_indices"):
            child._sync_component_indices()

        child.reflection_metadata = {
            "reflection_applied": True,
            "target_component": target,
            "new_index": new_index,
            "round_feedback_summary": cls._feedback_summary(child),
        }
        return child

    @classmethod
    def _select_target(cls, individual: Individual, component_pool: ComponentPool) -> str | None:
        feedback = dict(getattr(individual, "last_round_evaluation", {}) or {})
        legality = dict(feedback.get("legality") or {})
        alignment = float(feedback.get("strategy_alignment_score", 0.0) or 0.0)
        parseable = bool(legality.get("parseable", False))
        applicable = float(legality.get("applicable_actions", 0) or 0.0)
        max_actions = max(1.0, float(legality.get("max_actions", 1) or 1.0))
        action_ratio = applicable / max_actions

        if not parseable or action_ratio < 0.5:
            preferred_targets = cls.FORMAT_TARGETS
        elif alignment < 7.0:
            preferred_targets = cls.STRATEGY_TARGETS
        else:
            preferred_targets = cls.STRATEGY_TARGETS + cls.FORMAT_TARGETS

        for target in preferred_targets:
            if target in component_pool.FIXED_COMPONENT_KEYS:
                continue
            if target in component_pool.component_keys:
                return target
        return None

    @classmethod
    def _build_instruction(
        cls,
        *,
        individual: Individual,
        component_pool: ComponentPool,
        target: str,
        current_text: str,
    ) -> str:
        feedback = dict(getattr(individual, "last_round_evaluation", {}) or {})
        component_summary = component_pool.describe_individual_components(individual)
        return f"""
You are improving one component of a MicroRTS prompt for round-level LLM action generation.

Rewrite target: {target}

Current component text:
{current_text}

Round feedback:
{json.dumps(feedback, ensure_ascii=False, indent=2)}

Selected component indices:
{json.dumps(component_summary, ensure_ascii=False, indent=2)}

Rewrite rules:
- Rewrite only the target component.
- Keep the text compatible with the existing JSON schema.
- Make the component more likely to produce parseable, legal, state-grounded actions.
- If feedback shows legal actions but poor strategy alignment, make the target more strategically specific.
- If feedback shows parse or legality problems, make the target more concrete and executable.
- Return only the rewritten component text, with no explanation.
""".strip()

    @staticmethod
    def _rewrite_component(
        *,
        current_text: str,
        instruction: str,
        model: str,
    ) -> str:
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": instruction,
                    "stream": False,
                    "options": {"temperature": 0.4},
                },
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()
        except Exception:
            return current_text

    @staticmethod
    def _component_text(component_pool: ComponentPool, individual: Individual, target: str) -> str:
        if target in component_pool.strategy_keys:
            index = int(individual.strategy.get(target, 0))
            return "\n".join(component_pool.get_strategy_component(target, index))
        index = int(individual.static_components.get(target, 0))
        return component_pool.get_component_str(target, index)

    @staticmethod
    def _feedback_summary(individual: Individual) -> dict[str, Any]:
        feedback = dict(getattr(individual, "last_round_evaluation", {}) or {})
        legality = dict(feedback.get("legality") or {})
        return {
            "fitness": list(getattr(individual, "fitness", []) or []),
            "parseable": legality.get("parseable"),
            "applicable_actions": legality.get("applicable_actions"),
            "max_actions": legality.get("max_actions"),
            "strategy_alignment_score": feedback.get("strategy_alignment_score"),
        }
