"""Commentator-to-Coach Strategy Reflection pipeline.

The Commentator diagnoses selected matches and the Coach directly converts
those diagnoses plus canonical matchup metadata into a revised strategy. A
short contract-rewrite stage repairs only a proposed policy that fails the
deterministic MicroRTS contract. Java generation remains outside this module.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from evaluation.match_trace import iter_match_trace

from .candidate import Candidate
from .llm import LLMCallLogger, truncate_prompt
from .mutation import ReflectionContext, parse_json_object_response, utc_now
from .strategy_compliance import validate_strategy_prompt_contract
from .opponent_cases import LEXICASE_CASES
from .prompts import load_prompt, normalize_prompt, render_prompt
from .strategy_diversity import build_strategy_niche, normalize_strategy_signature


CANONICAL_ROLES = ("match_commentator", "coach", "generator")
ROLE_SCHEMA_VERSION = "strategy-reflection-v5"
PROMPT_VERSION = "sports-team-v6"
MICRORTS_GAMEPLAY_CONTRACT = load_prompt("microrts_gameplay_contract")

STRATEGY_MUTATION_INTENT_DISTRIBUTION = (
    ("REFINE", 0.40),
    ("COUNTER", 0.25),
    ("STRUCTURAL", 0.20),
    ("ALTERNATIVE", 0.15),
)
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
        if "ROLE: strategy_contract_rewriter" in prompt:
            return json.dumps({
                "revised_strategy_prompt": (
                    "If a friendly Worker is idle, carries no resource, and a reachable "
                    "Resource exists, have that Worker harvest the nearest reachable Resource. "
                    "If a friendly Worker is idle, carries a resource, and a friendly Base "
                    "exists, have that Worker return it to the nearest friendly Base. If a "
                    "friendly Base is idle, stockpile >= 1, and a free adjacent cell exists, "
                    "have that Base train a Worker into that cell. If a friendly Worker is "
                    "idle and an enemy Base exists, have that Worker target the nearest current "
                    "enemy Base, move toward it, and attack when in range. If no enemy Base "
                    "exists, a current enemy unit or building exists, and a friendly Worker is "
                    "idle, have that Worker target the nearest current enemy unit or building, "
                    "move toward it, and attack when in range."
                ),
            })
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
                "new_strategy_prompt": (
                    "If a friendly Worker is idle, carries no resource, and a reachable "
                    "Resource exists, have that Worker harvest the nearest reachable Resource. "
                    "If a friendly Worker is idle, carries a resource, and a friendly Base "
                    "exists, have that Worker return it to the nearest friendly Base. If a "
                    "friendly Base is idle, stockpile >= 1, and a free adjacent cell exists, "
                    "have that Base train a Worker into that cell. If a friendly Worker is "
                    "idle and an enemy Base exists, have that Worker target the nearest current "
                    "enemy Base, move toward it, and attack when in range. If no enemy Base "
                    "exists, a current enemy unit or building exists, and a friendly Worker is "
                    "idle, have that Worker target the nearest current enemy unit or building, "
                    "move toward it, and attack when in range."
                ),
            })
        return ""


# Strategy Reflection role pipeline: selected match evidence -> commentator ->
# coach. Java generation remains outside this module.
class StrategyReflectionPipeline:
    """Run Commentator -> Coach using shared backend plumbing."""

    def __init__(
        self,
        backend: RoleBackend,
        *,
        max_attempts: int = 3,
        max_prompt_chars: int = 60_000,
        model_identity: str | None = None,
        enabled_roles: set[str] | None = None,
        selection_seed: int = 0,
        sample_budget: int = 10,
        timing_logger: LLMCallLogger | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if sample_budget < 1:
            raise ValueError("sample_budget must be at least 1")
        self.backend = backend
        self.max_attempts = max_attempts
        self.max_prompt_chars = max_prompt_chars
        self.model_identity = model_identity
        self.enabled_roles = frozenset(("match_commentator", "coach") if enabled_roles is None else enabled_roles)
        self.selection_seed = int(selection_seed)
        self.sample_budget = int(sample_budget)
        self.timing_logger = timing_logger

    def mutate(self, candidate: Candidate, context: ReflectionContext, *, artifact_dir: Path | None = None, mutation_intent: str | None = None) -> Candidate:
        result = self.run(candidate, context, artifact_dir=artifact_dir, mutation_intent=mutation_intent)
        assert result.candidate.generation_prompt == candidate.generation_prompt
        return result.candidate

    def run(self, candidate: Candidate, context: ReflectionContext, *, artifact_dir: Path | None = None, mutation_intent: str | None = None) -> StrategyReflectionResult:
        required_roles = {"match_commentator", "coach"}
        original_generation_prompt = candidate.generation_prompt
        intent = normalize_mutation_intent(mutation_intent) or select_strategy_mutation_intent(
            seed=_intent_seed(self.selection_seed, context.evolution.generation_index, candidate.id, context.index)
        )
        strategy_source_parent_id = _strategy_source_parent_id(candidate, context)
        coach_prompt_name = f"coach_{intent.lower()}"
        _write_text(artifact_dir, "reflection/parent_strategy_prompt.txt", candidate.strategy_prompt)
        base_metadata = {
            "schema_version": "strategy-reflection-artifacts-v1",
            "generation": candidate.generation,
            "child_candidate_id": candidate.id,
            "mutation_operator": "strategy_reflection",
            "commentator_prompt_name": "match_commentator",
            "coach_prompt_name": coach_prompt_name,
        }
        if strategy_source_parent_id is not None:
            base_metadata["parent_candidate_id"] = strategy_source_parent_id
        _write_json(artifact_dir, "reflection/metadata.json", base_metadata)
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
            sample_budget=self.sample_budget,
        )
        _write_json(artifact_dir, "reflection/match_selection.json", selection)
        global_summary = build_global_evaluation_summary(context.game_evidence or {}, context.per_match_results)
        _write_json(artifact_dir, "reflection/global_evaluation_summary.json", global_summary)
        by_id = {_match_id(item): item for item in context.per_match_results}
        selected_items = [by_id[match_id] for match_id in selection["selected_match_ids"] if match_id in by_id]
        _write_json(
            artifact_dir,
            "reflection/selected_matches.json",
            [_selected_match_record(item) for item in selected_items],
        )
        metadata = {
            **base_metadata,
            "selected_match_count": len(selected_items),
        }
        _write_json(artifact_dir, "reflection/metadata.json", metadata)
        commentator_call_count = 0
        for item in selected_items:
            match_id = str(item.get("match_id") or f"match_{item.get('match_index', len(analyses)):03d}")
            log_path = _resolve_path(item.get("match_trace_path"))
            if log_path is None or not log_path.exists():
                failures.append(f"{match_id}: commentary unavailable")
                _write_status(artifact_dir, match_id, "unavailable", failures[-1])
                continue
            try:
                commentator_call_count += 1
                analysis = self._commentate(
                    candidate,
                    context,
                    item,
                    match_id,
                    log_path,
                    artifact_dir,
                    artifact_index=commentator_call_count,
                )
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                failures.append(f"{match_id}: {exc}")
                _write_status(artifact_dir, match_id, "failed", str(exc))
                continue
            analyses.append(analysis)

        _write_json(
            artifact_dir,
            "reflection/metadata.json",
            {
                **metadata,
                "commentator_call_count": commentator_call_count,
                "successful_commentator_count": len(analyses),
            },
        )
        if not analyses:
            return _failed_result(
                candidate,
                artifact_dir,
                "match_commentator: no valid match analyses",
                analyses,
            )
        try:
            coach_payload = _coach_payload(candidate, context, analyses, selection, failures, global_summary)
            coach_request = _coach_prompt(candidate.strategy_prompt, coach_payload, intent)
            bounded_coach_request = truncate_prompt(coach_request, max_chars=self.max_prompt_chars)
            _write_json(artifact_dir, "reflection/coach_input.json", {
                "prompt_name": coach_prompt_name,
                "render_variables": {
                    "gameplay_contract": MICRORTS_GAMEPLAY_CONTRACT,
                    "parent_strategy_prompt": json.dumps(candidate.strategy_prompt, ensure_ascii=False),
                    "commentator_diagnoses_and_evaluation_metadata": json.dumps(
                        coach_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
                "semantic_payload": {
                    "gameplay_contract": MICRORTS_GAMEPLAY_CONTRACT,
                    "parent_strategy_prompt": candidate.strategy_prompt,
                    "commentator_diagnoses_and_evaluation_metadata": coach_payload,
                },
            })
            _write_text(artifact_dir, "reflection/coach_prompt.txt", bounded_coach_request)
            coach_extra = {}
            if strategy_source_parent_id is not None:
                coach_extra["parent_candidate_id"] = strategy_source_parent_id
            coach_raw, validated_coach = self._call_role(
                "coach",
                bounded_coach_request,
                candidate,
                artifact_dir,
                extra=coach_extra,
                validator=lambda raw: _validate_coach_structure_response(
                    raw,
                    parent_strategy_prompt=candidate.strategy_prompt,
                ),
            )
            _write_text(artifact_dir, "reflection/coach_raw.txt", coach_raw)
            coach_output, coach = validated_coach
            _write_json(artifact_dir, "reflection/coach_output.json", coach_output)
            proposed_strategy = normalize_prompt(
                coach.new_strategy_prompt,
                max_chars=4000,
                max_lines=80,
            )
            _write_text(
                artifact_dir,
                "reflection/coach_proposed_strategy_prompt.txt",
                proposed_strategy,
            )
            contract_rewrite_applied = False
            try:
                validate_strategy_prompt_contract(proposed_strategy)
                corrected_strategy = proposed_strategy
                _write_json(artifact_dir, "reflection/strategy_contract_rewrite.json", {
                    "applied": False,
                    "initial_validation_error": None,
                })
            except ValueError as exc:
                initial_validation_error = str(exc)
                contract_request = render_prompt("strategy_contract_rewrite", {
                    "gameplay_contract": MICRORTS_GAMEPLAY_CONTRACT,
                    "proposed_strategy_prompt": proposed_strategy,
                    "validation_error": initial_validation_error,
                })
                _write_text(
                    artifact_dir,
                    "reflection/strategy_contract_rewriter_prompt.txt",
                    contract_request,
                )
                contract_raw, validated_contract = self._call_role(
                    "strategy_contract_rewriter",
                    contract_request,
                    candidate,
                    artifact_dir,
                    extra=coach_extra,
                    validator=_validate_strategy_contract_rewrite_response,
                )
                contract_output, corrected_strategy = validated_contract
                contract_rewrite_applied = True
                _write_text(
                    artifact_dir,
                    "reflection/strategy_contract_rewriter_raw.txt",
                    contract_raw,
                )
                _write_json(
                    artifact_dir,
                    "reflection/strategy_contract_rewriter_output.json",
                    contract_output,
                )
                _write_json(artifact_dir, "reflection/strategy_contract_rewrite.json", {
                    "applied": True,
                    "initial_validation_error": initial_validation_error,
                })
            coach = replace(coach, new_strategy_prompt=corrected_strategy)
            child_signature = normalize_strategy_signature(coach.strategy_signature)
            child_niche = build_strategy_niche(child_signature)
            niche_changed = parent_niche != "unknown" and child_niche != parent_niche
            child = replace(
                candidate,
                strategy_prompt=coach.new_strategy_prompt,
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
                        "parent_candidate_id": strategy_source_parent_id,
                        "analyses": [item.to_dict() for item in analyses],
                        "coach_input": coach_payload,
                        "coach_result": coach.to_dict(),
                        "contract_rewrite_applied": contract_rewrite_applied,
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
            _write_text(
                artifact_dir,
                "reflection/child_strategy_prompt.txt",
                child.strategy_prompt,
            )
            _write_json(artifact_dir, "reflection/coach_result.json", coach.to_dict())
            _write_json(artifact_dir, "reflection/mutation_intent.json", {
                "mutation_intent": intent,
                "parent_strategy_niche": parent_niche,
                "child_strategy_niche": child_niche,
                "niche_changed": niche_changed,
            })
            assert child.generation_prompt == original_generation_prompt
            return StrategyReflectionResult(child, "success", tuple(analyses), coach, None)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return _failed_result(candidate, artifact_dir, f"coach: {exc}", analyses)

    def _commentate(
        self,
        candidate: Candidate,
        context: ReflectionContext,
        item: dict[str, Any],
        match_id: str,
        log_path: Path,
        artifact_dir: Path | None,
        *,
        artifact_index: int,
    ) -> MatchAnalysis:
        raw_log = list(iter_match_trace(log_path))
        if not raw_log:
            raise ValueError("match log contains no ticks")
        request = _commentator_prompt(candidate, context, item, match_id, raw_log)
        raw, validated_commentary = self._call_role(
            "match_commentator",
            request,
            candidate,
            artifact_dir,
            match_id=match_id,
            validator=lambda response: _validate_commentary_response(response, match_id),
        )
        parsed_output, analysis = validated_commentary
        _write_json(
            artifact_dir,
            f"reflection/commentator_{artifact_index:02d}.json",
            parsed_output,
        )
        _write_json(artifact_dir, f"commentary/{match_id}/match_analysis.json", analysis.to_dict())
        _write_status(artifact_dir, match_id, "succeeded", None)
        return analysis

    def _call_role(
        self,
        role: str,
        prompt: str,
        candidate: Candidate,
        artifact_dir: Path | None,
        *,
        validator: Callable[[str], Any],
        match_id: str | None = None,
        suffix: str = "",
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, Any]:
        request_id = uuid4().hex
        trace = {"role": role, "candidate_id": candidate.id, "generation_index": candidate.generation, "request_id": request_id, "model_configuration_identity": self.model_identity, "prompt_version": PROMPT_VERSION, "schema_version": ROLE_SCHEMA_VERSION, **(extra or {})}
        if match_id is not None:
            trace["match_id"] = match_id
        bounded = truncate_prompt(prompt, max_chars=self.max_prompt_chars)
        name = "request.json" if not suffix else f"request_{suffix}.json"
        _write_json(artifact_dir, f"commentary/{match_id}/{name}" if match_id else f"reflection/{role}_{name}", {**trace, "prompt": bounded})
        last_error = ""
        last_response = ""
        for attempt in range(1, self.max_attempts + 1):
            started_at = utc_now()
            started = time.monotonic()
            raw = ""
            attempt_prompt = (
                bounded
                if not last_error
                else truncate_prompt(
                    render_prompt("role_validation_retry", {
                        "validation_error": last_error,
                        "previous_response": last_response,
                        "original_request": bounded,
                    }),
                    max_chars=self.max_prompt_chars,
                )
            )
            attempt_request_name = f"request_attempt_{attempt:03d}.json"
            _write_json(
                artifact_dir,
                f"commentary/{match_id}/{attempt_request_name}"
                if match_id
                else f"reflection/{role}_{attempt_request_name}",
                {**trace, "attempt": attempt, "prompt": attempt_prompt},
            )
            try:
                raw = self.backend.generate(attempt_prompt)
                last_response = raw
                validated = validator(raw)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                last_error = str(exc) or type(exc).__name__
                finished_at = utc_now()
                duration_seconds = max(0.0, time.monotonic() - started)
                envelope = {
                    **trace,
                    "attempt": attempt,
                    "status": "error",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_seconds": duration_seconds,
                    "response": raw,
                    "prompt": attempt_prompt,
                    "error": last_error,
                }
                attempt_name = f"response_attempt_{attempt:03d}.json"
                _write_json(artifact_dir, f"commentary/{match_id}/{attempt_name}" if match_id else f"reflection/{role}_{attempt_name}", envelope)
                self._write_role_timing(
                    trace,
                    role=role,
                    attempt=attempt,
                    status="error",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=duration_seconds,
                    failure_category=type(exc).__name__,
                )
                continue

            finished_at = utc_now()
            duration_seconds = max(0.0, time.monotonic() - started)
            envelope = {
                **trace,
                "attempt": attempt,
                "status": "success",
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": duration_seconds,
                "response": raw,
                "prompt": attempt_prompt,
            }
            response_name = "response.json" if not suffix else f"response_{suffix}.json"
            _write_json(artifact_dir, f"commentary/{match_id}/{response_name}" if match_id else f"reflection/{role}_{response_name}", envelope)
            attempt_name = f"response_attempt_{attempt:03d}.json"
            _write_json(artifact_dir, f"commentary/{match_id}/{attempt_name}" if match_id else f"reflection/{role}_{attempt_name}", envelope)
            self._write_role_timing(
                trace,
                role=role,
                attempt=attempt,
                status="success",
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration_seconds,
                failure_category=None,
            )
            return raw, validated
        raise RuntimeError(last_error or f"{role} failed after {self.max_attempts} attempts")

    def _write_role_timing(
        self,
        trace: dict[str, Any],
        *,
        role: str,
        attempt: int,
        status: str,
        started_at: str,
        finished_at: str,
        duration_seconds: float,
        failure_category: str | None,
    ) -> None:
        if self.timing_logger is None:
            return
        endpoint = getattr(self.backend, "chat_completions_url", None)
        if not isinstance(endpoint, str):
            endpoint = getattr(self.backend, "base_url", None)
        request_id = str(trace["request_id"])
        run_id = self.timing_logger.run_id or "run"
        self.timing_logger.write_timing_event(
            request_correlation_id=f"{run_id}:{request_id}:{attempt}",
            stage=role,
            status=status,
            model=self.model_identity,
            candidate_id=str(trace["candidate_id"]),
            generation=int(trace["generation_index"]),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            metadata={
                "operation_type": "mutation",
                "endpoint": endpoint,
                "failure_category": failure_category,
            },
        )


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
    sample_budget: int = 10,
) -> dict[str, Any]:
    """Select a deterministic, coverage-aware sample without replacement."""

    if sample_budget < 1:
        raise ValueError("sample_budget must be at least 1")
    rows = [item for item in match_results if isinstance(item, dict)]
    pools: dict[str, list[dict[str, Any]]] = {"loss": [], "draw": [], "win": []}
    unique_rows: dict[str, dict[str, Any]] = {}
    for item in rows:
        outcome = _match_outcome(item)
        if outcome is None:
            continue
        match_id = _match_id(item)
        if match_id in unique_rows:
            continue
        unique_rows[match_id] = item
        pools[outcome].append(item)
    eligible = list(unique_rows.values())
    seed = _selection_seed(
        run_seed=run_seed,
        generation_index=generation_index,
        candidate_id=candidate_id,
        reflection_invocation=reflection_invocation,
    )
    rng = random.Random(seed)
    sample_size = min(sample_budget, len(eligible))
    selected: list[dict[str, Any]] = []

    # First cover every opponent with a failure if possible. A draw is the
    # fallback only for an opponent with no loss; fully winning opponents wait
    # until the map/fill passes when there is spare budget.
    for opponent in _ordered_values(eligible, _match_opponent):
        if len(selected) >= sample_size:
            break
        candidates = [item for item in eligible if _match_opponent(item) == opponent and item not in selected]
        losses = [item for item in candidates if _match_outcome(item) == "loss"]
        draws = [item for item in candidates if _match_outcome(item) == "draw"]
        representative_pool = losses or draws
        if representative_pool:
            selected.append(_choose_coverage_candidate(representative_pool, selected, rng, prefer_map=True))

    # Then introduce maps that have not appeared yet. Coverage wins this pass;
    # result priority is used only among candidates with comparable coverage.
    while len(selected) < sample_size:
        remaining = [item for item in eligible if item not in selected]
        unseen_maps = [item for item in remaining if _match_map(item) not in {_match_map(row) for row in selected}]
        if not unseen_maps:
            break
        selected.append(_choose_coverage_candidate(unseen_maps, selected, rng, prefer_map=True))

    # Finally fill the budget with diverse opponent/map/side combinations and
    # LOSS > DRAW > WIN priority. The seeded RNG only breaks exact ties.
    while len(selected) < sample_size:
        remaining = [item for item in eligible if item not in selected]
        if not remaining:
            break
        selected.append(_choose_coverage_candidate(remaining, selected, rng))

    selected_outcomes = [_match_outcome(item) for item in selected]
    sampled_opponents = [_match_opponent(item) for item in selected]
    sampled_maps = [_match_map(item) for item in selected]
    sampled_sides = [_player_position(item) for item in selected]
    return {
        "schema_version": "strategy-reflection-match-selection-v2",
        "candidate_id": candidate_id,
        "generation_index": generation_index,
        "total_match_count": len(rows),
        "available_results": {key: len(pools[key]) for key in ("loss", "draw", "win")},
        "eligible_match_count": len(eligible),
        "eligible_match_ids": [_match_id(item) for item in eligible],
        "selected_match_ids": [_match_id(item) for item in selected],
        "selected_outcome_class": selected_outcomes[0] if selected_outcomes and len(set(selected_outcomes)) == 1 else ("mixed" if selected_outcomes else None),
        "selection_rule": "opponent_coverage_then_map_coverage_then_loss_draw_win",
        "sampling_priority": "opponent_coverage_then_map_coverage_then_loss_draw_win_then_seeded_random_ties",
        "sample_count": len(selected),
        "sampled_match_ids": [_match_id(item) for item in selected],
        "sampled_opponents": sampled_opponents,
        "sampled_maps": sampled_maps,
        "sampled_player_positions": sampled_sides,
        "sampled_results": selected_outcomes,
        "unique_opponents_sampled": len(set(sampled_opponents)),
        "unique_maps_sampled": len(set(sampled_maps)),
        "losses_sampled": selected_outcomes.count("loss"),
        "draws_sampled": selected_outcomes.count("draw"),
        "wins_sampled": selected_outcomes.count("win"),
        "coverage_counts": {
            "opponents": len(set(sampled_opponents)),
            "maps": len(set(sampled_maps)),
            "opponent_map_side_combinations": len({_coverage_key(item) for item in selected}),
        },
        "requested_sample_size": sample_budget,
        "actual_sample_size": sample_size,
        "random_provenance": {
            "seed": seed,
            "run_seed": int(run_seed),
            "generation_index": int(generation_index),
            "candidate_id": candidate_id,
            "reflection_invocation": int(reflection_invocation),
        },
    }


def _choose_coverage_candidate(
    candidates: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    rng: random.Random,
    *,
    prefer_map: bool = False,
) -> dict[str, Any]:
    seen_maps = {_match_map(item) for item in selected}
    seen_opponents = {_match_opponent(item) for item in selected}
    seen_combinations = {_coverage_key(item) for item in selected}

    def score(item: dict[str, Any]) -> tuple[int, int, int, int, float]:
        outcome = _match_outcome(item)
        result_priority = {"loss": 2, "draw": 1, "win": 0}.get(outcome or "win", 0)
        combination_priority = int(_coverage_key(item) not in seen_combinations)
        opponent_priority = int(_match_opponent(item) not in seen_opponents)
        map_priority = int(_match_map(item) not in seen_maps)
        if prefer_map:
            return (map_priority, result_priority, combination_priority, opponent_priority, rng.random())
        return (combination_priority, result_priority, opponent_priority, map_priority, rng.random())

    return max(candidates, key=score)


def _ordered_values(rows: list[dict[str, Any]], getter) -> list[str]:
    values = {getter(item) for item in rows}
    return sorted(values, key=lambda value: (LEXICASE_CASES.index(value) if value in LEXICASE_CASES else len(LEXICASE_CASES), value))


def _match_opponent(item: dict[str, Any]) -> str:
    return str(item.get("opponent_id") or item.get("opponent_name") or item.get("opponent") or "unknown")


def _match_map(item: dict[str, Any]) -> str:
    return str(item.get("map_id") or item.get("map_name") or item.get("map") or "unknown")


def _player_position(item: dict[str, Any]) -> str:
    value = item.get("candidate_player")
    if value in (0, 1):
        return f"p{value}"
    return str(item.get("candidate_side") or "unknown")


def _coverage_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (_match_opponent(item), _match_map(item), _player_position(item))


def build_global_evaluation_summary(
    game: dict[str, Any],
    match_results: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic breadth evidence from every evaluated match."""

    rows = [item for item in match_results if isinstance(item, dict)]
    completed = [item for item in rows if _match_outcome(item) is not None]
    opponent_payloads = {
        str(item.get("opponent_id")): item
        for item in game.get("opponent_results") or ()
        if isinstance(item, dict) and item.get("opponent_id")
    }
    configuration = game.get("evaluation_configuration") if isinstance(game.get("evaluation_configuration"), dict) else {}
    configured_maps = configuration.get("maps") or game.get("evaluation_maps") or ()
    map_ids = [f"map_{index}" for index, _ in enumerate(configured_maps, start=1)]
    map_ids.extend(_match_map(item) for item in rows if _match_map(item) not in map_ids)
    map_ids = list(dict.fromkeys(map_ids))
    rounds = int(configuration.get("rounds_per_map") or game.get("rounds_per_map") or 3)
    side_count = 2 if bool(configuration.get("swap_player_sides", game.get("swap_player_sides", True))) else 1
    default_required_cases = len(map_ids) * rounds * side_count

    opponent_summaries: list[dict[str, Any]] = []
    for opponent_id in LEXICASE_CASES:
        opponent_rows = [item for item in completed if _match_opponent(item) == opponent_id]
        source = opponent_payloads.get(opponent_id, {})
        expected = int(source.get("expected_match_count") or default_required_cases or 0)
        name = str(source.get("opponent_name") or (opponent_rows[0].get("opponent_name") if opponent_rows else opponent_id))
        map_summary = _grouped_match_summary(opponent_rows, _match_map)
        for map_id in map_ids:
            map_summary.setdefault(map_id, _empty_match_summary())
        side_summary = _grouped_match_summary(opponent_rows, _player_position)
        for side in ("p0", "p1") if side_count == 2 else ("p0",):
            side_summary.setdefault(side, _empty_match_summary())
        opponent_summaries.append({
            "opponent": name,
            "opponent_id": opponent_id,
            "wins": sum(_match_outcome(item) == "win" for item in opponent_rows),
            "draws": sum(_match_outcome(item) == "draw" for item in opponent_rows),
            "losses": sum(_match_outcome(item) == "loss" for item in opponent_rows),
            "win_rate": _win_rate(opponent_rows),
            "completed_matches": len(opponent_rows),
            "expected_matches": expected,
            "maps": map_summary,
            "player_sides": side_summary,
            "fully_beaten_opponent": bool(opponent_rows) and len(opponent_rows) == expected and all(_match_outcome(item) == "win" for item in opponent_rows),
        })

    fully_beaten = [item["opponent_id"] for item in opponent_summaries if item["fully_beaten_opponent"]]
    total_wins = sum(_match_outcome(item) == "win" for item in completed)
    total_draws = sum(_match_outcome(item) == "draw" for item in completed)
    total_losses = sum(_match_outcome(item) == "loss" for item in completed)
    return {
        "schema_version": "strategy-reflection-global-summary-v1",
        "source": "all_evaluated_match_results",
        "total_matches": len(rows),
        "evaluated_match_count": len(completed),
        "failed_or_unresolved_match_count": len(rows) - len(completed),
        "total_wins": total_wins,
        "total_draws": total_draws,
        "total_losses": total_losses,
        "competitive_win_rate": _win_rate(completed),
        "fully_beaten_opponents_count": len(fully_beaten),
        "fully_beaten_opponents": fully_beaten,
        "evaluation_configuration": {
            "maps": list(configured_maps),
            "rounds_per_map": rounds,
            "swap_player_sides": side_count == 2,
            "required_cases_per_opponent": default_required_cases,
        },
        "opponents": opponent_summaries,
    }


