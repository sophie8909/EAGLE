"""Commentator-to-Coach Strategy Reflection pipeline.

The Commentator diagnoses selected matches and the Coach directly converts
those diagnoses plus canonical matchup metadata into a revised strategy.
Java generation remains outside this module.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from evaluation.match_logs import read_match_log_chunks

from .candidate import Candidate
from .llm import truncate_prompt
from .mutation import ReflectionContext, utc_now
from .prompts import normalize_prompt
from .strategy_diversity import build_strategy_niche, normalize_strategy_signature


CANONICAL_ROLES = ("match_commentator", "coach", "generator")
ROLE_SCHEMA_VERSION = "strategy-reflection-v2"
PROMPT_VERSION = "sports-team-v2"

STRATEGY_MUTATION_INTENT_DISTRIBUTION = (
    ("REFINE", 0.40),
    ("COUNTER", 0.25),
    ("STRUCTURAL", 0.20),
    ("ALTERNATIVE", 0.15),
)
COACH_INTENT_INSTRUCTIONS = {
    "REFINE": "Preserve the parent's overall strategic identity. Modify only the strategic behaviors required to address the highest-priority findings in the selected match diagnoses.",
    "COUNTER": "Focus on opponent behavior identified by the selected match diagnoses as causing important failures. Create concrete conditional responses while preserving unrelated successful strategy components.",
    "STRUCTURAL": "You may substantially reorganize the opening, economy, production, attack timing, expansion, or defense strategy. Do not merely rewrite the parent using different wording; use the evidence to create a materially different strategic structure.",
    "ALTERNATIVE": "Solve the diagnosed problems using a different strategic approach from the parent. Avoid reproducing the parent's core strategy unless the evidence makes it necessary.",
}


# Mutation-intent selection is part of the EA RNG stream; the role pipeline
# below consumes that selected intent but never creates a second RNG system.
def normalize_mutation_intent(value: object) -> str | None:
    intent = str(value or "").strip().upper()
    return intent if intent in {name for name, _ in STRATEGY_MUTATION_INTENT_DISTRIBUTION} else None


def select_strategy_mutation_intent(*, rng: random.Random | None = None, seed: int | None = None) -> str:
    """Select exactly one intent from the small deterministic EA distribution."""

    if rng is None:
        if seed is None:
            raise ValueError("select_strategy_mutation_intent requires rng or seed")
        rng = random.Random(seed)
    draw = rng.random()
    cumulative = 0.0
    for intent, probability in STRATEGY_MUTATION_INTENT_DISTRIBUTION:
        cumulative += probability
        if draw < cumulative:
            return intent
    return STRATEGY_MUTATION_INTENT_DISTRIBUTION[-1][0]


class RoleBackend(Protocol):
    def generate(self, prompt: str) -> str:
        """Return one raw response from the shared LLM backend."""


@dataclass(frozen=True)
class MatchAnalysis:
    match_id: str
    candidate_strategy: dict[str, str]
    opponent_strategy: dict[str, str]
    turning_points: tuple[dict[str, Any], ...]
    candidate_strengths: tuple[str, ...]
    candidate_weaknesses: tuple[str, ...]
    win_loss_analysis: dict[str, Any]
    strategy_observations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["turning_points"] = [dict(item) for item in self.turning_points]
        payload["candidate_strengths"] = list(self.candidate_strengths)
        payload["candidate_weaknesses"] = list(self.candidate_weaknesses)
        payload["strategy_observations"] = list(self.strategy_observations)
        return payload


@dataclass(frozen=True)
class CoachResult:
    strategy_changes: dict[str, list[str]]
    strategy_signature: dict[str, Any]
    parent_strategy_prompt: str
    new_strategy_prompt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyReflectionResult:
    candidate: Candidate
    status: str
    analyses: tuple[MatchAnalysis, ...] = ()
    coach: CoachResult | None = None
    error: str | None = None


class MockRoleBackend:
    """Small deterministic backend for mocked EA and pipeline tests."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "ROLE: match_commentator" in prompt:
            match_id = _json_value(prompt, "match_id") or "match"
            return json.dumps({
                "match_id": match_id,
                "candidate_strategy": {"summary": "candidate economy and pressure", "opening": "worker opening", "economy": "steady", "production": "produced units", "combat": "contested center", "expansion": "none"},
                "opponent_strategy": {"summary": "opponent pressure", "opening": "rush", "economy": "limited", "production": "early army", "combat": "front attack", "expansion": "none"},
                "turning_points": [{"tick": 0, "event": "opening", "impact": "both sides established"}],
                "candidate_strengths": ["stable opening"],
                "candidate_weaknesses": ["late pressure"],
                "win_loss_analysis": {"result": "draw", "primary_reason": "mock evidence", "secondary_reasons": []},
                "strategy_observations": ["mock observation"],
            })
        if "ROLE: coach" in prompt:
            parent = _text_value(prompt, "parent_strategy_prompt")
            return json.dumps({
                "strategy_changes": {"preserved": ["stable opening"], "removed_or_reduced": [], "added_or_strengthened": ["attack after the first combat group is ready"]},
                "strategy_signature": {"opening": "worker_first", "economy": "balanced_worker", "production": ["worker", "light"], "attack_timing": "mid", "combat_style": "pressure", "expansion": "conditional", "defense": "reactive", "target_priority": "workers"},
                "parent_strategy_prompt": parent,
                "new_strategy_prompt": parent + "\nIf the first combat group is ready, attack before floating resources.",
            })
        return ""


