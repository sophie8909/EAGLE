"""Deterministic guardrails for strategy-language contract violations.

The LLM receives the complete gameplay contract and remains responsible for
the policy design.  This module catches a deliberately small set of concepts
that the contract unambiguously excludes, so a bounded retry can ask the model
to reformulate them instead of silently accepting an invalid prompt.
"""

from __future__ import annotations

import re


_CONTRACT_VIOLATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:enemy[- ]owned cell|friendly[- ]owned cell|enemy territory|"
            r"friendly territory|territorial|starting cell|spawn(?:ing)? (?:cell|point|location))\b",
            re.IGNORECASE,
        ),
        "cells have no owner, territory, start, or spawn attribute",
    ),
    (
        re.compile(
            r"\b(?:enemy|opponent)(?:'s)?\s+(?:Workers?|units?|Lights?|Heavies|Ranged)\s+"
            r"(?:(?:is|are)\s+)?(?:converging|moving toward)|"
            r"\b(?:enemy|opponent)\s+(?:movement trend|trajectory|velocity)\b",
            re.IGNORECASE,
        ),
        "opponent movement history, trajectory, and intent are not observable",
    ),
    (
        re.compile(
            r"\b(?:opponent|enemy)(?:'s)?\s+(?:economy|resource stockpile)\b.{0,32}"
            r"\b(?:stagnant|static|weak|strong|increasing|not increasing)\b",
            re.IGNORECASE,
        ),
        "opponent economy trends and qualitative strength are not observable",
    ),
    (
        re.compile(
            r"\b(?:economy|resource collection|production)\s+(?:stalls?|stagnates?|"
            r"is stagnant|is static)\b|"
            r"\b(?:resource\s+)?stockpile\b.{0,32}\b(?:has\s+)?not\s+increased\b|"
            r"\b(?:resource\s+)?stockpile\b.{0,32}\b(?:increased|decreased)\b.{0,24}"
            r"\b(?:over|during|for)\b",
            re.IGNORECASE,
        ),
        "history-based economy or production trends are not observable",
    ),
    (
        re.compile(
            r"\b(?:enemy|opponent)(?:'s)?\b.{0,40}\b(?:built|builds|constructed|"
            r"constructs|produced|produces|created)\b",
            re.IGNORECASE,
        ),
        "opponent production and construction history are not observable; test current entities instead",
    ),
    (
        re.compile(
            r"\b(?:is|are|was|were|has been|have been)?\s*(?:destroyed|lost)\b",
            re.IGNORECASE,
        ),
        "destruction and loss events are not observable; test whether the current entity exists",
    ),
    (
        re.compile(
            r"\b(?:newly|recently)\s+(?:produced|built|created)|"
            r"\bwithin\s+\d+\s+cycles?\s+of\s+(?:production|construction|harvest)|"
            r"\bafter\b.{0,40}\b(?:production|construction|harvest)\s+(?:completes?|completion)",
            re.IGNORECASE,
        ),
        "entity creation and action-completion history are not observable strategy state",
    ),
    (
        re.compile(
            r"\b(?:would|will)\s+(?:kill|destroy|survive|reach)|\bpotential\s+"
            r"(?:attack|counterattack|counter-attack|threat)|\bbefore the next\b",
            re.IGNORECASE,
        ),
        "future outcomes and actions are not observable",
    ),
    (
        re.compile(r"\b(?:under attack|is attacking|are attacking)\b", re.IGNORECASE),
        "an opponent's current action target is not observable; use current types, positions, ranges, and distances",
    ),
    (
        re.compile(
            r"\b(?:within|outside|not\s+within)\s+(?:the\s+)?attack\s+range\s+of\s+"
            r"(?:an?\s+|the\s+|any\s+)?(?:friendly\s+)?(?:Base|Barracks)\b",
            re.IGNORECASE,
        ),
        "Base and Barracks do not attack and therefore have no attack range",
    ),
    (
        re.compile(
            r"\b(?:enemy|opponent)\b.{0,48}\b(?:attacking|targeting)\s+"
            r"(?:an?\s+|the\s+|any\s+)?(?:friendly|our|Base|Worker)",
            re.IGNORECASE,
        ),
        "an opponent's current action target is not observable; use current types, positions, ranges, and distances",
    ),
    (
        re.compile(
            r"\b(?:not\s+visible|visibility|unseen|scout(?:ing)?(?:\s+for)?|"
            r"encounter(?:ed|ing)?)\b",
            re.IGNORECASE,
        ),
        "the game state is fully observable and has no scouting, encounter-memory, or visibility mechanic",
    ),
    (
        re.compile(
            r"\b(?:already|currently)\s+(?:training|producing|building|moving|"
            r"attacking|harvesting|returning)\b|\bno active production\b|\bif built\b",
            re.IGNORECASE,
        ),
        "only the current idle state is observable; current action type and action history are not strategy state",
    ),
    (
        re.compile(r"\b(?:threat|threats|threaten|threatens|threatening)\b", re.IGNORECASE),
        "threat is undefined; use current enemy type, position, attack range, and an explicit distance threshold",
    ),
    (
        re.compile(r"\b(?:cluster|clustering|consolidate|consolidating)\b", re.IGNORECASE),
        "this is not a legal action; state the exact move, target, attack, train, build, harvest, return, or idle response",
    ),
    (
        re.compile(r"\bnear\s+(?:a\s+|the\s+)?(?:Base|Barracks|Worker|enemy|resource)\b", re.IGNORECASE),
        "near is ambiguous; use an explicit grid-distance threshold",
    ),
    (
        re.compile(r"\b(?:block|blocks|blocking)\s+(?:enemy\s+|their\s+|its\s+)?movement\b", re.IGNORECASE),
        "blocking movement is not a legal strategic action",
    ),
    (
        re.compile(r"\b(?:capture|captures|capturing)\s+(?:enemy\s+|their\s+)?resources\b", re.IGNORECASE),
        "Resources are neutral and may be harvested, not captured",
    ),
    (
        re.compile(
            r"\b(?:target|attack)(?:s|ed|ing)?\b[^.;\n]{0,48}\bResources?\b|"
            r"\bResources?\b\s+(?:as\s+)?(?:an?\s+|the\s+)?(?:combat\s+)?target\b",
            re.IGNORECASE,
        ),
        "Resource is neutral and may only be harvested by a Worker; it is not a combat target",
    ),
    (
        re.compile(r"\bsafe location\b", re.IGNORECASE),
        "safe location is undefined; express it with free cells and current enemy distances",
    ),
    (
        re.compile(r"\b(?:harass|harasses|harassing)\b", re.IGNORECASE),
        "harass is not a legal action; state a concrete target, movement, and attack fallback",
    ),
    (
        re.compile(
            r"\b(?:AgentContext|isFreeCell|command[A-Z]\w*|get[A-Z]\w*)\s*\(?|"
            r"\bcontext\.|\b[A-Za-z_]\w*\.(?:get|is|has)[A-Za-z_]\w*\s*\(",
            re.IGNORECASE,
        ),
        "a strategy prompt must use game-level conditions and actions, not Java or API symbols",
    ),
    (
        re.compile(
            r"\b(?:target|attack)(?:s|ed|ing)?\s+(?:the\s+)?(?:nearest\s+)?"
            r"(?:reachable\s+)?friendly\s+(?:Base|Barracks|Worker|Light|Heavy|Ranged|"
            r"units?|buildings?|entities)\b",
            re.IGNORECASE,
        ),
        "target and attack actions may select only an enemy-owned unit or building, never a friendly entity",
    ),
)