def _grouped_match_summary(rows: list[dict[str, Any]], key_getter) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        grouped.setdefault(str(key_getter(item)), []).append(item)
    return {
        key: {
            "wins": sum(_match_outcome(item) == "win" for item in values),
            "draws": sum(_match_outcome(item) == "draw" for item in values),
            "losses": sum(_match_outcome(item) == "loss" for item in values),
            "matches": len(values),
            "win_rate": _win_rate(values),
        }
        for key, values in grouped.items()
    }


def _empty_match_summary() -> dict[str, Any]:
    return {"wins": 0, "draws": 0, "losses": 0, "matches": 0, "win_rate": 0.0}


def _win_rate(rows: list[dict[str, Any]]) -> float:
    return round(sum(_match_outcome(item) == "win" for item in rows) / len(rows), 6) if rows else 0.0


def _selection_seed(*, run_seed: int, generation_index: int, candidate_id: str, reflection_invocation: int) -> int:
    material = f"{int(run_seed)}:{int(generation_index)}:{candidate_id}:{int(reflection_invocation)}:strategy_reflection".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def _intent_seed(run_seed: int, generation_index: int, candidate_id: str, invocation: int) -> int:
    material = f"{int(run_seed)}:{int(generation_index)}:{candidate_id}:{int(invocation)}:strategy_mutation_intent".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def _match_id(item: dict[str, Any]) -> str:
    return str(item.get("match_id") or f"match_{int(item.get('match_index', -1)):03d}")


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


