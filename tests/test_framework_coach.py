from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eagle.candidate import Candidate
from eagle.evaluation.runtime_evaluation import write_mock_round_state
from eagle.generation.framework_slots import validate_framework_bundle
from eagle.operators.context import (
    CandidateReflectionSummary,
    EvolutionContext,
    ReflectionContext,
)
from eagle.operators.framework_coach import (
    FRAMEWORK_SELECTION_SCHEMA_NAME,
    FRAMEWORK_SELECTION_SCHEMA_VERSION,
    MockFrameworkRoleBackend,
    framework_selection_response_schema,
    validate_framework_selection_response,
)
from eagle.operators.strategy import MockRoleBackend, StrategyReflectionPipeline
from tests.test_framework_coach_integration import bundle_payload
from tests.test_strategy_reflection_pipeline import _write_trace


EXACT_HASH = "a" * 64


class SequenceBackend:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.commentator = MockRoleBackend()

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "ROLE: match_commentator" in prompt:
            return self.commentator.generate(prompt)
        return self.responses.pop(0)


class FrameworkCoachTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = validate_framework_bundle(bundle_payload())

    def candidate(
        self,
        candidate_id: str = "child",
        *,
        genome: dict | None = None,
        generation: int = 1,
    ) -> Candidate:
        return Candidate(
            id=candidate_id,
            generation=generation,
            candidate_java_mode="generated_phenotype",
            java_materialization_mode="framework_slots",
            control_genome=genome or {"horizon": 3, "policy": "aggressive"},
            slot_parent_ids={"horizon": "parent-a", "policy": "parent-b"}
            if generation
            else {},
            framework_bundle_sha256=EXACT_HASH,
            generation_prompt="",
        )

    def envelope(self, genome: dict | None = None) -> str:
        return json.dumps(
            {
                "schema_version": FRAMEWORK_SELECTION_SCHEMA_VERSION,
                "framework_bundle_sha256": EXACT_HASH,
                "control_genome": genome
                or {"horizon": 2, "policy": "balanced"},
            }
        )

    def context(self, root: Path, *, trace: bool = True) -> ReflectionContext:
        trace_path = root / "match_trace.jsonl.gz"
        if trace:
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=8)
            _write_trace(
                trace_path,
                metadata={
                    "match_id": "worst",
                    "candidate_side": "p0",
                    "opponent_name": "LightRush",
                },
                round_state_dir=states,
                raw_result={
                    "final_tick": 0,
                    "players": {
                        "p0": {"resource_total": 10},
                        "p1": {"resource_total": 8},
                    },
                },
                tick_limit=0,
            )
        return ReflectionContext(
            candidate=CandidateReflectionSummary(candidate_id="parent-a"),
            evolution=EvolutionContext(generation_index=1),
            parent_comparison={
                "framework_control_genome": {
                    "horizon": 1,
                    "policy": "aggressive",
                }
            },
            game_evidence={"wins": 0, "draws": 0, "losses": 1},
            per_match_results=(
                {
                    "match_id": "worst",
                    "match_index": 0,
                    "performance": -1.0,
                    "winner": 1,
                    "candidate_player": 0,
                    "opponent_name": "LightRush",
                    "map_name": "map",
                    "match_trace_path": str(trace_path),
                },
            ),
        )

    def test_selection_envelope_is_exact_and_genome_validated(self) -> None:
        payload = json.loads(self.envelope())
        parsed, genome = validate_framework_selection_response(
            self.envelope(),
            bundle=self.bundle,
            framework_bundle_sha256=EXACT_HASH,
        )
        self.assertEqual(parsed, payload)
        self.assertEqual(genome, payload["control_genome"])

        invalid = {
            "unknown key": payload | {"extra": True},
            "missing key": {
                key: value
                for key, value in payload.items()
                if key != "schema_version"
            },
            "wrong schema": payload | {"schema_version": "wrong"},
            "wrong hash": payload | {"framework_bundle_sha256": "b" * 64},
            "unknown slot": payload
            | {
                "control_genome": {
                    **payload["control_genome"],
                    "extra": 1,
                }
            },
            "invalid value": payload
            | {"control_genome": {"horizon": 99, "policy": "balanced"}},
        }
        for label, value in invalid.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate_framework_selection_response(
                    json.dumps(value),
                    bundle=self.bundle,
                    framework_bundle_sha256=EXACT_HASH,
                )

    def test_selection_response_schema_freezes_bundle_hash_and_finite_domains(self) -> None:
        schema = framework_selection_response_schema(self.bundle, EXACT_HASH)
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(
            schema["properties"]["schema_version"]["enum"],
            [FRAMEWORK_SELECTION_SCHEMA_VERSION],
        )
        self.assertEqual(
            schema["properties"]["framework_bundle_sha256"]["enum"],
            [EXACT_HASH],
        )
        genome = schema["properties"]["control_genome"]
        self.assertEqual(genome["required"], ["horizon", "policy"])
        self.assertEqual(genome["properties"]["horizon"]["enum"], [1, 2, 3])
        self.assertEqual(
            genome["properties"]["policy"]["enum"],
            ["balanced", "aggressive"],
        )
        self.assertEqual(FRAMEWORK_SELECTION_SCHEMA_NAME, "eagle_framework_selection")

    def test_selection_rejects_duplicate_keys_and_non_json_wrappers(self) -> None:
        for raw in (
            self.envelope().replace('"horizon": 2', '"horizon": 1, "horizon": 2'),
            "```json\n" + self.envelope() + "\n```",
            "[]",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_framework_selection_response(
                    raw, bundle=self.bundle, framework_bundle_sha256=EXACT_HASH,
                )

    def test_initial_retry_persists_raw_before_parse_and_real_timing(self) -> None:
        backend = SequenceBackend(["not json", self.envelope()])
        candidate = self.candidate("initial", generation=0)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selected = StrategyReflectionPipeline(
                backend,
                framework_bundle=self.bundle,
                framework_bundle_sha256=EXACT_HASH,
                max_attempts=2,
            ).select_initial_framework_genome(candidate, artifact_dir=root)
            stage = root / "initialization" / "framework_coach"
            first = json.loads(
                (stage / "coach_response_attempt_001.json").read_text(
                    encoding="utf-8"
                )
            )
            second_request = json.loads(
                (stage / "coach_request_attempt_002.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(selected.control_genome, {"horizon": 2, "policy": "balanced"})
        self.assertEqual(first["status"], "error")
        self.assertEqual(first["response"], "not json")
        self.assertIn("deterministic validation", second_request["prompt"])
        self.assertEqual(
            [item["status"] for item in selected.timing["reflection_llm"]["attempts"]],
            ["error", "success"],
        )

    def test_mutation_uses_parent_evidence_and_replaces_complete_child_genome(self) -> None:
        backend = SequenceBackend([self.envelope()])
        candidate = self.candidate()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = StrategyReflectionPipeline(
                backend,
                framework_bundle=self.bundle,
                framework_bundle_sha256=EXACT_HASH,
                max_attempts=1,
            ).run(candidate, self.context(root), artifact_dir=root / "child")
        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.candidate.control_genome,
            {"horizon": 2, "policy": "balanced"},
        )
        self.assertEqual(result.candidate.slot_parent_ids, candidate.slot_parent_ids)
        commentator = next(
            prompt for prompt in backend.prompts if "ROLE: match_commentator" in prompt
        )
        coach = next(
            prompt for prompt in backend.prompts if "ROLE: framework_coach" in prompt
        )
        self.assertIn('"control_genome": {"horizon": 1, "policy": "aggressive"}', commentator)
        self.assertIn(
            'evaluated_parent_control_genome: {"horizon": 1, "policy": "aggressive"}',
            coach,
        )
        self.assertIn(
            'current_child_control_genome: {"horizon": 3, "policy": "aggressive"}',
            coach,
        )

    def test_legal_noop_is_successful_reflection(self) -> None:
        candidate = self.candidate()
        backend = SequenceBackend([self.envelope(candidate.control_genome)])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = StrategyReflectionPipeline(
                backend,
                framework_bundle=self.bundle,
                framework_bundle_sha256=EXACT_HASH,
                max_attempts=1,
            ).run(candidate, self.context(root), artifact_dir=root / "child")
        self.assertEqual(result.status, "success")
        self.assertFalse(result.candidate.metadata["mutation"]["applied"])
        self.assertEqual(
            result.candidate.metadata["mutation"]["reflection_status"],
            "success",
        )

    def test_missing_trace_fails_and_preserves_complete_genome(self) -> None:
        candidate = self.candidate()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = StrategyReflectionPipeline(
                SequenceBackend([self.envelope()]),
                framework_bundle=self.bundle,
                framework_bundle_sha256=EXACT_HASH,
                max_attempts=1,
            ).run(candidate, self.context(root, trace=False), artifact_dir=root / "child")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.candidate.failure_stage, "reflection")
        self.assertEqual(result.candidate.control_genome, candidate.control_genome)
        self.assertEqual(result.candidate.slot_parent_ids, candidate.slot_parent_ids)

    def test_oversized_authoritative_prompt_fails_without_backend_call(self) -> None:
        backend = SequenceBackend([self.envelope()])
        candidate = self.candidate("initial", generation=0)
        selected = StrategyReflectionPipeline(
            backend,
            framework_bundle=self.bundle,
            framework_bundle_sha256=EXACT_HASH,
            max_prompt_chars=256,
        ).select_initial_framework_genome(candidate)
        self.assertEqual(selected.failure_stage, "initialization")
        self.assertIn("cannot be truncated", selected.failure_reason)
        self.assertEqual(backend.prompts, [])

    def test_attempt_timing_is_request_local_under_concurrency(self) -> None:
        backend = MockFrameworkRoleBackend(self.bundle, EXACT_HASH)
        pipeline = StrategyReflectionPipeline(
            backend,
            framework_bundle=self.bundle,
            framework_bundle_sha256=EXACT_HASH,
            max_attempts=1,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates = [
                self.candidate(f"initial-{index}", generation=0)
                for index in range(2)
            ]
            with ThreadPoolExecutor(max_workers=2) as pool:
                selected = list(
                    pool.map(
                        lambda item: pipeline.select_initial_framework_genome(
                            item,
                            artifact_dir=root / item.id,
                        ),
                        candidates,
                    )
                )
        for candidate in selected:
            attempts = candidate.timing["reflection_llm"]["attempts"]
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["status"], "success")
            self.assertEqual(candidate.failure_stage, None)


if __name__ == "__main__":
    unittest.main()