def validate_strategy_prompt_contract(prompt: str) -> None:
    """Reject only explicit closed-world violations with retry-ready feedback."""

    source = str(prompt or "").strip()
    if not source:
        raise ValueError("Strategy prompt must not be empty.")
    semantic_source = re.sub(
        r"(?m)^\s*(?:[-*]\s+|\d+\.\s*)?\*\*[^*\n]+?(?:\*\*\s*:|:\*\*)\s*",
        "",
        source,
    )
    violations: list[str] = []
    for pattern, explanation in _CONTRACT_VIOLATIONS:
        match = pattern.search(semantic_source)
        if match is None:
            continue
        excerpt = " ".join(match.group(0).split())
        violations.append(f"{excerpt!r}: {explanation}")
    violations.extend(_production_relation_violations(semantic_source))
    violations.extend(_resource_cost_violations(semantic_source))
    violations.extend(_state_action_contradictions(semantic_source))
    violations.extend(_action_prerequisite_violations(semantic_source))
    violations.extend(_unit_range_violations(semantic_source))
    violations.extend(_combat_action_violations(semantic_source))
    violations.extend(_target_prerequisite_violations(semantic_source))
    violations.extend(_ambiguous_rule_violations(semantic_source))
    violations.extend(_structural_rule_violations(semantic_source))
    if violations:
        raise ValueError(
            "Strategy prompt violates the closed-world MicroRTS contract: "
            + "; ".join(violations[:8])
            + ". Reformulate each condition using only current observable state and each response as a legal action."
        )


def _clauses(source: str) -> tuple[str, ...]:
    return tuple(
        clause.strip()
        for clause in re.split(r"[.;\n]+", source)
        if clause.strip()
    )


