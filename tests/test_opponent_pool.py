"""Contracts for the bounded tournament-managed opponent pool."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.runtime_evaluation import MatchResult
from eagle.opponent_pool import (
    POOL_PATH,
    POOL_SCHEMA_VERSION,
    PROTECTED_OPPONENT_IDS,
    initial_pool,
    load_pool,
    member_identity,
    member_reference,
    resolve_member_reference,
    select_pool_opponents,
    update_pool,
)
from eagle.opponents import OpponentSpec


def _config(*, capacity: int = 10, seed: int = 23) -> ExperimentConfig:
    return replace(
        ExperimentConfig.from_mapping({}),
        random_seed=seed,
        self_play_opponent_library_capacity=capacity,
    )


def _signature(*actions: str) -> dict[str, object]:
    return {
        "status": "complete",
        "dataset_id": "dataset",
        "dataset_sha256": "states",
        "normalization_version": "v1",
        "probe_ids": [f"p{index}" for index in range(len(actions))],
        "action_hashes": list(actions),
        "global_hash": "-".join(actions),
    }


def _candidate(
    candidate_id: str,
    *,
    source: str | None = None,
    generation: int = 1,
    signature: dict[str, object] | None = None,
) -> Candidate:
    return Candidate(
        id=candidate_id,
        generation=generation,
        generated_java=source or f"source {candidate_id}",
        compile_status="success",
        status="evaluated",
        game_eval_result={
            "expected_match_count": 18,
            "completed_match_count": 18,
            "opponent_results": [{"status": "completed"}],
        },
        semantic_signature=signature or {},
    )


def _persist(run_dir: Path, candidate: Candidate) -> Candidate:
    source = run_dir / "candidates" / candidate.id / "phenotype" / "CandidateAgent.java"
    write_candidate_inputs(run_dir / "candidates", candidate)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(candidate.generated_java, encoding="utf-8")
    candidate = replace(candidate, generated_java_path=str(source))
    write_candidate_snapshot(run_dir / "candidates", candidate)
    evaluation = run_dir / "candidates" / candidate.id / "evaluation"
    evaluation.mkdir(parents=True, exist_ok=True)
    (evaluation / "game_performance.json").write_text(
        json.dumps(candidate.game_eval_result), encoding="utf-8"
    )
    class_file = run_dir / "classes" / candidate.id / "ai" / "generated" / "CandidateAgent.class"
    class_file.parent.mkdir(parents=True, exist_ok=True)
    class_file.write_bytes(candidate.id.encode("utf-8"))
    return candidate


def _fake_match(outcomes: list[str], calls: list[dict[str, object]] | None = None):
    def run(**kwargs: object) -> MatchResult:
        if calls is not None:
            calls.append(dict(kwargs))
        index = int(kwargs["match_index"])
        outcome = outcomes[index % len(outcomes)]
        candidate_player = int(kwargs["candidate_player"])
        match_dir = Path(kwargs["match_output_dir"])
        match_dir.mkdir(parents=True, exist_ok=True)
        ok = outcome != "error"
        winner = (
            candidate_player if outcome == "win"
            else 1 - candidate_player if outcome == "loss"
            else -1 if outcome == "draw"
            else None
        )
        result = MatchResult(
            ok=ok,
            score=0.0,
            command=[],
            match_index=index,
            match_seed=int(kwargs["match_seed"]),
            candidate_id=str(kwargs["candidate_id"]),
            generation=int(kwargs["generation"]),
            candidate_player=candidate_player,
            opponent=str(kwargs["opponent"]),
            opponent_id=str(kwargs["opponent_id"]),
            opponent_name=str(kwargs["opponent_name"]),
            map_path=str(kwargs["map_path"]),
            map_id=str(kwargs["map_id"]),
            round_index=int(kwargs["round_index"]),
            max_cycles=int(kwargs["tick_limit"]),
            source_hash=str(kwargs["source_hash"]),
            class_hash=str(kwargs["class_hash"]),
            status="success" if ok else "failed",
            failure_category=None if ok else "runtime_match_failure",
            failure_reason=None if ok else "boom",
            winner=winner,
        )
        (match_dir / "result.json").write_text(
            json.dumps(result.to_json_dict()), encoding="utf-8"
        )
        return result

    return run


class OpponentPoolTests(unittest.TestCase):
    def test_initial_pool_and_selection_keep_protected_builtins_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = select_pool_opponents(root, generation=7, config=_config())
            second = select_pool_opponents(root, generation=7, config=_config())

        self.assertEqual(len(initial_pool()), 10)
        self.assertEqual(
            [item.opponent_id for item in first[:4] if isinstance(item, OpponentSpec)],
            list(PROTECTED_OPPONENT_IDS),
        )
        self.assertEqual([member_identity(item) for item in first], [member_identity(item) for item in second])
        self.assertEqual(len({member_identity(item) for item in first}), 10)

    def test_below_capacity_admits_candidates_and_deduplicates_source_and_semantics(self) -> None:
        candidates = [
            _candidate("first", source="same source", signature=_signature("a", "b")),
            _candidate("same-hash", source="same source", signature=_signature("a", "c")),
            _candidate("same-semantics", signature=_signature("a", "b")),
            _candidate("distinct", signature=_signature("a", "d")),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = [_persist(root, item) for item in candidates]
            update_pool(root, candidates, generation=1, config=_config(capacity=15), mock=True)
            members = load_pool(root, capacity=15)

        self.assertEqual(
            [item.id for item in members if isinstance(item, Candidate)],
            ["distinct", "first"],
        )

    def test_overflow_uses_result_driven_tournament_and_never_evicts_protected(self) -> None:
        entrant = _candidate("entrant")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entrant = _persist(root, entrant)
            update_pool(root, [entrant], generation=2, config=_config(), mock=True)
            members = load_pool(root, capacity=10)
            result = json.loads((
                root / "archives" / "opponent_pool_tournaments"
                / "generation_0002" / entrant.id / "result.json"
            ).read_text(encoding="utf-8"))
            all_match_artifacts = all((
                root / "archives" / "opponent_pool_tournaments" / "generation_0002"
                / entrant.id / f"match_{index:02d}" / "result.json"
            ).is_file() for index in range(18))

        identities = {member_identity(item) for item in members}
        self.assertIn("candidate:entrant", identities)
        self.assertTrue(all(f"builtin:{item}" in identities for item in PROTECTED_OPPONENT_IDS))
        self.assertEqual(len(identities), 10)
        self.assertEqual(result["decision"], "replace")
        self.assertEqual(result["completed_matches"], 18)
        self.assertEqual(len(result["matches"]), 18)
        self.assertEqual(len(set(item["match_seed"] for item in result["matches"])), 18)
        self.assertIsNotNone(result["defender_source_sha256"])
        self.assertIsNotNone(result["defender_classes_sha256"])
        self.assertTrue(all_match_artifacts)

    def test_tie_and_runtime_error_retain_incumbent(self) -> None:
        for name, outcomes, expected_status, expected_errors in (
            ("tie", ["win", "loss"], "completed", 0),
            ("error", ["error"], "failed", 18),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                entrant = _persist(root, _candidate(f"entrant-{name}"))
                before = {member_identity(item) for item in initial_pool()}
                with patch(
                    "eagle.evaluation.runtime_evaluation.run_microrts_match",
                    side_effect=_fake_match(outcomes),
                ):
                    update_pool(root, [entrant], generation=3, config=_config(), mock=True)
                after = {member_identity(item) for item in load_pool(root, capacity=10)}
                result = json.loads((
                    root / "archives" / "opponent_pool_tournaments"
                    / "generation_0003" / entrant.id / "result.json"
                ).read_text(encoding="utf-8"))
                self.assertEqual(after, before)
                self.assertEqual(result["decision"], "retain")
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["errors"], expected_errors)
                self.assertEqual(result["attempted_matches"], 18)
                self.assertEqual(result["completed_matches"], 18 - expected_errors)

    def test_setup_failure_persists_evidence_and_preserves_authoritative_pool_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incumbent = _persist(root, _candidate("incumbent"))
            update_pool(root, [incumbent], generation=1, config=_config(capacity=11), mock=True)
            path = root / POOL_PATH
            before = path.read_bytes()
            entrant = _persist(root, _candidate("missing-source"))
            Path(entrant.generated_java_path or "").unlink()

            with self.assertRaisesRegex(RuntimeError, "source is unavailable"):
                update_pool(root, [entrant], generation=2, config=_config(capacity=11), mock=True)

            result = json.loads((
                root / "archives" / "opponent_pool_tournaments"
                / "generation_0002" / entrant.id / "result.json"
            ).read_text(encoding="utf-8"))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["decision"], "retain")

    def test_interrupt_persists_duel_evidence_and_preserves_pool_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incumbent = _persist(root, _candidate("incumbent"))
            update_pool(root, [incumbent], generation=1, config=_config(capacity=11), mock=True)
            path = root / POOL_PATH
            before = path.read_bytes()
            entrant = _persist(root, _candidate("interrupted"))

            with patch(
                "eagle.evaluation.runtime_evaluation.run_microrts_match",
                side_effect=KeyboardInterrupt,
            ), self.assertRaises(KeyboardInterrupt):
                update_pool(root, [entrant], generation=2, config=_config(capacity=11), mock=True)

            result = json.loads((
                root / "archives" / "opponent_pool_tournaments"
                / "generation_0002" / entrant.id / "result.json"
            ).read_text(encoding="utf-8"))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result["status"], "interrupted")
            timing = [
                json.loads(line) for line in (root / "timing.jsonl").read_text().splitlines()
            ]
            self.assertEqual(timing[-1]["event"], "opponent_pool_tournament")
            self.assertEqual(timing[-1]["status"], "interrupted")

    def test_defender_and_match_seed_schedule_is_deterministic(self) -> None:
        schedules: list[tuple[str, list[int]]] = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                entrant = _persist(root, _candidate("scheduled"))
                calls: list[dict[str, object]] = []
                with patch(
                    "eagle.evaluation.runtime_evaluation.run_microrts_match",
                    side_effect=_fake_match(["draw"], calls),
                ):
                    update_pool(root, [entrant], generation=4, config=_config(seed=91), mock=True)
                result = json.loads((
                    root / "archives" / "opponent_pool_tournaments"
                    / "generation_0004" / entrant.id / "result.json"
                ).read_text(encoding="utf-8"))
                schedules.append((
                    result["defender"]["opponent_id"],
                    [int(call["match_seed"]) for call in calls],
                ))

        self.assertEqual(schedules[0], schedules[1])
        self.assertEqual(len(set(schedules[0][1])), 18)

    def test_load_pool_fences_schema_capacity_protected_identity_and_candidate_hash(self) -> None:
        candidate = _candidate("loaded")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = _persist(root, candidate)
            update_pool(root, [candidate], generation=1, config=_config(capacity=11), mock=True)
            path = root / POOL_PATH
            valid = json.loads(path.read_text(encoding="utf-8"))
            candidate_reference = next(
                item for item in valid["opponents"] if item["kind"] == "candidate"
            )
            self.assertEqual(
                member_identity(resolve_member_reference(root, candidate_reference)),
                "candidate:loaded",
            )
            with self.assertRaisesRegex(ValueError, "Invalid candidate identifier"):
                resolve_member_reference(root, {
                    **candidate_reference,
                    "candidate_id": "..\\escape",
                })

            mutations = {
                "schema": lambda payload: payload.update(schema_version="legacy"),
                "capacity": lambda payload: payload.update(capacity=12),
                "protected": lambda payload: payload.update(protected_opponent_ids=["mayari"]),
                "duplicate": lambda payload: payload["opponents"].__setitem__(1, payload["opponents"][0]),
                "hash": lambda payload: next(
                    item for item in payload["opponents"] if item["kind"] == "candidate"
                ).update(generated_java_sha256="0" * 64),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    payload = json.loads(json.dumps(valid))
                    mutate(payload)
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_pool(root, capacity=11)
            path.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(len(load_pool(root, capacity=11)), 11)

        self.assertEqual(valid["schema_version"], POOL_SCHEMA_VERSION)
        self.assertEqual(member_reference(initial_pool()[0])["kind"], "builtin")


if __name__ == "__main__":
    unittest.main()
