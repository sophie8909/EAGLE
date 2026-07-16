"""Deterministic capability scoring from reachable Java and match evidence."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .microrts_runner import MatchResult


CAPABILITY_NAMES = (
    "economy",
    "production",
    "combat",
    "target_selection",
    "state_aware_decision",
)


@dataclass(frozen=True)
class CapabilityEvidence:
    capability: str
    static_evidence: tuple[str, ...]
    runtime_evidence: tuple[str, ...]
    score: int

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["static_evidence"] = list(self.static_evidence)
        payload["runtime_evidence"] = list(self.runtime_evidence)
        return payload


@dataclass(frozen=True)
class FunctionCapabilityResult:
    economy_score: int
    production_score: int
    combat_score: int
    targeting_score: int
    state_aware_decision_score: int
    evidence: dict[str, CapabilityEvidence]

    @property
    def function_score(self) -> int:
        return min(
            100,
            self.economy_score
            + self.production_score
            + self.combat_score
            + self.targeting_score
            + self.state_aware_decision_score,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "economy_score": self.economy_score,
            "production_score": self.production_score,
            "combat_score": self.combat_score,
            "targeting_score": self.targeting_score,
            "state_aware_decision_score": self.state_aware_decision_score,
            "function_score": self.function_score,
            "evidence": {name: item.to_json_dict() for name, item in self.evidence.items()},
        }


def evaluate_function_capability(
    generated_java: str,
    match_results: list[MatchResult],
) -> FunctionCapabilityResult:
    """Score behavior without requiring candidate-defined method names or layout."""

    source = _reachable_source(_strip_comments_and_literals(generated_java))
    static = {
        "economy": _matches(
            source,
            {
                "resource observation": r"\b(?:getResources|getResourceUsage|resource)\b",
                "harvest action": r"\b(?:harvest|TYPE_HARVEST|returnResources)\b",
                "worker reasoning": r"\bWorker\b",
            },
        ),
        "production": _matches(
            source,
            {
                "production action": r"\b(?:train|produce|TYPE_PRODUCE)\b",
                "construction action": r"\b(?:build|Barracks|Base)\b",
                "unit type reasoning": r"\b(?:UnitType|Light|Heavy|Ranged)\b",
            },
        ),
        "combat": _matches(
            source,
            {
                "attack action": r"\b(?:attack|TYPE_ATTACK_LOCATION)\b",
                "combat unit reasoning": r"\b(?:Light|Heavy|Ranged)\b",
                "enemy reasoning": r"\b(?:enemy|opponent|getPlayer)\b",
            },
        ),
        "target_selection": _matches(
            source,
            {
                "position comparison": r"\b(?:getX|getY|distance|closest|nearest)\b",
                "target state": r"\b(?:getHitPoints|getType|getPlayer)\b",
                "candidate comparison": r"\b(?:for|while|stream)\b",
            },
        ),
        "state_aware_decision": _matches(
            source,
            {
                "conditional branch": r"\b(?:if|switch|case)\b",
                "game-state query": r"\b(?:getUnits|getPhysicalGameState|getActionAssignment)\b",
                "state comparison": r"(?:==|!=|<=|>=|<|>)",
            },
        ),
    }
    runtime = _runtime_evidence(match_results)
    evidence: dict[str, CapabilityEvidence] = {}
    for name in CAPABILITY_NAMES:
        static_items = tuple(static[name])
        runtime_items = tuple(runtime[name])
        score = 20 if static_items and runtime_items else 10 if static_items or runtime_items else 0
        evidence[name] = CapabilityEvidence(name, static_items, runtime_items, score)
    return FunctionCapabilityResult(
        economy_score=evidence["economy"].score,
        production_score=evidence["production"].score,
        combat_score=evidence["combat"].score,
        targeting_score=evidence["target_selection"].score,
        state_aware_decision_score=evidence["state_aware_decision"].score,
        evidence=evidence,
    )


def _runtime_evidence(match_results: list[MatchResult]) -> dict[str, list[str]]:
    output = {name: [] for name in CAPABILITY_NAMES}
    for result in match_results:
        if not result.ok:
            continue
        payload = result.raw_result or {}
        players = payload.get("players") or {}
        p0 = players.get("p0") or {}
        scoreboard = payload.get("final_scoreboard") or {}
        telemetry = result.telemetry
        if float(p0.get("carried_resources") or 0.0) > 0:
            _append(output["economy"], "carried resources observed")
        if telemetry and _series_changed([tick.player_resource for tick in telemetry.ticks]):
            _append(output["economy"], "player resources changed during match")
        if float(scoreboard.get("units_produced") or 0.0) > 0:
            _append(output["production"], "units produced")
        if telemetry and _series_changed([tick.player_unit_count for tick in telemetry.ticks]):
            _append(output["production"], "player unit count changed")
        if float(scoreboard.get("damage_dealt") or 0.0) > 0:
            _append(output["combat"], "damage dealt")
            _append(output["target_selection"], "damage required a selected target")
        if float(scoreboard.get("targets_attacked") or 0.0) > 0:
            _append(output["target_selection"], "targeted attacks recorded")
        if float(scoreboard.get("state_transitions") or 0.0) > 0:
            _append(output["state_aware_decision"], "state-dependent decisions recorded")
        if telemetry and _series_decreased([tick.enemy_total_unit_value for tick in telemetry.ticks]):
            _append(output["combat"], "enemy material decreased")
            _append(output["target_selection"], "enemy material was removed")
        if result.winner == 0:
            _append(output["combat"], "match win")
        if telemetry and len(telemetry.ticks) > 1:
            material = [tick.player_total_unit_value - tick.enemy_total_unit_value for tick in telemetry.ticks]
            resources = [tick.resource_diff for tick in telemetry.ticks]
            if _series_changed(material) or _series_changed(resources):
                _append(output["state_aware_decision"], "state-dependent telemetry changed")
    return output


def _matches(source: str, patterns: dict[str, str]) -> list[str]:
    return [label for label, pattern in patterns.items() if re.search(pattern, source, re.IGNORECASE)]


def _append(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _series_changed(values: list[float | int]) -> bool:
    return len(values) > 1 and any(value != values[0] for value in values[1:])


def _series_decreased(values: list[float | int]) -> bool:
    return len(values) > 1 and min(values[1:]) < values[0]


def _reachable_source(source: str) -> str:
    """Remove constant-false blocks before deterministic evidence matching."""

    pattern = re.compile(r"\bif\s*\(\s*false\s*\)\s*\{", re.IGNORECASE)
    while True:
        match = pattern.search(source)
        if match is None:
            return source
        depth = 1
        index = match.end()
        while index < len(source) and depth:
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
            index += 1
        source = source[: match.start()] + " " * (index - match.start()) + source[index:]


def _strip_comments_and_literals(source: str) -> str:
    pattern = re.compile(
        r'''//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*''',
        re.DOTALL,
    )
    return pattern.sub(lambda match: "\n" * match.group(0).count("\n"), source)