def _production_relation_violations(source: str) -> list[str]:
    violations: list[str] = []
    relations = (
        (
            re.compile(
                r"\b(?:(?:assign|have)\s+(?:an?\s+)?(?:idle\s+)?Workers?\s+to\s+"
                r"(?:train|produce)|Workers?\s+(?:(?:must|may|should|can)\s+)?(?:train|produce))\b",
                re.IGNORECASE,
            ),
            "Workers cannot train or produce units; a Base trains Workers and a Barracks trains combat units",
        ),
        (
            re.compile(
                r"\b(?:(?:assign|have)\s+(?:that\s+|the\s+|an?\s+)?"
                r"(?:idle\s+)?Workers?\s+(?:to\s+)?build|"
                r"Workers?\s+(?:(?:must|may|should|can)\s+)?builds?)\s+"
                r"(?:an?\s+)?(?:Worker|Light|Heavy|Ranged)(?:\s+units?)?\b",
                re.IGNORECASE,
            ),
            "Workers build only Base or Barracks; a Base trains Workers and a Barracks trains combat units",
        ),
        (
            re.compile(
                r"\b(?:(?:assign|have)\s+(?:an?\s+)?(?:idle\s+)?Barracks\s+to\s+"
                r"(?:train|produce)|Barracks\s+(?:(?:must|may|should|can)\s+)?"
                r"(?:trains?|produces?))\s+(?:an?\s+)?Workers?\b",
                re.IGNORECASE,
            ),
            "Barracks cannot train Workers",
        ),
        (
            re.compile(
                r"\b(?:(?:assign|have)\s+(?:an?\s+)?(?:idle\s+)?Base\s+to\s+"
                r"(?:train|produce)|Base\s+(?:(?:must|may|should|can)\s+)?"
                r"(?:trains?|produces?))\s+(?:an?\s+)?(?:Light|Heavy|Ranged)\b",
                re.IGNORECASE,
            ),
            "Bases cannot train combat units",
        ),
        (
            re.compile(
                r"\b(?:Light|Heavy|Ranged)(?:\s+units?)?\s+"
                r"(?:(?:must|may|should|can)\s+)?(?:harvest|return|build|train|produce)\b",
                re.IGNORECASE,
            ),
            "combat units may only move, target, attack, or idle",
        ),
        (
            re.compile(
                r"\b(?:Base|Barracks)\s+(?:(?:must|may|should|can)\s+)?"
                r"(?:move|harvest|return|attack|build)\b",
                re.IGNORECASE,
            ),
            "Bases and Barracks are stationary producers and cannot move, harvest, return, attack, or build",
        ),
    )
    for clause in _clauses(source):
        for pattern, explanation in relations:
            match = pattern.search(clause)
            if match:
                violations.append(f"{match.group(0)!r}: {explanation}")
    return violations


def _resource_cost_violations(source: str) -> list[str]:
    violations: list[str] = []
    requirements = (("Base", 10), ("Barracks", 5))
    for clause in _clauses(source):
        for entity, cost in requirements:
            if not re.search(rf"\bbuild\s+(?:an?\s+)?{entity}\b", clause, re.IGNORECASE):
                continue
            threshold = re.search(
                r"\bresources?\s*(?:>=|≥|>|exceeds?)\s*(\d+)\b",
                clause,
                re.IGNORECASE,
            )
            if threshold and int(threshold.group(1)) < cost:
                violations.append(
                    f"{clause!r}: building a {entity} costs {cost} resources, "
                    f"but the stated threshold is {threshold.group(1)}"
                )
    return violations


def _resource_lower_bound(clause: str) -> int | None:
    normalized = clause.replace("≥", ">=")
    thresholds: list[int] = []
    patterns = (
        r"\b(?:resources?|stockpile)\s*(?:(?:is|are)\s*)?(?:>=|>)\s*(\d+)\b",
        r"\b(?:resources?|stockpile)\s+(?:(?:are|is)\s+)?at least\s+(\d+)\b",
        r"\b(?:has|have|with)\s+(?:a\s+stockpile\s+of\s+)?"
        r"(?:at least\s+)?(\d+)\s+resources?\b",
    )
    for pattern in patterns:
        thresholds.extend(
            int(match.group(1))
            for match in re.finditer(pattern, normalized, re.IGNORECASE)
        )
    return max(thresholds) if thresholds else None


def _has_free_adjacent_cell(clause: str) -> bool:
    return bool(
        re.search(
            r"\b(?:free|legal)\s+(?:adjacent\s+)?cells?\b|"
            r"\badjacent\s+(?:free|legal)\s+cells?\b",
            clause,
            re.IGNORECASE,
        )
    )


def _positive_action_clause(clause: str) -> bool:
    return not bool(
        re.search(
            r"\b(?:do not|don't|never|cannot|can't|must not)\b",
            clause,
            re.IGNORECASE,
        )
    )