# Strategy Reflection role pipeline: selected match evidence -> commentator ->
# coach. Java generation remains outside this module.
class StrategyReflectionPipeline:
    """Run Commentator -> Coach using shared backend plumbing."""

    def __init__(self, backend: RoleBackend, *, max_attempts: int = 3, max_prompt_chars: int = 60_000, model_identity: str | None = None, enabled_roles: set[str] | None = None, selection_seed: int = 0) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.backend = backend
        self.max_attempts = max_attempts
        self.max_prompt_chars = max_prompt_chars
        self.model_identity = model_identity
        self.enabled_roles = frozenset(("match_commentator", "coach") if enabled_roles is None else enabled_roles)
        self.selection_seed = int(selection_seed)

    def mutate(self, candidate: Candidate, context: ReflectionContext, *, artifact_dir: Path | None = None, mutation_intent: str | None = None) -> Candidate:
        result = self.run(candidate, context, artifact_dir=artifact_dir, mutation_intent=mutation_intent)
        return result.candidate

    def run(self, candidate: Candidate, context: ReflectionContext, *, artifact_dir: Path | None = None, mutation_intent: str | None = None) -> StrategyReflectionResult:
        required_roles = {"match_commentator", "coach"}
        intent = normalize_mutation_intent(mutation_intent) or select_strategy_mutation_intent(
            seed=_intent_seed(self.selection_seed, context.evolution.generation_index, candidate.id, context.index)
        )
        parent_niche = candidate.strategy_niche or "unknown"
        candidate = replace(
            candidate,
            mutation_intent=intent,
            parent_strategy_niche=parent_niche,
        )
        _write_json(artifact_dir, "reflection/mutation_intent.json", {
            "mutation_intent": intent,
            "parent_strategy_niche": parent_niche,
            "child_strategy_niche": parent_niche,
            "niche_changed": False,
        })
        if required_roles - self.enabled_roles:
            return _failed_result(candidate, artifact_dir, "strategy reflection roles disabled", [])
        analyses: list[MatchAnalysis] = []
        failures: list[str] = []
        selection = select_reflection_matches(
            context.per_match_results,
            run_seed=self.selection_seed,
            generation_index=context.evolution.generation_index,
            candidate_id=candidate.id,
            reflection_invocation=context.index,
        )
        _write_json(artifact_dir, "reflection/match_selection.json", selection)
        selected_ids = set(selection["selected_match_ids"])
        for item in context.per_match_results:
            match_id = _match_id(item)
            if match_id not in selected_ids:
                _delete_raw_match_artifacts(item)

        selected_items = [item for item in context.per_match_results if _match_id(item) in selected_ids]
        for item in selected_items:
            match_id = str(item.get("match_id") or f"match_{item.get('match_index', len(analyses)):03d}")
            log_path = _resolve_path(item.get("match_log_path"))
            if log_path is None or not log_path.exists():
                failures.append(f"{match_id}: commentary unavailable")
                _write_status(artifact_dir, match_id, "unavailable", failures[-1])
                _delete_raw_match_artifacts(item)
                continue
            try:
                analysis = self._commentate(candidate, context, item, match_id, log_path, artifact_dir)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                failures.append(f"{match_id}: {exc}")
                _write_status(artifact_dir, match_id, "failed", str(exc))
                _delete_raw_match_artifacts(item)
                continue
            analyses.append(analysis)
            _delete_raw_match_artifacts(item)

        try:
            coach_payload = _coach_payload(candidate, context, analyses, selection, failures)
            coach_request = _coach_prompt(candidate.strategy_prompt, coach_payload, intent)
            coach_raw = self._call_role("coach", coach_request, candidate, artifact_dir, extra={"parent_candidate_id": candidate.id})
            coach = _parse_coach(coach_raw, parent_strategy_prompt=candidate.strategy_prompt)
            child_signature = normalize_strategy_signature(coach.strategy_signature)
            child_niche = build_strategy_niche(child_signature)
            niche_changed = parent_niche != "unknown" and child_niche != parent_niche
            child = replace(
                candidate,
                strategy_prompt=normalize_prompt(coach.new_strategy_prompt, max_chars=4000, max_lines=80),
                strategy_signature=child_signature,
                strategy_niche=child_niche,
                mutation_intent=intent,
                parent_strategy_niche=parent_niche,
                niche_changed=niche_changed,
                mutation_type="strategy",
                metadata={
                    **candidate.metadata,
                    "strategy_reflection": {
                        "schema_version": ROLE_SCHEMA_VERSION,
                        "parent_candidate_id": candidate.id,
                        "analyses": [item.to_dict() for item in analyses],
                        "coach_input": coach_payload,
                        "coach_result": coach.to_dict(),
                        "mutation_intent": intent,
                        "parent_strategy_niche": parent_niche,
                        "child_strategy_niche": child_niche,
                        "niche_changed": niche_changed,
                        "commentary_failures": failures,
                        "match_selection": selection,
                    },
                    "mutation": {"applied": True, "type": "strategy", "reflection_error": None, "rewrite_error": None},
                },
            )
            _write_json(artifact_dir, "reflection/coach_result.json", coach.to_dict())
            _write_json(artifact_dir, "reflection/mutation_intent.json", {
                "mutation_intent": intent,
                "parent_strategy_niche": parent_niche,
                "child_strategy_niche": child_niche,
                "niche_changed": niche_changed,
            })
            return StrategyReflectionResult(child, "success", tuple(analyses), coach, None)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return _failed_result(candidate, artifact_dir, f"coach: {exc}", analyses)

    def _commentate(self, candidate: Candidate, context: ReflectionContext, item: dict[str, Any], match_id: str, log_path: Path, artifact_dir: Path | None) -> MatchAnalysis:
        chunks = read_match_log_chunks(log_path, max_chars=self.max_prompt_chars)
        if not chunks:
            raise ValueError("match log contains no ticks")
        partials: list[dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunks):
            request = _commentator_prompt(candidate, context, item, match_id, chunk, chunk_index, "unknown")
            raw = self._call_role("match_commentator", request, candidate, artifact_dir, match_id=match_id)
            partials.append(_parse_json(raw))
        if not partials:
            raise ValueError("match log contains no ticks")
        if len(partials) == 1:
            analysis = _parse_commentary(partials[0], match_id)
        else:
            request = _commentator_synthesis_prompt(match_id, item, partials)
            raw = self._call_role("match_commentator", request, candidate, artifact_dir, match_id=match_id, suffix="synthesis")
            analysis = _parse_commentary(_parse_json(raw), match_id)
        _write_json(artifact_dir, f"commentary/{match_id}/match_analysis.json", analysis.to_dict())
        _write_status(artifact_dir, match_id, "succeeded", None)
        return analysis

    def _call_role(self, role: str, prompt: str, candidate: Candidate, artifact_dir: Path | None, *, match_id: str | None = None, suffix: str = "", extra: dict[str, Any] | None = None) -> str:
        request_id = uuid4().hex
        trace = {"role": role, "candidate_id": candidate.id, "generation_index": candidate.generation, "request_id": request_id, "model_configuration_identity": self.model_identity, "prompt_version": PROMPT_VERSION, "schema_version": ROLE_SCHEMA_VERSION, **(extra or {})}
        if match_id is not None:
            trace["match_id"] = match_id
        bounded = truncate_prompt(prompt, max_chars=self.max_prompt_chars)
        name = "request.json" if not suffix else f"request_{suffix}.json"
        _write_json(artifact_dir, f"commentary/{match_id}/{name}" if match_id else f"reflection/{role}_{name}", {**trace, "prompt": bounded})
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                raw = self.backend.generate(bounded)
                envelope = {**trace, "attempt": attempt, "status": "success", "duration_seconds": max(0.0, time.monotonic() - started), "response": raw}
                response_name = "response.json" if not suffix else f"response_{suffix}.json"
                _write_json(artifact_dir, f"commentary/{match_id}/{response_name}" if match_id else f"reflection/{role}_{response_name}", envelope)
                return raw
            except (OSError, RuntimeError, ValueError) as exc:
                last_error = str(exc) or type(exc).__name__
        raise RuntimeError(last_error or f"{role} failed after {self.max_attempts} attempts")


