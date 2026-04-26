"""Reflection-based offspring generation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...envs.microrts.compiler import locate_microrts_root
from ...utils.component_pool import ComponentPool
from ...config import EAConfig
from ...utils.individual import Individual
from .mutation import Mutation


_ACTION_TYPES = ("move", "harvest", "build", "train", "attack")


def _empty_quality_summary() -> dict[str, float | int]:
    """Create a zero-valued instruction-quality summary bucket."""
    return {
        "llm_move_count": 0,
        "applied_success_count": 0,
        "applied_failure_count": 0,
        "duplicate_skipped_count": 0,
        "direct_failure_count": 0,
        "success_rate": 0.0,
        "failure_rate": 0.0,
        "duplicate_rate": 0.0,
    }


class Reflection:
    """Conservative feedback-guided rewrite operator."""

    @classmethod
    def build_compact_reflection_context(
        cls,
        *,
        parsed_log: dict[str, Any] | None,
        match_score: dict[str, Any] | None,
        timeout: bool,
        max_turn_hint: int | None,
    ) -> dict[str, Any]:
        """Convert one parsed real-game log into a compact reflection context."""
        parsed_log = parsed_log or {}
        summary = dict(parsed_log.get("summary") or {})
        segments = list(parsed_log.get("segments") or [])
        move_results = list(parsed_log.get("all_move_results") or [])

        final_turn = cls._infer_final_turn(summary=summary, segments=segments, parsed_log=parsed_log)
        max_turn = max_turn_hint if isinstance(max_turn_hint, int) and max_turn_hint > 0 else final_turn
        global_summary = cls._build_quality_summary(summary)
        phase_summaries = cls._build_phase_summaries(segments, final_turn)
        action_type_stats = cls._build_action_type_stats(move_results)
        outcome = cls._derive_outcome(summary, match_score)
        diagnosis_notes = cls._build_diagnosis_notes(
            outcome=outcome,
            final_turn=final_turn,
            max_turn=max_turn,
            timeout=timeout,
            global_summary=global_summary,
            phase_summaries=phase_summaries,
            action_type_stats=action_type_stats,
        )

        return {
            "outcome": outcome,
            "win_score": cls._match_win_score(match_score),
            "final_turn": final_turn,
            "max_turn": max_turn,
            "ended_by_timeout": bool(timeout),
            "global_instruction_quality": global_summary,
            "phase_instruction_quality": phase_summaries,
            "action_type_stats": action_type_stats,
            "diagnosis_notes": diagnosis_notes,
        }

    @classmethod
    def safe_fallback_context(cls, *, match_score: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a minimal context when no prior real-game data is available."""
        return {
            "outcome": "unknown",
            "win_score": cls._match_win_score(match_score),
            "final_turn": 0,
            "max_turn": 0,
            "ended_by_timeout": False,
            "global_instruction_quality": _empty_quality_summary(),
            "phase_instruction_quality": {
                "early": _empty_quality_summary(),
                "mid": _empty_quality_summary(),
                "late": _empty_quality_summary(),
            },
            "action_type_stats": {
                "intent_counts": {action_type: 0 for action_type in _ACTION_TYPES},
                "executed_counts": {action_type: 0 for action_type in _ACTION_TYPES},
            },
            "diagnosis_notes": ["No prior real-evaluation summary was available."],
            "missing_data": True,
        }

    @classmethod
    def apply_reflection(
        cls,
        parent: Individual,
        component_pool: ComponentPool,
        config: EAConfig,
        reflection_context: dict[str, Any],
    ) -> tuple[Individual, dict[str, Any]]:
        """Rewrite a small set of flattened components using compact feedback."""
        child = parent.copy()
        component_indices = Mutation._ensure_complete_strategy(
            dict(getattr(child, "component_indices", {}) or {}),
            component_pool,
        )
        child.ea_llm_call_time = 0.0

        target_components = cls._select_rewrite_targets(
            component_pool=component_pool,
            config=config,
            reflection_context=reflection_context,
        )
        if not target_components:
            return child, {
                "rewritten_components": [],
                "reflection_context_missing": True,
                "reflection_context_used_fallback": True,
            }

        component_indices, rewrite_summary, elapsed = cls._rewrite_targets_with_reflection(
            strategy=component_indices,
            component_pool=component_pool,
            reflection_context=reflection_context,
            targets=target_components,
        )
        for key, value in Mutation._ensure_complete_strategy(component_indices, component_pool).items():
            child.set_component_index(key, value)
        child.ea_llm_call_time += elapsed
        return child, {
            "rewritten_components": target_components,
            "rewrite_prompt_summary": rewrite_summary,
            "reflection_context_missing": bool(reflection_context.get("missing_data")),
            "reflection_context_used_fallback": bool(reflection_context.get("missing_data")),
        }

    @classmethod
    def _infer_final_turn(
        cls,
        *,
        summary: dict[str, Any],
        segments: list[dict[str, Any]],
        parsed_log: dict[str, Any],
    ) -> int:
        """Infer the last observed turn from parsed summary data."""
        candidates: list[int] = []
        for row in summary.get("resource_history", []) or []:
            time_value = row.get("time")
            if isinstance(time_value, int):
                candidates.append(time_value)
        for row in summary.get("feature_history", []) or []:
            time_value = row.get("time")
            if isinstance(time_value, int):
                candidates.append(time_value)
        for segment in segments:
            current_time = segment.get("current_time")
            if isinstance(current_time, int):
                candidates.append(current_time)
        for row in parsed_log.get("resource_history", []) or []:
            time_value = row.get("time")
            if isinstance(time_value, int):
                candidates.append(time_value)
        return max(candidates) if candidates else 0

    @classmethod
    def _build_quality_summary(cls, source: dict[str, Any]) -> dict[str, float | int]:
        """Collapse one summary-like dict into fixed counts and rates."""
        summary = _empty_quality_summary()
        for key in (
            "llm_move_count",
            "applied_success_count",
            "applied_failure_count",
            "duplicate_skipped_count",
            "direct_failure_count",
        ):
            value = source.get(key, 0)
            summary[key] = int(value) if isinstance(value, (int, float)) else 0

        move_count = int(summary["llm_move_count"])
        if move_count > 0:
            summary["success_rate"] = float(summary["applied_success_count"]) / move_count
            summary["failure_rate"] = (
                float(summary["applied_failure_count"]) + float(summary["direct_failure_count"])
            ) / move_count
            summary["duplicate_rate"] = float(summary["duplicate_skipped_count"]) / move_count
        return summary

    @classmethod
    def _build_phase_summaries(
        cls,
        segments: list[dict[str, Any]],
        final_turn: int,
    ) -> dict[str, dict[str, float | int]]:
        """Aggregate segment-level instruction quality into early/mid/late phases."""
        phase_buckets = {
            "early": _empty_quality_summary(),
            "mid": _empty_quality_summary(),
            "late": _empty_quality_summary(),
        }
        if not segments:
            return phase_buckets

        for index, segment in enumerate(segments):
            phase_name = cls._phase_name_for_segment(
                segment=segment,
                index=index,
                total_segments=len(segments),
                final_turn=final_turn,
            )
            bucket = phase_buckets[phase_name]
            segment_summary = cls._build_quality_summary(segment)
            for key in (
                "llm_move_count",
                "applied_success_count",
                "applied_failure_count",
                "duplicate_skipped_count",
                "direct_failure_count",
            ):
                bucket[key] = int(bucket[key]) + int(segment_summary[key])

        return {
            phase_name: cls._build_quality_summary(bucket)
            for phase_name, bucket in phase_buckets.items()
        }

    @classmethod
    def _phase_name_for_segment(
        cls,
        *,
        segment: dict[str, Any],
        index: int,
        total_segments: int,
        final_turn: int,
    ) -> str:
        """Assign a segment to early, mid, or late game."""
        current_time = segment.get("current_time")
        if isinstance(current_time, int) and final_turn > 0:
            ratio = current_time / max(final_turn, 1)
        else:
            ratio = (index + 1) / max(total_segments, 1)

        if ratio <= 1 / 3:
            return "early"
        if ratio <= 2 / 3:
            return "mid"
        return "late"

    @classmethod
    def _build_action_type_stats(cls, move_results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        """Summarize intended and executed action counts by action type."""
        intent_counts = {action_type: 0 for action_type in _ACTION_TYPES}
        executed_counts = {action_type: 0 for action_type in _ACTION_TYPES}

        for move in move_results:
            action_type = str(move.get("action_type") or "").strip().lower()
            if action_type not in intent_counts:
                continue
            intent_counts[action_type] += 1
            if move.get("status") in {"applied_success", "applied_failed"}:
                executed_counts[action_type] += 1

        return {
            "intent_counts": intent_counts,
            "executed_counts": executed_counts,
        }

    @classmethod
    def _derive_outcome(cls, summary: dict[str, Any], match_score: dict[str, Any] | None) -> str:
        """Map winner and fitness data onto a stable outcome label."""
        win_score = cls._match_win_score(match_score)
        if win_score == 1.0:
            return "win"
        if win_score == 0.0:
            return "loss"

        winner = summary.get("winner")
        target_side = summary.get("target_side")
        if winner is None or target_side is None:
            return "unknown"
        return "win" if str(winner) == str(target_side) else "loss"

    @staticmethod
    def _match_win_score(match_score: dict[str, Any] | None) -> float:
        if not isinstance(match_score, dict):
            return 0.0
        try:
            return float(match_score.get("win_score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _build_diagnosis_notes(
        cls,
        *,
        outcome: str,
        final_turn: int,
        max_turn: int,
        timeout: bool,
        global_summary: dict[str, float | int],
        phase_summaries: dict[str, dict[str, float | int]],
        action_type_stats: dict[str, dict[str, int]],
    ) -> list[str]:
        """Derive a few compact rule-based notes for reflection prompts."""
        notes: list[str] = []

        if timeout or (max_turn > 0 and final_turn >= max_turn):
            if outcome == "draw":
                notes.append("The game ended in a draw at the turn limit.")
            else:
                notes.append("The game reached the turn limit before a decisive finish.")

        attack_intents = action_type_stats["intent_counts"]["attack"]
        attack_executed = action_type_stats["executed_counts"]["attack"]
        if attack_intents >= 3 and attack_executed * 2 < attack_intents:
            notes.append("The agent produced many attack intentions but few successful attack executions.")

        late_summary = phase_summaries["late"]
        if (
            float(late_summary["duplicate_rate"]) >= 0.20
            or float(late_summary["failure_rate"]) >= 0.35
        ):
            notes.append("Late-game duplicate and failed actions were frequent.")

        if not notes and float(global_summary["success_rate"]) < 0.35:
            notes.append("Overall action application success was low across the game.")

        return notes[:3]

    @classmethod
    def _select_rewrite_targets(
        cls,
        *,
        component_pool: ComponentPool,
        config: EAConfig,
        reflection_context: dict[str, Any],
    ) -> list[str]:
        """Choose a small set of strategy components to rewrite conservatively."""
        max_components = min(
            max(1, int(config.reflection_max_components_to_rewrite)),
            2,
        )

        available_targets = list(component_pool.evolving_component_keys)
        if not available_targets:
            return []

        selected_targets: list[str] = []
        phase_quality = reflection_context.get("phase_instruction_quality", {})
        action_type_stats = reflection_context.get("action_type_stats", {})
        intent_counts = dict(action_type_stats.get("intent_counts") or {})
        executed_counts = dict(action_type_stats.get("executed_counts") or {})

        if intent_counts.get("attack", 0) > executed_counts.get("attack", 0):
            selected_targets.extend(
                target
                for target in ("decision_priority", "late_game_plan")
                if target in available_targets
            )

        late_summary = dict(phase_quality.get("late") or {})
        if (
            float(late_summary.get("duplicate_rate", 0.0)) >= 0.20
            or float(late_summary.get("failure_rate", 0.0)) >= 0.35
        ):
            selected_targets.extend(
                target
                for target in ("anti_stall_rules", "tactical_heuristics")
                if target in available_targets
            )

        if not selected_targets:
            selected_targets.append(
                "decision_priority" if "decision_priority" in available_targets else available_targets[0]
            )

        deduplicated: list[str] = []
        for target in selected_targets:
            if target not in deduplicated:
                deduplicated.append(target)
        return deduplicated[:max_components]

    @classmethod
    def _rewrite_targets_with_reflection(
        cls,
        *,
        strategy: dict[str, int],
        component_pool: ComponentPool,
        reflection_context: dict[str, Any],
        targets: list[str],
    ) -> tuple[dict[str, int], str, float]:
        """Rewrite selected targets using compact summarized game feedback."""
        updated_strategy = dict(strategy or {})
        total_elapsed = 0.0
        rewritten_targets: list[str] = []

        for target in targets:
            current_text = Mutation._component_text(component_pool, updated_strategy, target)
            instruction = cls._build_reflection_instruction(
                strategy=updated_strategy,
                component_pool=component_pool,
                target_component=target,
                reflection_context=reflection_context,
            )
            rewritten_text, elapsed = Mutation.rewrite_component_with_llm(
                current_text,
                instruction,
            )
            total_elapsed += elapsed
            rewritten_component = component_pool.parse_component_str(rewritten_text)
            new_index = component_pool.add_component(target, rewritten_component)
            updated_strategy[target] = new_index
            rewritten_targets.append(target)

        summary = f"reflection: rewrote {', '.join(rewritten_targets)}"
        return updated_strategy, summary, total_elapsed

    @classmethod
    def _build_reflection_instruction(
        cls,
        *,
        strategy: dict[str, int],
        component_pool: ComponentPool,
        target_component: str,
        reflection_context: dict[str, Any],
    ) -> str:
        """Assemble the rewrite instruction used by the reflection operator."""
        strategy_snapshot = Mutation._format_strategy_snapshot(strategy, component_pool)
        identity_text = Mutation._component_text(
            component_pool,
            strategy,
            getattr(component_pool, "identity_component_key", None),
        )
        context_lines = json_dumps_compact(reflection_context)
        return (
            "Reflection operator\n"
            f"Rewrite target: {target_component}\n\n"
            "Goal:\n"
            "- Make one conservative improvement using compact feedback from the parent's last real game.\n"
            "- Keep strategy_identity unchanged.\n"
            "- Rewrite only the named target component.\n"
            "- Preserve the existing strategic style unless the feedback strongly suggests a local adjustment.\n"
            "- Prefer practical constraints that improve execution reliability over ambitious redesigns.\n\n"
            f"Current strategy_identity:\n{identity_text}\n\n"
            f"Current strategy snapshot:\n{strategy_snapshot}\n\n"
            "Compact reflection context:\n"
            f"{context_lines}\n\n"
            "Return only the rewritten text for the target component with no explanation."
        )


def json_dumps_compact(value: Any) -> str:
    """Render compact JSON for prompt context blocks."""
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def read_max_turn_hint(repo_root: Path) -> int | None:
    """Read the configured `max_cycles` value when available."""
    properties_path = locate_microrts_root(repo_root) / "resources" / "config.properties"
    if not properties_path.exists():
        return None

    for raw_line in properties_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "max_cycles":
            continue
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
