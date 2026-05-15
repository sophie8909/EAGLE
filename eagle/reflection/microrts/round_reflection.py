"""Round-level reflection operator."""

from __future__ import annotations

import json
from typing import Any

import requests

from eagle.config import EAConfig
from eagle.evolution.component.individual import Individual
from eagle.utils.component_pool import ComponentPool


class RoundReflection:
    """Rewrite one prompt component using feedback from round-level evaluation."""

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

        rewritten_component = component_pool.parse_rewritten_component(
            target,
            rewritten_text,
        )
        new_index = component_pool.add_component(target, rewritten_component)

        child.set_component_index(target, new_index)
        child._sync_component_indices()

        child.reflection_metadata = {
            "reflection_applied": True,
            "target_component": target,
            "new_index": new_index,
            "round_feedback_summary": cls._feedback_summary(child),
        }

        return child

    @classmethod
    def _select_target(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
    ) -> str | None:
        """Select which component should be rewritten from round feedback."""
        feedback = dict(getattr(individual, "last_round_evaluation", {}) or {})
        legality = dict(feedback.get("legality") or {})

        alignment = float(feedback.get("strategy_alignment_score", 0.0) or 0.0)
        parseable = bool(legality.get("parseable", False))
        applicable = float(legality.get("applicable_actions", 0) or 0.0)
        max_actions = max(1.0, float(legality.get("max_actions", 1) or 1.0))
        action_ratio = applicable / max_actions

        format_targets = list(getattr(component_pool, "reflection_format_keys", []) or [])
        alignment_targets = list(getattr(component_pool, "reflection_alignment_keys", []) or [])

        if not format_targets:
            format_targets = list(getattr(component_pool, "evolving_component_keys", []) or [])
        if not alignment_targets:
            alignment_targets = list(getattr(component_pool, "evolving_component_keys", []) or [])

        if not parseable or action_ratio < 0.5:
            preferred_targets = format_targets
        elif alignment < 7.0:
            preferred_targets = alignment_targets
        else:
            preferred_targets = alignment_targets + format_targets

        for target in preferred_targets:
            if target in component_pool.non_evolving_component_keys:
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
        """Build the LLM rewrite instruction for reflection."""
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
- Keep the text valid for the existing JSON schema.
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
        """Rewrite a component through the local Ollama endpoint."""
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
            rewritten_text = str(data.get("response", "")).strip()
            return rewritten_text or current_text
        except Exception:
            return current_text

    @staticmethod
    def _component_text(
        component_pool: ComponentPool,
        individual: Individual,
        target: str,
    ) -> str:
        """Read the selected text for one component."""
        return component_pool.get_component_str(target, individual.get_component_index(target))

    @staticmethod
    def _feedback_summary(individual: Individual) -> dict[str, Any]:
        """Summarize round feedback for reflection metadata."""
        feedback = dict(getattr(individual, "last_round_evaluation", {}) or {})
        legality = dict(feedback.get("legality") or {})

        return {
            "fitness": RoundReflection._fitness_summary_value(getattr(individual, "fitness", None)),
            "parseable": legality.get("parseable"),
            "applicable_actions": legality.get("applicable_actions"),
            "max_actions": legality.get("max_actions"),
            "strategy_alignment_score": feedback.get("strategy_alignment_score"),
        }

    @staticmethod
    def _fitness_summary_value(fitness: Any) -> Any:
        """Return a JSON-safe fitness value without assuming sequence fitness."""
        if isinstance(fitness, dict):
            return dict(fitness)
        if isinstance(fitness, (list, tuple)):
            return list(fitness)
        return fitness