def cleanup_retired_match_traces(
    candidates_dir: Path,
    candidates: list[Candidate] | tuple[Candidate, ...],
    *,
    surviving_candidate_ids: set[str],
) -> None:
    """Remove traces only after an atomic survivor boundary retires a candidate.

    Parent selection is with replacement, so multiple siblings can need the
    same parent's traces while a generation is being constructed.  The caller
    must invoke this only after the next surviving population has been recorded.
    """

    retired_ids = {
        candidate.id
        for candidate in candidates
        if candidate.id not in surviving_candidate_ids
    }
    for candidate_id in sorted(retired_ids):
        for trace_path in sorted((candidates_dir / candidate_id / "matches").glob("*/match_trace.jsonl.gz")):
            trace_path.unlink(missing_ok=True)


# Role prompt construction and response parsing -----------------------------
def _commentator_prompt(candidate: Candidate, context: ReflectionContext, item: dict[str, Any], match_id: str, raw_log: list[dict[str, Any]]) -> str:
    return render_prompt("match_commentator", {
        "gameplay_contract": MICRORTS_GAMEPLAY_CONTRACT,
        "match_id": json.dumps(match_id),
        "opponent": json.dumps(item.get("opponent_name") or item.get("opponent_id") or item.get("opponent") or "unknown"),
        "map": json.dumps(item.get("map_name") or item.get("map_id") or item.get("map") or "unknown"),
        "player_position": json.dumps(_player_position(item)),
        "result": json.dumps(_match_outcome(item) or "unknown"),
        "candidate_basic_strategy": json.dumps(candidate.strategy_prompt, ensure_ascii=False),
        "opponent_basic_strategy": json.dumps({
            "identity": item.get("opponent_name") or item.get("opponent") or "unknown",
            "class": item.get("opponent") or "unknown",
        }, ensure_ascii=False, sort_keys=True),
        "complete_match_record": json.dumps(_selected_match_record(item), ensure_ascii=False, sort_keys=True),
        "raw_game_log": json.dumps(raw_log, ensure_ascii=False, sort_keys=True),
    })


