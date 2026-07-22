"""Gameplay-only orchestration for completed-run champion final tests."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.microrts_runner import (
    IntegrationResult,
    MatchResult,
    hash_class_directory,
    hash_file,
    integrate_microrts_agent,
    run_microrts_match,
)

from . import FINAL_TEST_SCHEMA_VERSION
from .aggregation import aggregate_final_test_results
from .artifacts import (
    append_jsonl,
    copy_candidate_source,
    copy_input_config,
    create_final_test_directory,
    write_json,
)
from .config import FinalTestConfig
from .opponents import (
    ResolvedOpponent,
    compile_opponent_probe,
    load_resolved_opponents,
    verify_resolved_opponent,
)
from .schedule import FinalTestMatch, build_schedule, exact_match_count
from .selection import SelectedCandidate, select_final_test_candidates


CompileFunction = Callable[..., CompileResult]
IntegrationFunction = Callable[..., IntegrationResult]
MatchFunction = Callable[..., MatchResult]


@dataclass(frozen=True)
class FinalTestOutcome:
    final_test_dir: Path
    success: bool
    expected_matches: int
    completed_matches: int


@dataclass(frozen=True)
class CompiledCandidate:
    selected: SelectedCandidate
    source_path: Path
    classes_dir: Path
    source_hash: str
    class_hash: str | None
    compile_duration_seconds: float
    compile_result: CompileResult
    integration_result: IntegrationResult | None

    @property
    def ready(self) -> bool:
        return bool(
            self.compile_result.ok
            and self.class_hash
            and self.integration_result is not None
            and self.integration_result.ok
        )


def execute_final_test(
    *,
    run_dir: Path,
    config_path: Path,
    repository_root: Path,
    selector: str | None = None,
    candidate_id: str | None = None,
    final_test_id: str | None = None,
    smoke: bool = False,
    compile_function: CompileFunction | None = None,
    integration_function: IntegrationFunction | None = None,
    match_function: MatchFunction | None = None,
    verify_opponents: bool = True,
) -> FinalTestOutcome:
    """Run a final test without importing or invoking any evolutionary/LLM operator."""

    started_at = _utc_now()
    started = time.monotonic()
    repository_root = repository_root.resolve()
    run_dir = run_dir.resolve()
    config = FinalTestConfig.from_file(config_path.resolve(), repository_root=repository_root)
    if smoke:
        config = config.smoke_subset()
    selection = select_final_test_candidates(
        run_dir,
        selector=selector,
        candidate_id=candidate_id,
    )
    opponents = load_resolved_opponents(
        config.resolved_opponents_manifest,
        expected_ids=config.opponent_ids,
    )
    active_id = final_test_id or _default_final_test_id(selection.selector, smoke=smoke)
    final_test_dir = create_final_test_directory(run_dir, config.output_directory, active_id)
    copy_input_config(config_path, final_test_dir)
    write_json(final_test_dir / "selection.json", selection.to_json_dict(run_dir))
    write_json(
        final_test_dir / "opponents.json",
        {
            "schema_version": "eagle-final-test-opponents-snapshot-v1",
            "opponents": [opponents[item].to_json_dict() for item in config.opponent_ids],
        },
    )
    schedule = build_schedule(selection.candidates, config)
    resolved_config = config.to_resolved_dict(formal=not smoke)
    resolved_config.update(
        {
            "run_id": run_dir.name,
            "final_test_id": active_id,
            "selector": selection.selector,
            "selected_candidate_ids": [item.candidate_id for item in selection.candidates],
            "expected_match_count": len(schedule),
            "git_commit": selection.git_commit,
            "llm_calls": 0,
            "evolutionary_operator_calls": 0,
        }
    )
    write_json(final_test_dir / "resolved_config.json", resolved_config)

    if verify_opponents:
        probe_classes = compile_opponent_probe(
            final_test_dir / "opponent_probe",
            config.microrts_dir,
        )
        for opponent_id in config.opponent_ids:
            verify_resolved_opponent(
                opponents[opponent_id],
                repository_root=repository_root,
                microrts_dir=config.microrts_dir,
                probe_classes=probe_classes,
            )

    compile_call = compile_function or compile_generated_agent
    integration_call = integration_function or integrate_microrts_agent
    match_call = match_function or run_microrts_match
    compiled = {
        candidate.candidate_id: _compile_candidate(
            candidate,
            final_test_dir=final_test_dir,
            config=config,
            compile_function=compile_call,
            integration_function=integration_call,
        )
        for candidate in selection.candidates
    }

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for match in schedule:
        candidate = compiled[match.candidate_id]
        opponent = opponents[match.opponent_id]
        if candidate.ready:
            record = _run_one_match(
                match,
                candidate=candidate,
                opponent=opponent,
                config=config,
                final_test_dir=final_test_dir,
                repository_root=repository_root,
                match_function=match_call,
            )
        else:
            record = _blocked_match_record(
                match,
                candidate=candidate,
                opponent=opponent,
                final_test_dir=final_test_dir,
            )
        records.append(record)
        append_jsonl(final_test_dir / "results.jsonl", record)
        if record["status"] != "success":
            failures.append(record)

    per_candidate_expected = {
        item.candidate_id: exact_match_count(1, config) for item in selection.candidates
    }
    summary = aggregate_final_test_results(records, expected_by_candidate=per_candidate_expected)
    summary.update(
        {
            "final_test_schema_version": FINAL_TEST_SCHEMA_VERSION,
            "run_id": run_dir.name,
            "final_test_id": active_id,
            "selector": selection.selector,
            "tested_candidate_ids": [item.candidate_id for item in selection.candidates],
            "formal_final_test": not smoke,
            "status": "complete" if summary["formal_test_complete"] else "incomplete",
            "artifact_paths": {
                "selection": "selection.json",
                "opponents": "opponents.json",
                "results": "results.jsonl",
                "failures": "failures.json",
                "timing": "timing.json",
            },
        }
    )
    write_json(final_test_dir / "summary.json", summary)
    write_json(
        final_test_dir / "failures.json",
        {
            "final_test_schema_version": FINAL_TEST_SCHEMA_VERSION,
            "failure_count": len(failures),
            "failures": failures,
        },
    )
    finished_at = _utc_now()
    write_json(
        final_test_dir / "timing.json",
        {
            "final_test_schema_version": FINAL_TEST_SCHEMA_VERSION,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": max(0.0, time.monotonic() - started),
            "candidate_compilation_seconds": {
                item.candidate_id: item.compile_duration_seconds
                for item in compiled.values()
            },
            "match_durations_seconds": [float(item.get("duration_seconds") or 0.0) for item in records],
        },
    )
    completed_count = sum(item["status"] == "success" for item in records)
    return FinalTestOutcome(
        final_test_dir=final_test_dir,
        success=completed_count == len(schedule),
        expected_matches=len(schedule),
        completed_matches=completed_count,
    )


def _compile_candidate(
    candidate: SelectedCandidate,
    *,
    final_test_dir: Path,
    config: FinalTestConfig,
    compile_function: CompileFunction,
    integration_function: IntegrationFunction,
) -> CompiledCandidate:
    copied_source = copy_candidate_source(candidate.source_path, final_test_dir, candidate.candidate_id)
    canonical_hash = hash_file(candidate.source_path)
    copied_hash = hash_file(copied_source)
    if copied_hash != canonical_hash:
        raise ValueError(f"Copied final-test source hash mismatch for {candidate.candidate_id}.")
    classes_dir = final_test_dir / "candidate_classes" / candidate.candidate_id / "classes"
    compile_started = time.monotonic()
    compile_result = compile_function(
        copied_source,
        microrts_dir=config.microrts_dir,
        output_dir=classes_dir,
        mock=False,
    )
    compile_duration = max(0.0, time.monotonic() - compile_started)
    compilation_dir = final_test_dir / "candidate_classes" / candidate.candidate_id / "compilation"
    write_json(compilation_dir / "result.json", compile_result.to_json_dict())
    (compilation_dir / "command.txt").write_text(" ".join(compile_result.command), encoding="utf-8")
    (compilation_dir / "stdout.txt").write_text(compile_result.stdout, encoding="utf-8")
    (compilation_dir / "stderr.txt").write_text(compile_result.stderr, encoding="utf-8")
    class_hash = hash_class_directory(classes_dir) if compile_result.ok else None
    integration: IntegrationResult | None = None
    if compile_result.ok:
        integration = integration_function(
            microrts_dir=config.microrts_dir,
            classes_dir=classes_dir,
            agent_class="ai.generated.CandidateAgent",
            integration_artifacts_dir=(
                final_test_dir / "candidate_classes" / candidate.candidate_id / "integration"
            ),
            mock=False,
        )
    write_json(
        final_test_dir / "candidate_sources" / candidate.candidate_id / "identity.json",
        {
            "candidate_id": candidate.candidate_id,
            "canonical_source_path": str(candidate.source_path),
            "copied_source_path": str(copied_source),
            "candidate_source_sha256": canonical_hash,
            "candidate_class_sha256": class_hash,
            "compile_count": 1,
            "integration": None if integration is None else integration.to_json_dict(),
        },
    )
    return CompiledCandidate(
        selected=candidate,
        source_path=copied_source,
        classes_dir=classes_dir,
        source_hash=canonical_hash,
        class_hash=class_hash,
        compile_duration_seconds=compile_duration,
        compile_result=compile_result,
        integration_result=integration,
    )


def _run_one_match(
    match: FinalTestMatch,
    *,
    candidate: CompiledCandidate,
    opponent: ResolvedOpponent,
    config: FinalTestConfig,
    final_test_dir: Path,
    repository_root: Path,
    match_function: MatchFunction,
) -> dict[str, Any]:
    output_dir = final_test_dir / match.artifact_relative_path
    jar_path = (repository_root / opponent.jar_path).resolve()
    try:
        result = match_function(
            microrts_dir=config.microrts_dir,
            classes_dir=candidate.classes_dir,
            agent_class="ai.generated.CandidateAgent",
            opponent=opponent.class_name,
            tick_limit=match.max_cycles,
            match_index=match.match_index,
            match_artifacts_dir=output_dir.parent,
            mock=False,
            seed=match.seed,
            timeout_seconds=config.subprocess_timeout_seconds,
            map_path=match.map_path,
            candidate_id=match.candidate_id,
            source_hash=candidate.source_hash,
            class_hash=candidate.class_hash,
            candidate_player=match.candidate_player,
            extra_classpath_entries=(jar_path,),
            match_output_dir=output_dir,
        )
        record = result.to_json_dict()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        record = _exception_record(match, str(exc))
    record.update(_final_metadata(match, candidate=candidate, opponent=opponent))
    write_json(output_dir / "result.json", record)
    return record


def _blocked_match_record(
    match: FinalTestMatch,
    *,
    candidate: CompiledCandidate,
    opponent: ResolvedOpponent,
    final_test_dir: Path,
) -> dict[str, Any]:
    if not candidate.compile_result.ok:
        category = "candidate_compilation_failure"
        reason = candidate.compile_result.stderr or "Final-test candidate compilation failed."
    else:
        category = "candidate_integration_failure"
        reason = (
            "Final-test candidate integration failed."
            if candidate.integration_result is None
            else candidate.integration_result.failure_reason or "Final-test candidate integration failed."
        )
    record = _exception_record(match, reason, category=category)
    record.update(_final_metadata(match, candidate=candidate, opponent=opponent))
    output_dir = final_test_dir / match.artifact_relative_path
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stdout.txt").write_text("", encoding="utf-8")
    (output_dir / "stderr.txt").write_text(reason, encoding="utf-8")
    write_json(output_dir / "timing.json", record["timing"])
    write_json(output_dir / "result.json", record)
    return record


def _final_metadata(
    match: FinalTestMatch,
    *,
    candidate: CompiledCandidate,
    opponent: ResolvedOpponent,
) -> dict[str, Any]:
    return {
        "final_test_schema_version": FINAL_TEST_SCHEMA_VERSION,
        "candidate_id": match.candidate_id,
        "candidate_player": match.candidate_player,
        "opponent_id": match.opponent_id,
        "opponent": opponent.class_name,
        "opponent_display_name": opponent.display_name,
        "opponent_upstream_repository": opponent.upstream_repository,
        "opponent_upstream_commit": opponent.pinned_commit,
        "opponent_jar_sha256": opponent.jar_sha256,
        "map_id": match.map_id,
        "map": match.map_path,
        "seed": match.seed,
        "max_cycles": match.max_cycles,
        "candidate_source_sha256": candidate.source_hash,
        "candidate_class_sha256": candidate.class_hash,
        "evolution_game_performance": candidate.selected.evolution_game_performance,
        "evolution_code_quality": candidate.selected.evolution_code_quality,
    }


def _exception_record(
    match: FinalTestMatch,
    reason: str,
    *,
    category: str = "final_test_runner_error",
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "candidate_id": match.candidate_id,
        "match_index": match.match_index,
        "candidate_player": match.candidate_player,
        "opponent_id": match.opponent_id,
        "map_id": match.map_id,
        "map": match.map_path,
        "seed": match.seed,
        "max_cycles": match.max_cycles,
        "status": "failed",
        "ok": False,
        "failure_category": category,
        "failure_reason": reason,
        "winner": None,
        "final_tick": None,
        "return_code": None,
        "duration_seconds": 0.0,
        "command": [],
        "stdout": "",
        "stderr": reason,
        "replay_path": None,
        "round_state_path": None,
        "telemetry": None,
        "timing": {
            "started_at": now,
            "finished_at": now,
            "duration_seconds": 0.0,
            "timeout_seconds": None,
            "status": "failed",
        },
    }


def _default_final_test_id(selector: str, *, smoke: bool) -> str:
    label = "".join(character if character.isalnum() else "_" for character in selector).strip("_")
    prefix = "smoke" if smoke else "final"
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{prefix}_{label}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

