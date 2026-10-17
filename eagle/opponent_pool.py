"""Bounded tournament-managed self-play opponent pool."""

from __future__ import annotations

import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeAlias

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.determinism import derive_seed
from eagle.evaluation.match_matrix import MatchSpecification, MatrixOpponent, build_match_matrix, canonical_evaluation_maps
from eagle.opponents import OpponentSpec, SEARCH_OPPONENT_REGISTRY
from eagle.run_artifacts import atomic_json, load_candidate
from eagle.timing import Stopwatch, append_event


PoolMember: TypeAlias = Candidate | OpponentSpec

PROTECTED_OPPONENT_IDS = ("allinbot", "mayari", "coac", "tma")
POOL_SCHEMA_VERSION = "eagle-opponent-pool-v1"
POOL_PATH = Path("archives/self_play_opponents.json")
TOURNAMENT_SCHEMA_VERSION = "eagle-opponent-pool-tournament-v1"
TOURNAMENT_ROOT = Path("archives/opponent_pool_tournaments")

_BUILTINS = {item.opponent_id: item for item in SEARCH_OPPONENT_REGISTRY}


def initial_pool() -> list[PoolMember]:
    return list(SEARCH_OPPONENT_REGISTRY)


def member_identity(member: PoolMember) -> str:
    if isinstance(member, OpponentSpec):
        return f"builtin:{member.opponent_id}"
    return f"candidate:{member.id}"


def member_reference(member: PoolMember) -> dict[str, object]:
    if isinstance(member, OpponentSpec):
        return {
            "kind": "builtin",
            "opponent_id": member.opponent_id,
            "protected": member.opponent_id in PROTECTED_OPPONENT_IDS,
        }
    reference: dict[str, object] = {
        "kind": "candidate",
        "candidate_id": member.id,
        "generation": member.generation,
        "generated_java_sha256": _source_hash(member),
    }
    summary = _semantic_summary(member)
    if summary is not None:
        reference["semantic_signature"] = summary
    return reference


def resolve_member_reference(run_dir: Path, reference: dict[str, object]) -> PoolMember:
    if not isinstance(reference, dict):
        raise ValueError("Opponent-pool member reference must be an object.")
    kind = reference.get("kind")
    if kind == "builtin":
        if set(reference) != {"kind", "opponent_id", "protected"}:
            raise ValueError("Opponent-pool builtin reference has invalid fields.")
        opponent_id = reference.get("opponent_id")
        if not isinstance(opponent_id, str) or opponent_id not in _BUILTINS:
            raise ValueError(f"Unknown opponent-pool builtin: {opponent_id!r}")
        protected = opponent_id in PROTECTED_OPPONENT_IDS
        if type(reference.get("protected")) is not bool or reference["protected"] is not protected:
            raise ValueError(f"Opponent-pool protected flag mismatch: {opponent_id}")
        return _BUILTINS[opponent_id]
    if kind != "candidate":
        raise ValueError(f"Unknown opponent-pool member kind: {kind!r}")
    allowed = {
        "kind", "candidate_id", "generation", "generated_java_sha256",
        "semantic_signature",
    }
    if not set(reference).issubset(allowed) or not {
        "kind", "candidate_id", "generation", "generated_java_sha256",
    }.issubset(reference):
        raise ValueError("Opponent-pool candidate reference has invalid fields.")
    candidate_id = reference.get("candidate_id")
    if not isinstance(candidate_id, str):
        raise ValueError("Opponent-pool candidate_id must be a string.")
    _validate_candidate_id(candidate_id)
    candidate = load_candidate(run_dir, candidate_id)
    if type(reference.get("generation")) is not int or reference["generation"] != candidate.generation:
        raise ValueError(f"Opponent-pool candidate generation mismatch: {candidate_id}")
    expected_hash = reference.get("generated_java_sha256")
    if not isinstance(expected_hash, str) or expected_hash != _source_hash(candidate):
        raise ValueError(f"Opponent-pool candidate Java hash mismatch: {candidate_id}")
    if not _is_ready(candidate):
        raise ValueError(f"Opponent-pool candidate is not runnable: {candidate_id}")
    if "semantic_signature" in reference:
        summary = reference["semantic_signature"]
        if not isinstance(summary, dict) or summary != _semantic_summary(candidate):
            raise ValueError(f"Opponent-pool candidate semantic signature mismatch: {candidate_id}")
    return candidate