def _coach_prompt(parent_strategy: str, payload: dict[str, Any], mutation_intent: str) -> str:
    prompt_id = f"coach_{mutation_intent.lower()}"
    return render_prompt(prompt_id, {
        "gameplay_contract": MICRORTS_GAMEPLAY_CONTRACT,
        "parent_strategy_prompt": json.dumps(parent_strategy, ensure_ascii=False),
        "commentator_diagnoses_and_evaluation_metadata": json.dumps(payload, ensure_ascii=False, sort_keys=True),
    })


def _coach_payload(candidate: Candidate, context: ReflectionContext, analyses: list[MatchAnalysis], selection: dict[str, Any], failures: list[str], global_summary: dict[str, Any]) -> dict[str, Any]:
    selection_metadata = dict(selection)
    selection_metadata.update({
        "selected_match_count": selection.get("actual_sample_size", 0),
        "total_losses": (selection.get("available_results") or {}).get("loss", 0),
        "total_draws": (selection.get("available_results") or {}).get("draw", 0),
        "total_wins": (selection.get("available_results") or {}).get("win", 0),
        "commentary_failures": list(failures),
        "selection_is_coverage_aware": True,
    })
    return {
        "candidate_id": candidate.id,
        "global_evaluation_summary": global_summary,
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
        "parent_comparison": context.parent_comparison or {"available": False},
        "match_selection": selection_metadata,
    }