class StrategyReflectionMutation(StrategyReflectionPipeline):
    """Compatibility-shaped mutation operator used by ``eagle.search``."""

    pass


# Match selection and raw-log lifecycle -------------------------------------
def select_reflection_matches(
    match_results: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    run_seed: int,
    generation_index: int,
    candidate_id: str,
    reflection_invocation: int = 0,
) -> dict[str, Any]:
    """Select up to three detailed matches using reproducible loss/draw/win priority."""

    rows = [item for item in match_results if isinstance(item, dict)]
    pools: dict[str, list[dict[str, Any]]] = {"loss": [], "draw": [], "win": []}
    for item in rows:
        outcome = _match_outcome(item)
        if outcome is not None:
            pools[outcome].append(item)
    if pools["loss"]:
        selected_outcome = "loss"
    elif pools["draw"]:
        selected_outcome = "draw"
    elif pools["win"]:
        selected_outcome = "win"
    else:
        selected_outcome = None

    eligible = pools[selected_outcome] if selected_outcome is not None else []
    seed = _selection_seed(
        run_seed=run_seed,
        generation_index=generation_index,
        candidate_id=candidate_id,
        reflection_invocation=reflection_invocation,
    )
    sample_size = min(3, len(eligible))
    selected, weight_tiers = _sample_by_opponent_weight(eligible, sample_size, seed)
    return {
        "schema_version": "strategy-reflection-match-selection-v1",
        "candidate_id": candidate_id,
        "generation_index": generation_index,
        "total_match_count": len(rows),
        "available_results": {key: len(pools[key]) for key in ("loss", "draw", "win")},
        "selected_outcome_class": selected_outcome,
        "selection_rule": "strict_priority_loss_draw_win",
        "sampling_priority": "descending_opponent_weight_within_selected_outcome",
        "eligible_match_ids": [_match_id(item) for item in eligible],
        "selected_match_ids": [_match_id(item) for item in selected],
        "opponent_weight_tiers": weight_tiers,
        "requested_sample_size": 3,
        "actual_sample_size": sample_size,
        "random_provenance": {
            "seed": seed,
            "run_seed": int(run_seed),
            "generation_index": int(generation_index),
            "candidate_id": candidate_id,
            "reflection_invocation": int(reflection_invocation),
        },
    }