def _action_prerequisite_violations(source: str) -> list[str]:
    violations: list[str] = []
    for clause in _clauses(source):
        if not _positive_action_clause(clause):
            continue

        production = re.search(
            r"\b(?:train|produce)(?:s|d|ing)?\s+(?:an?\s+)?"
            r"(Workers?|Light(?:\s+units?)?|Heavy(?:\s+units?)?|Ranged(?:\s+units?)?)\b",
            clause,
            re.IGNORECASE,
        )
        if production:
            product = production.group(1).lower()
            is_worker = product.startswith("worker")
            producer = "Base" if is_worker else "Barracks"
            producer_word = "Bases?" if is_worker else "Barracks"
            cost = 1 if is_worker else 2
            missing: list[str] = []
            producer_pattern = r"\bBases?\b" if producer == "Base" else r"\bBarracks\b"
            if not re.search(producer_pattern, clause, re.IGNORECASE):
                missing.append(f"an existing {producer}")
            if not re.search(
                rf"\b(?:friendly\s+)?{producer_word}\s+(?:is|are)\s+idle\b|"
                rf"\bidle\s+(?:friendly\s+)?{producer_word}\b",
                clause,
                re.IGNORECASE,
            ):
                missing.append(f"an idle {producer}")
            lower_bound = _resource_lower_bound(clause)
            if lower_bound is None or lower_bound < cost:
                missing.append(f"a stockpile of at least {cost}")
            if not _has_free_adjacent_cell(clause):
                missing.append("a free adjacent cell")
            if missing:
                violations.append(
                    f"{clause!r}: training {production.group(1)} must state "
                    + ", ".join(missing)
                )

        construction = re.search(
            r"\bbuild(?:s|ing)?\s+(?:an?\s+|new\s+)?(Base|Barracks)\b",
            clause,
            re.IGNORECASE,
        )
        if construction:
            building = construction.group(1).title()
            cost = 10 if building == "Base" else 5
            missing = []
            if not re.search(r"\bWorkers?\b", clause, re.IGNORECASE):
                missing.append("an existing Worker")
            if not re.search(
                r"\b(?:friendly\s+)?Worker\s+is\s+idle\b|"
                r"\bidle\s+(?:friendly\s+)?Worker\b",
                clause,
                re.IGNORECASE,
            ):
                missing.append("an idle Worker")
            lower_bound = _resource_lower_bound(clause)
            if lower_bound is None or lower_bound < cost:
                missing.append(f"a stockpile of at least {cost}")
            if not _has_free_adjacent_cell(clause):
                missing.append("a legal free adjacent cell")
            elif re.search(
                r"\badjacent\s+to\s+(?:that\s+|the\s+|a\s+)?"
                r"(?:friendly\s+)?(?:Base|Barracks)\b",
                clause,
                re.IGNORECASE,
            ) and not re.search(
                r"\badjacent\s+to\s+(?:(?:that|the|an?|one)\s+)?"
                r"(?:(?:idle|acting|friendly)\s+)*Workers?\b",
                clause,
                re.IGNORECASE,
            ) and not re.search(
                r"\bbuild(?:s|ing)?\s+(?:an?\s+|new\s+)?(?:Base|Barracks)\b"
                r"[^.;\n]{0,96}\badjacent\s+to\s+itself\b",
                clause,
                re.IGNORECASE,
            ):
                missing.append("a legal free cell adjacent to the acting Worker")
            if missing:
                violations.append(
                    f"{clause!r}: building a {building} must state "
                    + ", ".join(missing)
                )

        harvest_action = re.search(r"\bharvest(?:s|ed|ing)?\b", clause, re.IGNORECASE)
        if harvest_action:
            missing = []
            if not re.search(r"\bWorkers?\b", clause, re.IGNORECASE):
                missing.append("an existing Worker")
            if not re.search(r"\bidle\b", clause, re.IGNORECASE):
                missing.append("an idle Worker")
            if not re.search(
                r"\b(?:carr(?:y|ies|ying)|has|with)\s+no\s+(?:carried\s+)?resource\b|"
                r"\bcarried\s+resource(?:\s+amount)?\s*(?:=|is)\s*0\b",
                clause,
                re.IGNORECASE,
            ):
                missing.append("a Worker carrying no resource")
            if not re.search(
                r"\b(?:a|one|1|at\s+least\s+one)\s+reachable\s+Resources?\s+exists?\b|"
                r"\breachable\s+Resources?\s+(?:exists?|is\s+available)\b",
                clause,
                re.IGNORECASE,
            ):
                missing.append("an existing reachable Resource")
            if missing:
                violations.append(
                    f"{clause!r}: harvesting must state " + ", ".join(missing)
                )

        assignment = re.search(
            r"\b(?:assign|direct|send|deploy|redirect|have|keep)\b.{0,100}"
            r"\b(?:move|advance|attack|harvest|return|target|train|produce|build)\b",
            clause,
            re.IGNORECASE,
        )
        subject_action = re.search(
            r"\b(?:every|each|all|additional|other)\s+"
            r"(?:Workers?|Lights?|Heavies|Ranged(?:\s+units?)?|Bases?|Barracks)\s+"
            r"(?:moves?|advances?|attacks?|harvests?|returns?|trains?|produces?|builds?)\b",
            clause,
            re.IGNORECASE,
        )
        assignment_lacks_idle = bool(
            assignment
            and not re.search(
                r"\bidle\b",
                clause[: assignment.end()],
                re.IGNORECASE,
            )
        )
        if assignment_lacks_idle or subject_action:
            violations.append(
                f"{clause!r}: every assigned action must explicitly select an idle friendly actor"
            )

        return_action = re.search(
            r"\breturn(?:s|ed|ing)?\b",
            clause,
            re.IGNORECASE,
        )
        if return_action:
            if not re.search(r"\bWorkers?\b", clause, re.IGNORECASE):
                violations.append(f"{clause!r}: only a Worker can return a carried resource")
            if not re.search(
                r"\b(?:friendly\s+)?Worker\s+is\s+idle\b|"
                r"\bidle\s+(?:friendly\s+)?Worker\b",
                clause,
                re.IGNORECASE,
            ):
                violations.append(f"{clause!r}: returning requires an idle friendly Worker")
            explicitly_empty = re.search(
                r"\b(?:carr(?:y|ies|ying)|has|with)\s+no\s+(?:carried\s+)?resource\b|"
                r"\bcarried\s+resource(?:\s+amount)?\s*(?:=|is)\s*0\b",
                clause,
                re.IGNORECASE,
            )
            explicitly_carrying = re.search(
                r"\b(?:carr(?:y|ies|ying)|has|with)\s+(?:a|one|1)\s+"
                r"(?:carried\s+)?resource\b|\bcarried\s+resource(?:\s+amount)?\s*"
                r"(?:=|is|>=|≥)\s*1\b",
                clause,
                re.IGNORECASE,
            )
            if explicitly_empty or not explicitly_carrying:
                violations.append(
                    f"{clause!r}: returning requires a Worker currently carrying a resource"
                )
            legal_return_target = re.search(
                r"\breturn(?:s|ed|ing)?\b.{0,48}\bto\s+"
                r"(?:(?:the\s+)?nearest\s+|an?\s+|the\s+)?"
                r"(?:(?:existing|reachable)\s+)*friendly\s+Base\b",
                clause,
                re.IGNORECASE,
            )
            absent_friendly_base = re.search(
                r"\bno\s+friendly\s+Base\s+(?:exists?|remains?)\b",
                clause,
                re.IGNORECASE,
            )
            if not legal_return_target or absent_friendly_base:
                violations.append(
                    f"{clause!r}: a carried resource may be returned only to a friendly Base"
                )
            if re.search(
                r"\breturn(?:s|ed|ing)?\b.{0,120}\b(?:and|then)\s+"
                r"(?:have\s+(?:that|the)\s+Workers?\s+)?"
                r"(?:target|attack|move|advance|harvest|build|train|produce)\b|"
                r"\b(?:target|attack|move|advance|harvest|build|train|produce)\b"
                r".{0,120}\b(?:and|then)\s+return\b",
                clause,
                re.IGNORECASE,
            ):
                violations.append(
                    f"{clause!r}: one unit executes one action at a time; split return and the other action into separate current-state rules"
                )
    return violations