def _parse_commentary(payload: dict[str, Any], match_id: str) -> MatchAnalysis:
    if "new_strategy_prompt" in payload or "java" in json.dumps(payload).lower():
        raise ValueError("commentator output crossed its responsibility boundary")

    wrapped = payload.get("match_analysis")
    if wrapped is not None and not isinstance(wrapped, dict):
        raise ValueError("commentator match_analysis wrapper must be an object")
    analysis = wrapped if isinstance(wrapped, dict) else payload
    turning_points = _commentary_turning_points(analysis)
    if not turning_points:
        raise ValueError("commentator output must contain tick-backed turning points")

    weaknesses = _strings(analysis.get("candidate_weaknesses"))
    if not weaknesses:
        weaknesses = _structured_strings(
            analysis.get("strategic_failures"),
            fields=("category", "issue"),
        )

    opponent_strategy = analysis.get("opponent_strategy")
    if opponent_strategy is None:
        opponent_summary = _structured_strings(
            analysis.get("opponent_strengths"),
            fields=("tactic", "impact"),
        )
        opponent_strategy = {
            "summary": "; ".join(opponent_summary)
            or str(analysis.get("opponent") or "observed opponent strategy")
        }

    win_loss_analysis = analysis.get("win_loss_analysis")
    if win_loss_analysis is None:
        win_loss_analysis = {
            "result": str(analysis.get("result") or "unknown"),
            "decisive_causes": list(weaknesses),
        }
    if not isinstance(win_loss_analysis, dict):
        raise ValueError("commentator win_loss_analysis must be an object")

    return MatchAnalysis(
        match_id=str(analysis.get("match_id") or match_id),
        candidate_strategy=_strategy_section(analysis.get("candidate_strategy")),
        opponent_strategy=_strategy_section(opponent_strategy),
        turning_points=turning_points,
        candidate_strengths=_strings(analysis.get("candidate_strengths")),
        candidate_weaknesses=weaknesses,
        win_loss_analysis=dict(win_loss_analysis),
        strategy_observations=_strings(analysis.get("strategy_observations")),
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
        # The model echo remains losslessly available in coach_output.json, but
        # validated state must use the authoritative input gene.
        parent_strategy_prompt=parent_strategy_prompt,
        new_strategy_prompt=prompt,
    )