def _sample_by_opponent_weight(
    eligible: list[dict[str, Any]], sample_size: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sample from descending opponent-weight tiers without replacement."""

    tiers: dict[float, list[dict[str, Any]]] = {}
    for item in eligible:
        weight = _opponent_weight(item)
        tiers.setdefault(weight, []).append(item)
    ordered_tiers = sorted(tiers.items(), key=lambda pair: pair[0], reverse=True)
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    remaining = sample_size
    for weight, items in ordered_tiers:
        tier_ids = [_match_id(item) for item in items]
        chosen_count = min(remaining, len(items))
        chosen = rng.sample(items, chosen_count)
        selected.extend(chosen)
        metadata.append({
            "opponent_weight": weight,
            "eligible_match_ids": tier_ids,
            "selected_match_ids": [_match_id(item) for item in chosen],
        })
        remaining -= chosen_count
        if remaining == 0:
            break
    return selected, metadata


def _selection_seed(*, run_seed: int, generation_index: int, candidate_id: str, reflection_invocation: int) -> int:
    material = f"{int(run_seed)}:{int(generation_index)}:{candidate_id}:{int(reflection_invocation)}:strategy_reflection".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def _intent_seed(run_seed: int, generation_index: int, candidate_id: str, invocation: int) -> int:
    material = f"{int(run_seed)}:{int(generation_index)}:{candidate_id}:{int(invocation)}:strategy_mutation_intent".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def _match_id(item: dict[str, Any]) -> str:
    return str(item.get("match_id") or f"match_{int(item.get('match_index', -1)):03d}")


def _opponent_weight(item: dict[str, Any]) -> float:
    try:
        weight = float(item.get("opponent_weight", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return weight if weight == weight else 1.0


def _match_outcome(item: dict[str, Any]) -> str | None:
    if item.get("ok") is False or str(item.get("status") or "").lower() in {"failed", "error", "unavailable"}:
        return None
    candidate_player = item.get("candidate_player")
    winner = item.get("winner")
    try:
        candidate_player = int(candidate_player)
    except (TypeError, ValueError):
        candidate_player = None
    try:
        winner = int(winner)
    except (TypeError, ValueError):
        winner = None
    if candidate_player in {0, 1} and winner in {0, 1}:
        return "win" if winner == candidate_player else "loss"
    result = str(item.get("result") or "").lower()
    if "win" in result:
        if candidate_player is not None and result == f"p{candidate_player}_win":
            return "win"
        if result in {"p0_win", "p1_win"}:
            return "loss"
    if "draw" in result or winner not in {0, 1}:
        return "draw"
    return None


def _delete_raw_match_artifacts(item: dict[str, Any]) -> None:
    """Delete temporary commentator logs while preserving compact score artifacts."""

    paths = [item.get("match_log_path"), item.get("match_trace_path")]
    match_dir: Path | None = None
    for value in paths:
        if value:
            path = Path(str(value))
            match_dir = path.parent
            path.unlink(missing_ok=True)
    replay = item.get("replay_path")
    if replay:
        Path(str(replay)).unlink(missing_ok=True)
    if match_dir is not None:
        round_states = match_dir / "round_states"
        if round_states.exists():
            shutil.rmtree(round_states)


# Role prompt construction and response parsing -----------------------------
def _commentator_prompt(candidate: Candidate, context: ReflectionContext, item: dict[str, Any], match_id: str, chunk: list[dict[str, Any]], chunk_index: int, chunk_count: object) -> str:
    return "\n".join([
        "ROLE: match_commentator",
        "You are the Match Commentator for an evolutionary MicroRTS team.",
        "Analyze one completed match only. Analyze both candidate and opponent.",
        "Do not generalize this single match to the candidate's entire strategy.",
        "Analyze only the supplied match. The Coach will receive this diagnosis together with aggregate evaluation metadata.",
        "Do not modify strategy, write Java, calculate fitness, or act as Coach.",
        f"match_id: {json.dumps(match_id)}",
        f"candidate_basic_strategy: {json.dumps(candidate.strategy_prompt, ensure_ascii=False)}",
        f"opponent_basic_strategy: {json.dumps({'identity': item.get('opponent_name') or item.get('opponent') or 'unknown', 'class': item.get('opponent') or 'unknown'}, ensure_ascii=False, sort_keys=True)}",
        f"complete_match_record: {json.dumps(item, ensure_ascii=False, sort_keys=True)}",
        f"coverage_chunk: {chunk_index + 1}/{chunk_count}",
        "Return the compact match_analysis JSON schema.",
        json.dumps(chunk, ensure_ascii=False, sort_keys=True),
    ])


def _commentator_synthesis_prompt(match_id: str, item: dict[str, Any], partials: list[dict[str, Any]]) -> str:
    return "\n".join([
        "ROLE: match_commentator",
        "Synthesize the complete match analysis from all non-overlapping chunks.",
        "Analyze only the supplied match and do not generalize it to the candidate's entire strategy.",
        f"match_id: {json.dumps(match_id)}",
        f"complete_match_record: {json.dumps(item, ensure_ascii=False, sort_keys=True)}",
        json.dumps(partials, ensure_ascii=False, sort_keys=True),
    ])


def _coach_prompt(parent_strategy: str, payload: dict[str, Any], mutation_intent: str) -> str:
    return "\n".join([
        "ROLE: coach",
        "You are the Coach of an evolutionary MicroRTS team.",
        "Revise the parent strategy prompt directly from the selected Match Commentator diagnoses and canonical evaluation metadata.",
        "Commentator diagnoses are evidence about selected matches, not a replacement for the aggregate opponent results.",
        "Preserve successful behaviors identified by aggregate results, and use the detailed diagnoses to make concrete conditional changes.",
        "Detailed-match selection uses strict categorical priority: loss > draw > win, with at most three samples and no outcome backfill.",
        "Return a replacement strategy prompt with concrete conditional behavioral rules.",
        f"Mutation Intent: {mutation_intent}",
        COACH_INTENT_INSTRUCTIONS[mutation_intent],
        "Return exactly one JSON object with strategy_changes, strategy_signature, parent_strategy_prompt, and new_strategy_prompt.",
        "strategy_changes must contain preserved, removed_or_reduced, and added_or_strengthened arrays.",
        "strategy_signature must contain short categorical opening, economy, production, attack_timing, combat_style, expansion, defense, and target_priority fields.",
        "Do not append reflection history recursively.",
        "Do not write Java, discuss implementation details, or return analysis outside the schema.",
        "parent_strategy_prompt: " + json.dumps(parent_strategy, ensure_ascii=False),
        "commentator_diagnoses_and_evaluation_metadata: " + json.dumps(payload, ensure_ascii=False, sort_keys=True),
    ])


def _coach_payload(candidate: Candidate, context: ReflectionContext, analyses: list[MatchAnalysis], selection: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    game = context.game_evidence or {}
    selection_metadata = dict(selection)
    selection_metadata.update({
        "selected_match_count": selection.get("actual_sample_size", 0),
        "total_losses": (selection.get("available_results") or {}).get("loss", 0),
        "total_draws": (selection.get("available_results") or {}).get("draw", 0),
        "total_wins": (selection.get("available_results") or {}).get("win", 0),
        "commentary_failures": list(failures),
        "selection_is_biased_toward_worse_outcomes": True,
    })
    return {
        "candidate_id": candidate.id,
        "game_performance": context.aggregate_game_performance,
        "opponent_results": [item.to_dict() for item in context.opponents],
        "commentator_diagnoses": [
            {
                "match_id": item.match_id,
                "opponent": _match_value(context, item.match_id, "opponent_name"),
                "map": _match_value(context, item.match_id, "map_name"),
                "candidate_side": _match_value(context, item.match_id, "candidate_side"),
                "result": item.win_loss_analysis.get("result"),
                "candidate_strategy_summary": item.candidate_strategy.get("summary", ""),
                "opponent_strategy_summary": item.opponent_strategy.get("summary", ""),
                "turning_points": list(item.turning_points),
                "candidate_strengths": list(item.candidate_strengths),
                "candidate_weaknesses": list(item.candidate_weaknesses),
                "win_loss_analysis": item.win_loss_analysis,
            }
            for item in analyses
        ],
        "aggregate_summary": {key: game.get(key) for key in ("wins", "draws", "losses", "completed_match_count", "score_stddev")},
        "parent_comparison": context.parent_comparison or {"available": False},
        "match_selection": selection_metadata,
    }


def _parse_commentary(payload: dict[str, Any], match_id: str) -> MatchAnalysis:
    if "new_strategy_prompt" in payload or "java" in json.dumps(payload).lower():
        raise ValueError("commentator output crossed its responsibility boundary")
    turning_points = tuple(item for item in payload.get("turning_points", []) if isinstance(item, dict) and item.get("tick") is not None)
    if not turning_points:
        raise ValueError("commentator output must contain tick-backed turning points")
    return MatchAnalysis(
        match_id=str(payload.get("match_id") or match_id),
        candidate_strategy=_strategy_section(payload.get("candidate_strategy")),
        opponent_strategy=_strategy_section(payload.get("opponent_strategy")),
        turning_points=turning_points,
        candidate_strengths=_strings(payload.get("candidate_strengths")),
        candidate_weaknesses=_strings(payload.get("candidate_weaknesses")),
        win_loss_analysis=dict(payload.get("win_loss_analysis") or {}),
        strategy_observations=_strings(payload.get("strategy_observations")),
    )


def _parse_coach(payload: str, *, parent_strategy_prompt: str) -> CoachResult:
    data = _parse_json(payload)
    prompt = str(data.get("new_strategy_prompt") or "").strip()
    if not prompt:
        raise ValueError("coach output must contain new_strategy_prompt")
    if "class " in prompt or "public void" in prompt or "```java" in prompt:
        raise ValueError("coach output must not contain Java")
    changes = data.get("strategy_changes") or {}
    return CoachResult(
        strategy_changes={key: _strings(changes.get(key)) for key in ("preserved", "removed_or_reduced", "added_or_strengthened")},
        strategy_signature=normalize_strategy_signature(data.get("strategy_signature")),
        parent_strategy_prompt=str(data.get("parent_strategy_prompt") or parent_strategy_prompt),
        new_strategy_prompt=prompt,
    )


def _parse_json(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("role response must be a JSON object")
    return payload


def _strategy_section(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("commentator strategy sections must be objects")
    return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in value or () if str(item).strip())


def _resolve_path(value: Any) -> Path | None:
    if not value:
        return None
    return Path(str(value))


def _match_value(context: ReflectionContext, match_id: str, key: str) -> Any:
    for item in context.per_match_results:
        if str(item.get("match_id") or "") == match_id:
            return item.get(key)
    return None


def _write_status(root: Path | None, match_id: str, status: str, error: str | None) -> None:
    _write_json(root, f"commentary/{match_id}/commentary_status.json", {"role": "match_commentator", "match_id": match_id, "status": status, "error": error, "schema_version": ROLE_SCHEMA_VERSION})


def _write_json(root: Path | None, relative: str, payload: object) -> None:
    if root is None:
        return
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _failed_result(candidate: Candidate, root: Path | None, error: str, analyses: list[MatchAnalysis]) -> StrategyReflectionResult:
    _write_json(root, "reflection/commentary_failure.json", {"role": error.split(":", 1)[0], "candidate_id": candidate.id, "generation_index": candidate.generation, "error": error, "schema_version": ROLE_SCHEMA_VERSION})
    child = replace(candidate, metadata={**candidate.metadata, "mutation": {"applied": False, "type": "strategy", "reflection_error": error, "rewrite_error": error}})
    return StrategyReflectionResult(child, "failed", tuple(analyses), None, error)


def _json_value(prompt: str, key: str) -> str | None:
    marker = f"{key}: "
    line = next((line for line in prompt.splitlines() if line.startswith(marker)), "")
    if not line:
        return None
    try:
        return str(json.loads(line[len(marker):]))
    except json.JSONDecodeError:
        return None


def _text_value(prompt: str, key: str) -> str:
    return _json_value(prompt, key) or ""
