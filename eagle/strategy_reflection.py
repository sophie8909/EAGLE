"""Four-role Strategy Reflection pipeline.

The pipeline deliberately separates match understanding, candidate-level
strategy diagnosis, strategy mutation, and Java generation.  Code Reflection
continues to use :mod:`eagle.rewrite` and is not routed through this module.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from evaluation.match_logs import delete_match_log, read_match_log_chunks

from .candidate import Candidate
from .llm_transport import truncate_prompt
from .mutation import ReflectionContext, utc_now
from .offspring import normalize_prompt


CANONICAL_ROLES = ("match_commentator", "manager", "coach", "generator")
ROLE_SCHEMA_VERSION = "strategy-reflection-v1"
PROMPT_VERSION = "sports-team-v1"


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
class ManagerPlan:
    overall_assessment: str
    strengths_to_preserve: tuple[str, ...]
    recurring_weaknesses: tuple[dict[str, Any], ...]
    opponent_specific_findings: tuple[dict[str, Any], ...]
    priority_improvements: tuple[dict[str, Any], ...]
    strategy_constraints: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("strengths_to_preserve", "recurring_weaknesses", "opponent_specific_findings", "priority_improvements", "strategy_constraints"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True)
class CoachResult:
    strategy_changes: dict[str, list[str]]
    parent_strategy_prompt: str
    new_strategy_prompt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyReflectionResult:
    candidate: Candidate
    status: str
    analyses: tuple[MatchAnalysis, ...] = ()
    manager: ManagerPlan | None = None
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
        if "ROLE: manager" in prompt:
            return json.dumps({
                "overall_assessment": "Preserve the opening and improve timely pressure.",
                "strengths_to_preserve": ["stable opening"],
                "recurring_weaknesses": [],
                "opponent_specific_findings": [],
                "priority_improvements": [{"priority": 1, "problem": "late pressure", "recommended_direction": "attack after the first combat group is ready", "supporting_matches": []}],
                "strategy_constraints": [],
            })
        if "ROLE: coach" in prompt:
            parent = _text_value(prompt, "parent_strategy_prompt")
            return json.dumps({
                "strategy_changes": {"preserved": ["stable opening"], "removed_or_reduced": [], "added_or_strengthened": ["attack after the first combat group is ready"]},
                "parent_strategy_prompt": parent,
                "new_strategy_prompt": parent + "\nIf the first combat group is ready, attack before floating resources.",
            })
        return ""


class StrategyReflectionPipeline:
    """Run Commentator -> Manager -> Coach using shared backend plumbing."""

    def __init__(self, backend: RoleBackend, *, max_attempts: int = 3, max_prompt_chars: int = 60_000, model_identity: str | None = None, enabled_roles: set[str] | None = None) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.backend = backend
        self.max_attempts = max_attempts
        self.max_prompt_chars = max_prompt_chars
        self.model_identity = model_identity
        self.enabled_roles = frozenset(("match_commentator", "manager", "coach") if enabled_roles is None else enabled_roles)

    def mutate(self, candidate: Candidate, context: ReflectionContext, *, artifact_dir: Path | None = None) -> Candidate:
        result = self.run(candidate, context, artifact_dir=artifact_dir)
        return result.candidate

    def run(self, candidate: Candidate, context: ReflectionContext, *, artifact_dir: Path | None = None) -> StrategyReflectionResult:
        required_roles = {"match_commentator", "manager", "coach"}
        if required_roles - self.enabled_roles:
            return _failed_result(candidate, artifact_dir, "strategy reflection roles disabled", [])
        analyses: list[MatchAnalysis] = []
        failures: list[str] = []
        for item in context.per_match_results:
            match_id = str(item.get("match_id") or f"match_{item.get('match_index', len(analyses)):03d}")
            log_path = _resolve_path(item.get("match_log_path"))
            if log_path is None or not log_path.exists():
                failures.append(f"{match_id}: commentary unavailable")
                _write_status(artifact_dir, match_id, "unavailable", failures[-1])
                continue
            try:
                analysis = self._commentate(candidate, context, item, match_id, log_path, artifact_dir)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                failures.append(f"{match_id}: {exc}")
                _write_status(artifact_dir, match_id, "failed", str(exc))
                delete_match_log(log_path)
                continue
            analyses.append(analysis)
            delete_match_log(log_path)

        if failures:
            return _failed_result(candidate, artifact_dir, f"commentary: {failures[0]}", analyses)

        manager_payload = _manager_payload(candidate, context, analyses)
        try:
            manager_raw = self._call_role("manager", _manager_prompt(manager_payload), candidate, artifact_dir, extra={"candidate_id": candidate.id})
            manager = _parse_manager(manager_raw)
            _write_json(artifact_dir, "reflection/manager_analysis.json", manager.to_dict())
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return _failed_result(candidate, artifact_dir, f"manager: {exc}", analyses)

        try:
            coach_request = _coach_prompt(candidate.strategy_prompt, manager)
            coach_raw = self._call_role("coach", coach_request, candidate, artifact_dir, extra={"parent_candidate_id": candidate.id})
            coach = _parse_coach(coach_raw, parent_strategy_prompt=candidate.strategy_prompt)
            child = replace(
                candidate,
                strategy_prompt=normalize_prompt(coach.new_strategy_prompt, max_chars=4000, max_lines=80),
                mutation_type="strategy",
                metadata={
                    **candidate.metadata,
                    "strategy_reflection": {
                        "schema_version": ROLE_SCHEMA_VERSION,
                        "parent_candidate_id": candidate.id,
                        "analyses": [item.to_dict() for item in analyses],
                        "manager_analysis": manager.to_dict(),
                        "coach_result": coach.to_dict(),
                        "commentary_failures": failures,
                    },
                    "mutation": {"applied": True, "type": "strategy", "reflection_error": None, "rewrite_error": None},
                },
            )
            _write_json(artifact_dir, "reflection/coach_result.json", coach.to_dict())
            return StrategyReflectionResult(child, "success", tuple(analyses), manager, coach, None)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return _failed_result(candidate, artifact_dir, f"coach: {exc}", analyses, manager=manager)

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
            request = _commentator_synthesis_prompt(match_id, partials)
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


def _commentator_prompt(candidate: Candidate, context: ReflectionContext, item: dict[str, Any], match_id: str, chunk: list[dict[str, Any]], chunk_index: int, chunk_count: object) -> str:
    return "\n".join([
        "ROLE: match_commentator",
        "You are the Match Commentator for an evolutionary MicroRTS team.",
        "Analyze one completed match only. Analyze both candidate and opponent.",
        "Do not modify strategy, write Java, calculate fitness, or act as Manager or Coach.",
        f"match_id: {json.dumps(match_id)}",
        f"candidate_strategy: {json.dumps(candidate.strategy_prompt, ensure_ascii=False)}",
        f"opponent: {json.dumps(item.get('opponent_name') or item.get('opponent') or 'unknown')}",
        f"coverage_chunk: {chunk_index + 1}/{chunk_count}",
        "Return the compact match_analysis JSON schema.",
        json.dumps(chunk, ensure_ascii=False, sort_keys=True),
    ])


def _commentator_synthesis_prompt(match_id: str, partials: list[dict[str, Any]]) -> str:
    return "\n".join(["ROLE: match_commentator", "Synthesize the complete match analysis from all non-overlapping chunks.", f"match_id: {json.dumps(match_id)}", json.dumps(partials, ensure_ascii=False, sort_keys=True)])


def _manager_prompt(payload: dict[str, Any]) -> str:
    return "\n".join([
        "ROLE: manager",
        "You are the Manager of an evolutionary MicroRTS team.",
        "Use all match analyses to produce a concise strategic improvement plan.",
        "Do not inspect raw ticks, Java, compiler logs, or write the final strategy prompt.",
        "Return JSON with priority_improvements limited to at most three items.",
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    ])


def _coach_prompt(parent_strategy: str, manager: ManagerPlan) -> str:
    return "\n".join([
        "ROLE: coach",
        "You are the Coach of an evolutionary MicroRTS team.",
        "Revise the parent strategy prompt using the Manager improvement plan.",
        "Return a replacement strategy prompt with concrete conditional behavioral rules.",
        "Do not write Java, discuss implementation details, or return analysis outside the schema.",
        "parent_strategy_prompt: " + json.dumps(parent_strategy, ensure_ascii=False),
        "manager_analysis: " + json.dumps(manager.to_dict(), ensure_ascii=False, sort_keys=True),
    ])


def _manager_payload(candidate: Candidate, context: ReflectionContext, analyses: list[MatchAnalysis]) -> dict[str, Any]:
    game = context.game_evidence or {}
    return {
        "candidate_id": candidate.id,
        "game_performance": context.aggregate_game_performance,
        "opponent_results": [item.to_json_dict() for item in context.opponent_results],
        "matches": [
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


def _parse_manager(payload: str) -> ManagerPlan:
    data = _parse_json(payload)
    priorities = tuple(item for item in data.get("priority_improvements", []) if isinstance(item, dict))[:3]
    if not isinstance(data.get("overall_assessment"), str) or not data["overall_assessment"].strip():
        raise ValueError("manager output must contain an overall assessment")
    if "new_strategy_prompt" in data or "java" in json.dumps(data).lower():
        raise ValueError("manager output crossed its responsibility boundary")
    return ManagerPlan(
        overall_assessment=data["overall_assessment"].strip(),
        strengths_to_preserve=_strings(data.get("strengths_to_preserve")),
        recurring_weaknesses=tuple(item for item in data.get("recurring_weaknesses", []) if isinstance(item, dict)),
        opponent_specific_findings=tuple(item for item in data.get("opponent_specific_findings", []) if isinstance(item, dict)),
        priority_improvements=priorities,
        strategy_constraints=_strings(data.get("strategy_constraints")),
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


def _failed_result(candidate: Candidate, root: Path | None, error: str, analyses: list[MatchAnalysis], *, manager: ManagerPlan | None = None) -> StrategyReflectionResult:
    _write_json(root, "reflection/commentary_failure.json", {"role": error.split(":", 1)[0], "candidate_id": candidate.id, "generation_index": candidate.generation, "error": error, "schema_version": ROLE_SCHEMA_VERSION})
    child = replace(candidate, metadata={**candidate.metadata, "mutation": {"applied": False, "type": "strategy", "reflection_error": error, "rewrite_error": error}})
    return StrategyReflectionResult(child, "failed", tuple(analyses), manager, None, error)


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