def _validate_commentary_response(raw: str, match_id: str) -> tuple[dict[str, object], MatchAnalysis]:
    payload = parse_json_object_response(raw)
    return payload, _parse_commentary(payload, match_id)


def _validate_coach_structure_response(
    raw: str,
    *,
    parent_strategy_prompt: str,
) -> tuple[dict[str, object], CoachResult]:
    payload = parse_json_object_response(raw)
    return payload, _parse_coach(raw, parent_strategy_prompt=parent_strategy_prompt)


def _validate_strategy_contract_rewrite_response(
    raw: str,
) -> tuple[dict[str, object], str]:
    payload = parse_json_object_response(raw)
    if set(payload) != {"revised_strategy_prompt"}:
        raise ValueError(
            "Strategy contract rewrite JSON must contain exactly revised_strategy_prompt."
        )
    prompt = payload["revised_strategy_prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(
            "Strategy contract rewrite revised_strategy_prompt must be a non-empty string."
        )
    normalized = normalize_prompt(prompt, max_chars=4000, max_lines=80)
    validate_strategy_prompt_contract(normalized)
    return payload, normalized


def _parse_json(raw: str) -> dict[str, Any]:
    return parse_json_object_response(raw)


def _strategy_section(value: Any) -> dict[str, str]:
    if isinstance(value, str) and value.strip():
        return {"summary": value.strip()}
    if not isinstance(value, dict):
        raise ValueError("commentator strategy sections must be objects")
    return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}