def load_pool(run_dir: Path, *, capacity: int) -> list[PoolMember]:
    _validate_capacity(capacity)
    path = run_dir / POOL_PATH
    if not path.is_file():
        return initial_pool()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Opponent pool is missing or invalid: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "capacity", "protected_opponent_ids", "opponents",
    }:
        raise ValueError(f"Opponent pool has invalid top-level fields: {path}")
    if payload.get("schema_version") != POOL_SCHEMA_VERSION:
        raise ValueError(f"Unsupported opponent-pool schema: {path}")
    if type(payload.get("capacity")) is not int or payload["capacity"] != capacity:
        raise ValueError("Opponent-pool capacity does not match the resolved run config.")
    if payload.get("protected_opponent_ids") != list(PROTECTED_OPPONENT_IDS):
        raise ValueError("Opponent-pool protected roster does not match the protocol.")
    references = payload.get("opponents")
    if not isinstance(references, list) or not 10 <= len(references) <= capacity:
        raise ValueError("Opponent pool must contain between 10 and capacity members.")
    members = [resolve_member_reference(run_dir, item) for item in references]
    identities = [member_identity(member) for member in members]
    if len(identities) != len(set(identities)):
        raise ValueError("Opponent pool contains duplicate member identities.")
    protected = [
        member.opponent_id
        for member in members
        if isinstance(member, OpponentSpec) and member.opponent_id in PROTECTED_OPPONENT_IDS
    ]
    if sorted(protected) != sorted(PROTECTED_OPPONENT_IDS):
        raise ValueError("Opponent pool must contain every protected builtin exactly once.")
    return members


def select_pool_opponents(
    run_dir: Path,
    *,
    generation: int,
    config: ExperimentConfig,
) -> list[PoolMember]:
    pool = load_pool(run_dir, capacity=config.self_play_opponent_library_capacity)
    protected = [_BUILTINS[opponent_id] for opponent_id in PROTECTED_OPPONENT_IDS]
    eligible = sorted(
        (member for member in pool if member_identity(member) not in {
            member_identity(item) for item in protected
        }),
        key=member_identity,
    )
    if len(eligible) < 6:
        raise ValueError("Opponent pool requires at least six non-protected members.")
    rng = random.Random(derive_seed(
        config.random_seed, "opponent_pool", "snapshot", generation
    ))
    return [*protected, *rng.sample(eligible, 6)]


def update_pool(
    run_dir: Path,
    candidates: list[Candidate],
    *,
    generation: int,
    config: ExperimentConfig,
    mock: bool,
) -> None:
    capacity = config.self_play_opponent_library_capacity
    pool = load_pool(run_dir, capacity=capacity)
    for entrant in sorted(candidates, key=lambda item: item.id):
        if not _is_ready(entrant):
            continue
        _validate_candidate_id(entrant.id)
        if _is_duplicate(pool, entrant):
            continue
        if len(pool) < capacity:
            pool.append(entrant)
            continue
        eligible = sorted(
            (
                member for member in pool
                if not (
                    isinstance(member, OpponentSpec)
                    and member.opponent_id in PROTECTED_OPPONENT_IDS
                )
            ),
            key=member_identity,
        )
        if not eligible:
            raise ValueError("Opponent pool has no replaceable incumbent.")
        defender = random.Random(derive_seed(
            config.random_seed,
            "opponent_pool",
            "defender",
            generation,
            entrant.id,
        )).choice(eligible)
        if _run_tournament(
            run_dir,
            entrant=entrant,
            defender=defender,
            generation=generation,
            config=config,
            mock=mock,
        ):
            pool[pool.index(defender)] = entrant
    atomic_json(run_dir / POOL_PATH, {
        "schema_version": POOL_SCHEMA_VERSION,
        "capacity": capacity,
        "protected_opponent_ids": list(PROTECTED_OPPONENT_IDS),
        "opponents": [member_reference(member) for member in pool],
    })