def _unit_range_violations(source: str) -> list[str]:
    """Catch explicit attack-range assignments that contradict the unit table."""

    violations: list[str] = []
    for clause in _clauses(source):
        light_or_heavy = re.search(
            r"\bfriendly\s+(?:Light|Heavy)(?:\s+(?:unit|units))?\b",
            clause,
            re.IGNORECASE,
        )
        attack_action = re.search(r"\battack\w*\b", clause, re.IGNORECASE)
        incorrect_three = re.search(
            r"\b(?:within\s+)?(?:its\s+)?(?:attack\s+)?range\s*(?:of\s*)?3\b|"
            r"\brange\s+1\s+or\s+3\s+respectively\b",
            clause,
            re.IGNORECASE,
        )
        mixed_respectively = re.search(
            r"\brange\s+1\s+or\s+3\s+respectively\b",
            clause,
            re.IGNORECASE,
        )
        closes_to_melee_range = bool(
            re.search(r"\b(?:move|advance)\w*\b", clause, re.IGNORECASE)
            and (
                re.search(
                    r"\battack\w*\b.{0,48}\b(?:within\s+(?:range\s*)?1|"
                    r"distance\s*(?:=|<=|≤|is)?\s*1)\b",
                    clause,
                    re.IGNORECASE,
                )
                or re.search(
                    r"\b(?:until|once|when|after)\b.{0,32}"
                    r"\b(?:within\s+(?:range\s*)?1|distance\s*(?:=|<=|≤|is)?\s*1)\b"
                    r".{0,48}\battack\w*\b",
                    clause,
                    re.IGNORECASE,
                )
            )
        )
        if (
            light_or_heavy
            and incorrect_three
            and (mixed_respectively or (attack_action and not closes_to_melee_range))
        ):
            violations.append(
                f"{clause!r}: Light and Heavy attack at range 1; only Ranged attacks at range 3"
            )
    return violations


