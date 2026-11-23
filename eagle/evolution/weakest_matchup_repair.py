"""Design one framework-slot candidate from a completed self-play selection."""

from __future__ import annotations

import json
import random
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from eagle.candidate import Candidate, WEAKEST_MATCHUP_REPAIR_OPERATOR
from eagle.config import ExperimentConfig
from eagle.evaluation.determinism import derive_candidate_id, derive_seed
from eagle.generation.framework_slots import (
    canonical_json,
    load_framework_bundle,
    sample_initial_genome,
    validate_genome,
)
from eagle.llm import LLMCallLogger, LLMClient, generate_seeded
from eagle.operators.framework_coach import (
    framework_bundle_evidence,
    framework_selection_response_schema,
)
from eagle.opponent_pool import PoolMember
from eagle.prompts import load_prompt, render_prompt
from eagle.run_artifacts import atomic_json
from eagle.self_play import expand_self_play_slots, self_play_context_rows
from eagle.timing import Stopwatch


OPERATION = WEAKEST_MATCHUP_REPAIR_OPERATOR
SCHEMA_VERSION = "eagle-weakest-matchup-repair-v1"


def build_matchup_evidence(
    population: list[Candidate], snapshot: list[PoolMember], *, seed: int,
) -> dict[str, Any]:
    """Compare only the complete opponent matrices of the selected survivors."""
    if not population:
        raise ValueError("WMR requires a non-empty survivor population.")
    slots = {str(row["slot_id"]): row for row in self_play_context_rows(snapshot)}
    results = {}
    for candidate in population:
        rows = candidate.game_eval_result["opponent_results"]
        by_slot = {row["opponent_id"]: row for row in rows}
        if len(rows) != len(slots) or by_slot.keys() != slots.keys() or any(
            row["status"] != "completed"
            or row["completed_match_count"] <= 0
            or row["wins"] + row["draws"] + row["losses"] != row["completed_match_count"]
            for row in rows
        ):
            raise ValueError(f"WMR requires complete opponent counts for {candidate.id}.")
        results[candidate.id] = by_slot

    rates = {}
    summaries = []
    for slot_id in sorted(slots):
        wins = sum(rows[slot_id]["wins"] for rows in results.values())
        played = sum(rows[slot_id]["completed_match_count"] for rows in results.values())
        rates[slot_id] = Fraction(wins, played)
        summaries.append({
            **slots[slot_id], "wins": wins, "completed_match_count": played,
            "win_rate": float(rates[slot_id]),
        })
    lowest = min(rates.values())
    tied = [slot_id for slot_id, win_rate in rates.items() if win_rate == lowest]
    target_id = random.Random(seed).choice(tied)
    target = next(row for row in summaries if row["slot_id"] == target_id).copy()
    opponents = dict(zip(slots, expand_self_play_slots(snapshot), strict=True))
    opponent = opponents[target_id]
    if isinstance(opponent, Candidate):
        target.update(
            strategy_description=opponent.strategy_description,
            control_genome=opponent.control_genome,
        )
    else:
        target["opponent_name"] = opponent.display_name
    return {
        "target_opponent": target,
        "tied_lowest_slot_ids": tied,
        "opponent_rates": summaries,
        "survivors": [
            {
                "candidate_id": candidate.id,
                "strategy_description": candidate.strategy_description,
                "control_genome": candidate.control_genome,
                "matchup_result": results[candidate.id][target_id],
            }
            for candidate in population
        ],
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"WMR response contains duplicate key: {key}")
        result[key] = value
    return result