def _commentary_turning_points(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Normalize the two bounded Commentator timeline shapes seen in production."""

    source = payload.get("turning_points")
    legacy_observations = False
    if not isinstance(source, list) or not source:
        source = payload.get("key_observations")
        legacy_observations = True
    if not isinstance(source, list):
        return ()

    normalized: list[dict[str, Any]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        raw_tick = item.get("tick")
        if raw_tick is None:
            raw_tick = item.get("time")
        tick = _commentary_tick(raw_tick)
        if tick is None:
            continue
        if not legacy_observations:
            point = dict(item)
            point["tick"] = tick
            normalized.append(point)
            continue

        point: dict[str, Any] = {
            "tick": tick,
            "event": str(item.get("event") or item.get("summary") or "observed turning point").strip(),
        }
        if raw_tick is not None:
            point["source_time"] = str(raw_tick)
        impact = _commentary_analysis_summary(item.get("analysis") or item.get("impact"))
        if impact:
            point["impact"] = impact
        normalized.append(point)
    return tuple(normalized)


def _commentary_tick(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _commentary_analysis_summary(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    parts: list[str] = []
    for role in ("candidate", "opponent"):
        section = value.get(role)
        if not isinstance(section, dict):
            continue
        for field in ("behavior", "issue", "strength", "tactic", "impact"):
            detail = section.get(field)
            if isinstance(detail, str) and detail.strip():
                parts.append(f"{role} {field}: {detail.strip()}")
    for field in ("behavior", "issue", "impact"):
        detail = value.get(field)
        if isinstance(detail, str) and detail.strip():
            parts.append(f"{field}: {detail.strip()}")
    return "; ".join(dict.fromkeys(parts))


def _structured_strings(value: Any, *, fields: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return _strings(value)
    results: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            results.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        parts = [
            str(item.get(field)).strip()
            for field in fields
            if isinstance(item.get(field), str) and str(item.get(field)).strip()
        ]
        if parts:
            results.append(": ".join(parts))
    return tuple(results)


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple, set)):
        return ()
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


def _strategy_source_parent_id(candidate: Candidate, context: ReflectionContext) -> str | None:
    """Return recorded strategy-component provenance without comparing prompt text."""

    if candidate.strategy_parent_id:
        return candidate.strategy_parent_id
    if context.candidate.candidate_id:
        return context.candidate.candidate_id
    return context.candidate_id or None


def _selected_match_record(item: dict[str, Any]) -> dict[str, Any]:
    """Copy only available compact match fields in Commentator selection order."""

    record: dict[str, Any] = {"match_id": _match_id(item)}
    for key in (
        "match_index",
        "opponent_id",
        "opponent_name",
        "opponent",
        "map_id",
        "map_name",
        "map",
        "candidate_player",
        "candidate_side",
        "winner",
        "result",
        "performance",
        "score",
        "match_trace_path",
    ):
        if key not in item or item[key] is None:
            continue
        value = item[key]
        record[key] = str(value) if isinstance(value, Path) else value
    return record


def _write_status(root: Path | None, match_id: str, status: str, error: str | None) -> None:
    _write_json(root, f"commentary/{match_id}/commentary_status.json", {"role": "match_commentator", "match_id": match_id, "status": status, "error": error, "schema_version": ROLE_SCHEMA_VERSION})


def _write_text(root: Path | None, relative: str, value: str) -> None:
    if root is None:
        return
    path = _artifact_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_json(root: Path | None, relative: str, payload: object) -> None:
    if root is None:
        return
    path = _artifact_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _artifact_path(root: Path, relative: str) -> Path:
    if relative.startswith("reflection/"):
        relative = relative.removeprefix("reflection/")
    return root / "mutation" / "strategy_reflection" / relative


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