def _combat_action_violations(source: str) -> list[str]:
    """Require an attack to be in the acting unit's range or paired with movement."""

    violations: list[str] = []
    actor_pattern = re.compile(
        r"\b(?:friendly\s+)?(Worker|Light|Heavy|Ranged|Base|Barracks)"
        r"(?:\s+(?:unit|attacker))?\s+is\s+idle\b|"
        r"\bidle\s+(?:friendly\s+)?(Worker|Light|Heavy|Ranged|Base|Barracks)\b",
        re.IGNORECASE,
    )
    response_actor_pattern = re.compile(
        r"\b(?:have|assign|send|direct)\s+(?:that\s+|the\s+|an?\s+|one\s+)?"
        r"(?:friendly\s+)?(Worker|Light|Heavy|Ranged|Base|Barracks)\b",
        re.IGNORECASE,
    )
    for clause in _clauses(source):
        if not _positive_action_clause(clause):
            continue
        attack = re.search(r"\battack(?:s|ed|ing)?\b", clause, re.IGNORECASE)
        if attack is None:
            continue

        response = re.search(
            r",\s*(?:have|assign|send|direct|keep)\b",
            clause,
            re.IGNORECASE,
        )
        action = clause[response.start():] if response else clause
        response_actor = response_actor_pattern.search(action)
        condition_actor = actor_pattern.search(clause)
        actor = (
            response_actor.group(1)
            if response_actor
            else next(
                (
                    group
                    for group in condition_actor.groups()
                    if group is not None
                ),
                None,
            )
            if condition_actor
            else None
        )
        moves_before_attack = re.search(
            r"\b(?:move|advance)(?:s|d|ing)?\b",
            action,
            re.IGNORECASE,
        )
        if moves_before_attack:
            melee_attacks_at_three = bool(
                actor
                and actor.casefold() in {"worker", "light", "heavy"}
                and re.search(
                    r"\battack\w*\b.{0,64}\b(?:within|inside|at)\s+"
                    r"(?:attack\s+)?(?:range|distance)\s*(?:of\s*)?3\b",
                    action,
                    re.IGNORECASE,
                )
            )
            if melee_attacks_at_three:
                violations.append(
                    f"{clause!r}: Worker, Light, and Heavy may move toward a distant target but may attack only after it enters range 1"
                )
            continue

        if actor and actor.casefold() in {"base", "barracks"}:
            violations.append(
                f"{clause!r}: Base and Barracks cannot attack"
            )
            continue

        positive_range_segments: list[str] = []
        for segment in clause.split(","):
            negative = re.search(r"\bno\s+enemy\b", segment, re.IGNORECASE)
            if negative is None:
                positive_range_segments.append(segment)
                continue
            positive_tail = re.search(
                r"\b(?:and|but)\s+(?:(?:at\s+least\s+one|an?)\s+)?"
                r"enemy\b.*",
                segment[negative.end():],
                re.IGNORECASE,
            )
            if positive_tail:
                positive_range_segments.append(positive_tail.group(0))
        range_context = ",".join(positive_range_segments)
        range_from_other_actor = re.search(
            r"\b(?:within|inside)\b.{0,36}\b(?:range|distance)\b.{0,24}\bof\s+"
            r"(?:an?\s+|the\s+|any\s+)?(?:friendly\s+)?(?:Base|Barracks)\b|"
            r"\b(?:within|inside)\s+(?:attack\s+)?range(?:\s+\d+)?\s+of\s+"
            r"(?:an?\s+|the\s+|any\s+)?(?:friendly\s+)?(?:Base|Barracks)\b",
            range_context,
            re.IGNORECASE,
        )
        if range_from_other_actor:
            violations.append(
                f"{clause!r}: attack range must be measured from the idle friendly unit that performs the attack, not from another unit or building"
            )
            continue

        range_evidence = re.search(
            r"\b(?:within|inside)\s+(?:(?:the|its|that\s+unit's)\s+)?"
            r"(?:attack\s+)?(?:range|distance)(?:\s*(?:of\s*)?[13])?\b|"
            r"\badjacent\b|\bdistance\s*(?:=|<=|≤|is)?\s*[13]\b|"
            r"\bdistance\s+to\b.{0,48}\b(?:is\s*)?(?:=|<=|≤)\s*[13]\b",
            range_context,
            re.IGNORECASE,
        )
        if range_evidence is None:
            violations.append(
                f"{clause!r}: an immediate attack requires the target to be within the acting unit's attack range; otherwise target and move toward it first"
            )
            continue

        friendly_idle = re.search(
            r"\bfriendly\b(?P<actors>.{0,64}?)\bis\s+idle\b",
            clause,
            re.IGNORECASE,
        )
        listed_actor_words = {
            word.casefold()
            for word in re.findall(
                r"\b(?:Worker|Light|Heavy|Ranged)\b",
                friendly_idle.group("actors") if friendly_idle else "",
                re.IGNORECASE,
            )
        }
        actor_words = (
            listed_actor_words
            if len(listed_actor_words) > 1
            else {actor.casefold()} if actor else listed_actor_words
        )
        range_three = re.search(
            r"\b(?:range|distance)\s*(?:of\s*)?3\b|"
            r"\b(?:within|inside)\s+(?:range|distance)\s*3\b|"
            r"\b(?:range|distance)\s+1\s+or\s+3\s*(?:\([^)]*\))?\s*(?:respectively)?\b|"
            r"\bdistance\s+to\b.{0,48}\b(?:is\s*)?(?:=|<=|≤)\s*3\b",
            range_context,
            re.IGNORECASE,
        )
        if range_three and actor_words.intersection({"worker", "light", "heavy"}):
            violations.append(
                f"{clause!r}: Worker, Light, and Heavy may attack only at range 1; split mixed actor rules or use each acting unit's own attack range"
            )
    return violations