def propose_matchup_repair(
    *, population: list[Candidate], snapshot: list[PoolMember], config: ExperimentConfig,
    generation: int, run_dir: Path, artifact_dir: Path, client: LLMClient, mock: bool,
) -> Candidate | None:
    """Persist the proposal evidence and return a fresh candidate only for a legal design."""
    seed = derive_seed(config.random_seed, "evolution", generation, OPERATION)
    evidence = build_matchup_evidence(population, snapshot, seed=seed)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(artifact_dir / "evidence.json", {"seed": seed, **evidence})
    digest = config.framework_bundle_sha256
    assert digest is not None
    bundle = load_framework_bundle(config.framework_bundle_path, expected_sha256=digest)
    candidate_id = derive_candidate_id(config.random_seed, generation=generation, index=0, role=OPERATION)
    if mock:
        description = "Mock matchup repair strategy."
        genome = sample_initial_genome(bundle, random_seed=seed)
    else:
        schema = framework_selection_response_schema(bundle, digest)
        properties = schema["properties"]
        properties["schema_version"]["enum"] = [SCHEMA_VERSION]
        for key in ("matchup_reflection", "strategy_description"):
            properties[key] = {"type": "string"}
            schema["required"].append(key)
        backend = client.prompt_backend(
            operation=OPERATION, response_schema=schema,
            response_schema_name="eagle_weakest_matchup_repair", max_prompt_chars=None,
        )
        logger = LLMCallLogger(run_dir / "llm_logs", run_id=run_dir.name, timing_path=run_dir / "timing.jsonl")
        variables = {
            "gameplay_contract": load_prompt("microrts_gameplay_contract"),
            "framework_bundle": canonical_json(framework_bundle_evidence(bundle)),
            "matchup_evidence": canonical_json(evidence),
            "response_schema": canonical_json(schema),
        }
        error = None
        for attempt in range(1, config.mutation_max_attempts + 1):
            prompt = render_prompt(OPERATION, {
                **variables, "previous_error": error if error is not None else "None (first attempt).",
            })
            attempt_dir = artifact_dir / "attempts" / f"attempt_{attempt:03d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            (attempt_dir / "request.txt").write_text(prompt, encoding="utf-8")
            sampling_seed = derive_seed(seed, "proposal", attempt) % 2**31
            span = Stopwatch.start()
            error = None
            try:
                raw = generate_seeded(backend, prompt, sampling_seed)
                (attempt_dir / "response_raw.txt").write_text(raw, encoding="utf-8")
                payload = json.loads(raw, object_pairs_hook=_unique_object)
                if not isinstance(payload, dict) or payload.keys() != properties.keys():
                    raise ValueError("WMR response must contain exactly the required fields.")
                if payload["schema_version"] != SCHEMA_VERSION or payload["framework_bundle_sha256"] != digest:
                    raise ValueError("WMR response schema version or frozen bundle hash mismatch.")
                for key in ("matchup_reflection", "strategy_description"):
                    if not isinstance(payload[key], str) or not payload[key].strip():
                        raise ValueError(f"WMR response requires non-empty {key}.")
                description = payload["strategy_description"].strip()
                genome = validate_genome(bundle, payload["control_genome"])
            except (ValueError, TypeError, RuntimeError, OSError) as exc:
                error = str(exc)
            timing = span.finish(status="failed" if error is not None else "success", error=error)
            endpoint = client.selected_endpoint.base_url
            atomic_json(attempt_dir / "result.json", {
                **timing, "attempt": attempt, "model": backend.model, "backend": config.execution_mode,
                "endpoint": endpoint, "sampling_seed": sampling_seed,
            })
            logger.write_timing_event(
                request_correlation_id=f"{run_dir.name}:{OPERATION}:{uuid4().hex}",
                stage=OPERATION, status=timing["status"], model=backend.model,
                candidate_id=candidate_id, generation=generation, started_at=timing["started_at"],
                finished_at=timing["finished_at"], duration_seconds=timing["duration_seconds"],
                metadata={"operation_type": OPERATION, "endpoint": endpoint,
                          "transport_attempt": attempt, "sampling_seed": sampling_seed},
            )
            if error is None:
                break
        else:
            return None

    target = evidence["target_opponent"]
    return Candidate(
        id=candidate_id, generation=generation, operator=OPERATION,
        java_materialization_mode="framework_slots", java_compiler_version=config.java_compiler_version,
        framework_bundle_sha256=digest, control_genome=genome, generation_prompt="",
        strategy_description=description,
        metadata={OPERATION: {
            "target_opponent": target,
            "evidence_candidate_ids": [candidate.id for candidate in population],
            "evidence_path": (artifact_dir / "evidence.json").relative_to(run_dir).as_posix(),
        }},
    )