def _run_tournament(
    run_dir: Path,
    *,
    entrant: Candidate,
    defender: PoolMember,
    generation: int,
    config: ExperimentConfig,
    mock: bool,
) -> bool:
    from eagle.evaluation.matches import scoring_config_from_experiment
    from eagle.evaluation.opponents import (
        _opponent_display_name,
        _prepare_self_play_class,
        _resolved_static_evaluation_opponents,
    )
    from eagle.evaluation.runtime_evaluation import (
        MatchResult,
        hash_class_directory,
        hash_file,
        run_microrts_match,
    )

    span = Stopwatch.start()
    duel_dir = run_dir / TOURNAMENT_ROOT / f"generation_{generation:04d}" / entrant.id
    duel_dir.mkdir(parents=True, exist_ok=True)
    results: list[MatchResult] = []
    error: str | None = None
    interrupted = False
    entrant_classes = run_dir / "classes" / entrant.id
    entrant_source_hash: str | None = None
    entrant_class_hash: str | None = None
    defender_source_hash: str | None = None
    defender_class_hash: str | None = None
    try:
        entrant_source = _candidate_source_path(run_dir, entrant)
        entrant_source_hash = hash_file(entrant_source)
        if not mock:
            _require_class_directory(entrant_classes, entrant.id)
        entrant_class_hash = hash_class_directory(entrant_classes)
        if isinstance(defender, Candidate):
            defender_source = _candidate_source_path(run_dir, defender)
            defender_source_hash = hash_file(defender_source)
            defender_original_classes = run_dir / "classes" / defender.id
            if not mock:
                _require_class_directory(defender_original_classes, defender.id)
            defender_class, defender_classes = _prepare_self_play_class(
                defender,
                source=defender.generated_java,
                classes_dir=run_dir / "classes",
                config=config,
                mock=mock,
            )
            defender_class_hash = hash_class_directory(defender_classes)
            defender_classpath = (defender_classes,)
            defender_name = defender.id
        else:
            resolved = {
                item.opponent_id: item
                for item in _resolved_static_evaluation_opponents(
                    config,
                    mock=mock,
                    classes_dir=run_dir / "classes",
                    opponent_ids=(defender.opponent_id,),
                )
            }
            opponent = resolved.get(defender.opponent_id)
            if opponent is None:
                raise ValueError(f"Tournament defender is unavailable: {defender.opponent_id}")
            defender_class = opponent.class_name
            defender_classpath = opponent.classpath_entries
            defender_name = opponent.display_name or _opponent_display_name(defender.opponent_id)
            relative_source = Path(*defender_class.split(".")).with_suffix(".java")
            source_path = config.microrts_dir.resolve() / "src" / relative_source
            if source_path.is_file():
                defender_source_hash = hash_file(source_path)
            relative_class = Path(*defender_class.split(".")).with_suffix(".class")
            for class_root in (
                entrant_classes,
                *defender_classpath,
                config.microrts_dir.resolve() / "bin",
            ):
                class_path = class_root / relative_class
                if class_path.is_file():
                    defender_class_hash = hash_file(class_path)
                    break
        specifications = build_match_matrix(
            (MatrixOpponent(member_identity(defender)),),
            canonical_evaluation_maps(
                config.evaluation_maps,
                tick_limits=config.resolved_evaluation_map_tick_limits,
            ),
            rounds_per_map=config.rounds_per_map,
            swap_player_sides=config.swap_player_sides,
        )
        scoring = scoring_config_from_experiment(config)

        def run(specification: MatchSpecification) -> MatchResult:
            match_dir = duel_dir / f"match_{specification.match_index:02d}"
            seed = derive_seed(
                config.random_seed,
                "opponent_pool",
                "match",
                generation,
                entrant.id,
                member_identity(defender),
                specification.map_id,
                specification.round_index,
                specification.candidate_player,
                specification.match_index,
            )
            try:
                return run_microrts_match(
                    microrts_dir=config.microrts_dir,
                    classes_dir=entrant_classes,
                    agent_class="ai.generated.CandidateAgent",
                    opponent=defender_class,
                    opponent_id=member_identity(defender),
                    opponent_name=defender_name,
                    tick_limit=specification.tick_limit,
                    match_index=specification.match_index,
                    match_output_dir=match_dir,
                    scoring_config=scoring,
                    mock=mock,
                    mock_score=1.0,
                    timeout_seconds=config.match_timeout_seconds,
                    map_path=specification.map_path,
                    candidate_id=entrant.id,
                    generation=generation,
                    candidate_player=specification.candidate_player,
                    generation_index=generation,
                    source_hash=entrant_source_hash,
                    class_hash=entrant_class_hash,
                    extra_classpath_entries=defender_classpath,
                    artifact_mode=config.match_artifact_mode,
                    map_id=specification.map_id,
                    round_index=specification.round_index,
                    opponent_source_generation=(
                        defender.generation if isinstance(defender, Candidate) else None
                    ),
                    opponent_source_candidate_id=(
                        defender.id if isinstance(defender, Candidate) else None
                    ),
                    match_seed=seed,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                failure = MatchResult(
                    ok=False,
                    score=0.0,
                    command=[],
                    match_index=specification.match_index,
                    match_seed=seed,
                    candidate_id=entrant.id,
                    generation=generation,
                    candidate_player=specification.candidate_player,
                    opponent=defender_class,
                    opponent_id=member_identity(defender),
                    opponent_name=defender_name,
                    map_path=specification.map_path,
                    map_id=specification.map_id,
                    round_index=specification.round_index,
                    max_cycles=specification.tick_limit,
                    source_hash=entrant_source_hash,
                    class_hash=entrant_class_hash,
                    status="failed",
                    failure_category="opponent_pool_tournament_failure",
                    failure_reason=str(exc),
                    timeout_seconds=config.match_timeout_seconds,
                )
                atomic_json(match_dir / "result.json", failure.to_json_dict())
                return failure

        with ThreadPoolExecutor(
            max_workers=min(config.match_workers, len(specifications)),
            thread_name_prefix="eagle-opponent-pool",
        ) as executor:
            results.extend(executor.map(run, specifications))
    except KeyboardInterrupt:
        error = "opponent-pool tournament interrupted"
        interrupted = True
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        error = str(exc)

    wins = sum(result.ok and result.winner == result.candidate_player for result in results)
    losses = sum(result.ok and result.winner == 1 - result.candidate_player for result in results)
    draws = sum(result.ok and result.winner not in {0, 1} for result in results)
    errors = len(results) - wins - losses - draws
    complete = error is None and len(results) == 18 and errors == 0
    replaced = complete and wins > losses
    status = "completed" if complete else "interrupted" if interrupted else "failed"
    timing = span.finish(
        status="success" if complete else "interrupted" if interrupted else "failed",
        error=error,
    )
    summary = {
        "schema_version": TOURNAMENT_SCHEMA_VERSION,
        "generation": generation,
        "entrant": member_reference(entrant),
        "defender": member_reference(defender),
        "entrant_source_sha256": entrant_source_hash,
        "entrant_classes_sha256": entrant_class_hash,
        "defender_source_sha256": defender_source_hash,
        "defender_classes_sha256": defender_class_hash,
        "status": status,
        "error": error,
        "expected_matches": 18,
        "attempted_matches": len(results),
        "completed_matches": wins + losses + draws,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "errors": errors,
        "decision": "replace" if replaced else "retain",
        "retained_identity": member_identity(entrant if replaced else defender),
        "replaced_identity": member_identity(defender) if replaced else None,
        "matches": [
            {
                "match_index": result.match_index,
                "artifact_path": f"match_{result.match_index:02d}",
                "match_seed": result.match_seed,
                "candidate_player": result.candidate_player,
                "map_id": result.map_id,
                "round_index": result.round_index,
                "status": result.status,
                "ok": result.ok,
                "winner": result.winner,
                "source_hash": result.source_hash,
                "class_hash": result.class_hash,
                "failure_category": result.failure_category,
                "failure_reason": result.failure_reason,
            }
            for result in results
        ],
        "timing": timing,
    }
    atomic_json(duel_dir / "result.json", summary)
    append_event(run_dir / "timing.jsonl", {
        "event": "opponent_pool_tournament",
        "run_id": run_dir.name,
        "generation": generation,
        "entrant_id": entrant.id,
        "defender_identity": member_identity(defender),
        "status": summary["status"],
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "errors": errors,
        "decision": summary["decision"],
        **timing,
    })
    if interrupted:
        raise KeyboardInterrupt
    if error is not None:
        raise RuntimeError(error)
    return replaced


def _validate_capacity(capacity: int) -> None:
    if type(capacity) is not int or capacity < 10:
        raise ValueError("Opponent-pool capacity must be an integer of at least 10.")


def _validate_candidate_id(candidate_id: str) -> None:
    if (
        not candidate_id
        or candidate_id in {".", ".."}
        or any(character in candidate_id for character in ("/", "\\", ":", "\x00"))
        or Path(candidate_id).name != candidate_id
    ):
        raise ValueError(f"Invalid candidate identifier: {candidate_id!r}")


def _source_hash(candidate: Candidate) -> str:
    return hashlib.sha256(candidate.generated_java.encode("utf-8")).hexdigest()


def _semantic_summary(candidate: Candidate) -> dict[str, object] | None:
    from eagle.self_play import _library_semantic_summary

    return _library_semantic_summary(candidate)


def _is_ready(candidate: Candidate) -> bool:
    from eagle.self_play import _is_self_play_opponent_ready

    if not _is_self_play_opponent_ready(candidate):
        return False
    game = candidate.game_eval_result or {}
    expected = game.get("expected_match_count")
    completed = game.get("completed_match_count")
    return (
        type(expected) is int
        and type(completed) is int
        and expected > 0
        and completed == expected
    )


def _is_duplicate(pool: list[PoolMember], entrant: Candidate) -> bool:
    identities = {member_identity(member) for member in pool}
    if member_identity(entrant) in identities:
        return True
    hashes = {
        _source_hash(member)
        for member in pool
        if isinstance(member, Candidate)
    }
    if _source_hash(entrant) in hashes:
        return True
    summary = _semantic_summary(entrant)
    if summary is None:
        return False
    from eagle.evaluation.semantic_signature import SemanticLibrary

    library = SemanticLibrary()
    for member in pool:
        if isinstance(member, Candidate):
            stored = _semantic_summary(member)
            if stored is not None:
                library.add(member.id, stored)
    return bool(library.find_equivalent(summary))


def _candidate_source_path(run_dir: Path, candidate: Candidate) -> Path:
    canonical = run_dir / "candidates" / candidate.id / "phenotype" / "CandidateAgent.java"
    if canonical.is_file():
        return canonical
    configured = Path(candidate.generated_java_path) if candidate.generated_java_path else None
    if configured is None or not configured.is_file():
        raise ValueError(f"Candidate source is unavailable: {candidate.id}")
    return configured


def _require_class_directory(path: Path, candidate_id: str) -> None:
    if not path.is_dir() or not any(path.rglob("*.class")):
        raise ValueError(f"Candidate classes are unavailable: {candidate_id}")