def _target_prerequisite_violations(source: str) -> list[str]:
    """Require nearest-enemy selections to be guarded by that target's existence."""

    violations: list[str] = []
    target_kinds: tuple[tuple[re.Pattern[str], re.Pattern[str], str], ...] = (
        (
            re.compile(r"\benemy(?:-owned)?\s+Base(?:\s+position)?\b", re.IGNORECASE),
            re.compile(
                r"\benemy(?:-owned)?\s+Base\b.{0,40}\b(?:exists?|is\s+(?:within|adjacent))\b",
                re.IGNORECASE,
            ),
            "enemy Base",
        ),
        (
            re.compile(r"\benemy(?:-owned)?\s+Barracks\b", re.IGNORECASE),
            re.compile(
                r"\benemy(?:-owned)?\s+Barracks\b.{0,40}\b(?:exists?|is\s+(?:within|adjacent))\b",
                re.IGNORECASE,
            ),
            "enemy Barracks",
        ),
        (
            re.compile(r"\benemy(?:-owned)?\s+Workers?\b", re.IGNORECASE),
            re.compile(
                r"\benemy(?:-owned)?\s+Workers?\b.{0,40}\b(?:exists?|exist|is\s+(?:within|adjacent)|are\s+(?:within|adjacent))\b",
                re.IGNORECASE,
            ),
            "enemy Worker",
        ),
        (
            re.compile(
                r"\benemy(?:-owned)?\s+(?:units?\s+or\s+(?:buildings?|structures?)|"
                r"(?:buildings?|structures?)\s+or\s+units?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\benemy(?:-owned)?\s+(?:units?\s+or\s+(?:buildings?|structures?)|"
                r"(?:buildings?|structures?)\s+or\s+units?)\b.{0,40}\b(?:exists?|exist|"
                r"is\s+(?:within|adjacent)|are\s+(?:within|adjacent))\b",
                re.IGNORECASE,
            ),
            "enemy unit or building",
        ),
        (
            re.compile(r"\benemy(?:-owned)?\s+units?\b", re.IGNORECASE),
            re.compile(
                r"\benemy(?:-owned)?\s+units?\b.{0,40}\b(?:exists?|exist|is\s+(?:within|adjacent)|are\s+(?:within|adjacent))\b",
                re.IGNORECASE,
            ),
            "enemy unit",
        ),
        (
            re.compile(r"\benemy(?:-owned)?\s+(?:entity|entities)\b", re.IGNORECASE),
            re.compile(
                r"\benemy(?:-owned)?\s+(?:entity|entities)\b.{0,40}\b(?:exists?|exist|"
                r"is\s+(?:within|adjacent)|are\s+(?:within|adjacent))\b",
                re.IGNORECASE,
            ),
            "enemy entity",
        ),
    )
    for clause in _clauses(source):
        response = re.search(
            r",\s*(?:have|assign|send|direct|keep)\b|"
            r"^\s*(?:have|assign|send|direct|keep|target|attack|move|advance)\b",
            clause,
            re.IGNORECASE,
        )
        if response is None:
            continue
        condition = clause[: response.start()]
        action = clause[response.start():]
        if not re.search(
            r"\b(?:nearest|closest)\b.{0,32}\benemy(?:-owned)?\b|"
            r"\benemy(?:-owned)?\b.{0,32}\b(?:nearest|closest)\b",
            action,
            re.IGNORECASE,
        ):
            continue
        for target_pattern, existence_pattern, label in target_kinds:
            if target_pattern.search(action) is None:
                continue
            count_guarantees_target = bool(
                label == "enemy Worker"
                and re.search(
                    r"\b(?:count|number)\s+of\s+enemy\s+Workers?\b.{0,32}"
                    r"(?:>=|≥|at\s+least|is)\s*[1-9]\d*\b",
                    condition,
                    re.IGNORECASE,
                )
            )
            if existence_pattern.search(condition) is not None or count_guarantees_target or re.search(
                r"\bif\s+(?:(?:it|one|any)\s+)?exists?\b",
                action,
                re.IGNORECASE,
            ):
                break
            violations.append(
                f"{clause!r}: selecting the nearest {label} requires a current-state condition that such a target exists"
            )
            break
    return violations


def _ambiguous_rule_violations(source: str) -> list[str]:
    violations: list[str] = []
    vague = re.compile(
        r"\b(?:whenever resources allow|if possible|insufficient|"
        r"no other actions?(?: apply| are possible)?|"
        r"return to economy maintenance)\b",
        re.IGNORECASE,
    )
    for clause in _clauses(source):
        vague_match = vague.search(clause)
        if vague_match:
            violations.append(
                f"{vague_match.group(0)!r}: replace vague feasibility language with explicit current-state prerequisites and a legal fallback"
            )
        if re.search(r"\bdefend(?:ing)?\b", clause, re.IGNORECASE) and not re.search(
            r"\b(?:moves?|moving|attacks?|attacking|trains?|training|produces?|"
            r"producing|builds?|building|harvests?|harvesting|returns?|returning|"
            r"targets?|targeting|idle)\b",
            clause,
            re.IGNORECASE,
        ):
            violations.append(
                f"{clause!r}: defend is not an action unless the same rule resolves it to a legal move, attack, production, construction, economy, or idle response"
            )
        normalized = clause.replace("≥", ">=").replace("≤", "<=")
        lower = re.findall(
            r"\b(?:resources?|stockpile)\s*(?:(?:>=|>)\s*|"
            r"(?:is|are)\s+at least\s+)(\d+)\b",
            normalized,
            re.IGNORECASE,
        )
        upper = re.findall(
            r"\b(?:resources?|stockpile)\s*(?:(?:<=|<)\s*|"
            r"(?:is|are)\s+(?:at most|less than)\s+)(\d+)\b",
            normalized,
            re.IGNORECASE,
        )
        if lower and upper and max(map(int, lower)) >= min(map(int, upper)):
            violations.append(
                f"{clause!r}: the resource thresholds in this rule cannot be true at the same time"
            )
        if re.search(
            r"\bno enemy (?:entity|entities|units?|buildings?)"
            r"(?:\s+(?:or|and)\s+(?:enemy\s+)?(?:entity|entities|units?|buildings?))?\s+"
            r"(?:currently\s+)?(?:exists?|remain(?:s)?)\b"
            r"(?!\s+(?:within|at|in|adjacent))",
            clause,
            re.IGNORECASE,
        ) and re.search(
            r"\b(?:move|advance|attack|target)\b.{0,64}\benemy "
            r"(?:Base|Barracks|entity|entities|units?|buildings?)(?:\s+position)?\b",
            clause,
            re.IGNORECASE,
        ):
            violations.append(
                f"{clause!r}: the response targets an enemy entity that the same condition says does not exist"
            )
        if re.search(
            r"\bno enemy Base\s+(?:or|and)\s+(?:enemy\s+)?(?:units?|buildings?|Barracks)\s+"
            r"(?:currently\s+)?exists?\b(?!\s+(?:within|at|in|adjacent))",
            clause,
            re.IGNORECASE,
        ) and re.search(
            r"\b(?:move|advance|attack|target)\b.{0,64}\benemy "
            r"(?:Base|Barracks|units?|buildings?)\b",
            clause,
            re.IGNORECASE,
        ):
            violations.append(
                f"{clause!r}: the response targets an enemy entity that the same condition says does not exist"
            )
    return violations


def _structural_rule_violations(source: str) -> list[str]:
    """Reject oversized and internally contradictory policy-rule structures."""

    violations: list[str] = []
    numbered_rules = re.findall(
        r"(?:^|\n|\.\s+)(\d{1,2})\.\s+"
        r"(?=(?:If|When|For|Have|Keep|Leave|An?|Each|Every)\b)",
        source,
        re.IGNORECASE,
    )
    if len(numbered_rules) > 10:
        violations.append(
            f"the policy contains {len(numbered_rules)} numbered rules: a compliant policy may contain at most 10"
        )

    for clause in _clauses(source):
        for entity in (
            "Base",
            "Barracks",
            "Worker",
            "Light",
            "Heavy",
            "Ranged",
            "unit",
            "building",
        ):
            escaped = re.escape(entity)
            within = re.search(
                rf"\benemy\s+{escaped}\b.{{0,40}}?\b(?:within|inside)\s+"
                rf"(?:range|distance)\s*(\d+)\b",
                clause,
                re.IGNORECASE,
            )
            outside = re.search(
                rf"\benemy\s+{escaped}\b.{{0,40}}\b(?:outside|not\s+within)\s+"
                rf"(?:range|distance)\s*(\d+)\b",
                clause,
                re.IGNORECASE,
            )
            if within and outside and within.group(1) == outside.group(1):
                violations.append(
                    f"{clause!r}: the same enemy {entity} cannot be both within and "
                    f"outside range {within.group(1)}"
                )
                break
    return violations


def _state_action_contradictions(source: str) -> list[str]:
    violations: list[str] = []
    for clause in _clauses(source):
        if re.search(r"\bno Workers? (?:remain|exist)\b", clause, re.IGNORECASE) and re.search(
            r"\b(?:assign|have|send)\s+(?:an?\s+)?(?:idle\s+)?Worker\b|"
            r"\bWorker\s+(?:build|harvest|attack|move)|\bbuild\s+(?:an?\s+)?(?:Base|Barracks)",
            clause,
            re.IGNORECASE,
        ):
            violations.append(
                f"{clause!r}: a rule cannot act with a Worker when its condition says no Worker exists"
            )
        if re.search(r"\ball Workers?\b.{0,48}\breturn\s+to\b", clause, re.IGNORECASE) and not re.search(
            r"\b(?:carrying|carried|harvest|resource)\b", clause, re.IGNORECASE
        ):
            violations.append(
                f"{clause!r}: only a Worker carrying a resource can return it to a friendly Base"
            )
        if re.search(r"\bif fewer than\s+[2-9]\d*\s+Workers?\s+remain\b", clause, re.IGNORECASE) and re.search(
            r"\bbuild\s+(?:an?\s+)?(?:Base|Barracks)\b", clause, re.IGNORECASE
        ) and not re.search(r"\bat least one\s+(?:idle\s+)?Worker\b", clause, re.IGNORECASE):
            violations.append(
                f"{clause!r}: the count condition includes zero Workers, so building requires an explicit at-least-one idle Worker guard"
            )
    return violations
