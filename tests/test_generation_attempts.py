from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.artifacts import write_candidate_artifacts
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import decode_validate_compile_candidate, evaluate_candidate
from eagle.llm import LLMCallLogger
from evaluation.compiler import CompileResult
from generation.agent_template import JavaTemplatePaths, load_java_template
from generation.backend import (
    GenerationBackend,
    InitialJavaSeedBackend,
    OpenAICompatibleGenerationBackend,
)


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.payload = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


class ScriptedBackend(GenerationBackend):
    model = "scripted"
    operation = "generation"

    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.requests: list[str] = []
        self.contexts: list[tuple[int, str]] = []

    def generate(self, candidate: Candidate, class_name: str) -> str:
        return next(self.responses)

    def generate_from_request(
        self,
        candidate: Candidate,
        class_name: str,
        request_text: str,
    ) -> str:
        self.requests.append(request_text)
        return self.generate(candidate, class_name)

    def set_generation_attempt_context(self, attempt: int, attempt_id: str) -> None:
        self.contexts.append((attempt, attempt_id))


def invalid_source() -> str:
    return load_java_template(JavaTemplatePaths()).replace(
        "package ai.generated;",
        "package invalid.generated;",
        1,
    )


def replace_strategy(source: str, strategy: str) -> str:
    start_marker = "// EAGLE_AGENT_STRATEGY_START"
    end_marker = "// EAGLE_AGENT_STRATEGY_END"
    start = source.index(start_marker) + len(start_marker)
    end = source.index(end_marker)
    return source[:start] + "\n" + strategy.strip() + "\n\n    " + source[end:]


class GenerationAttemptTests(unittest.TestCase):
    def test_validation_failures_chain_compile_repair_requests_and_one_javac(self) -> None:
        valid = load_java_template(JavaTemplatePaths())
        backend = ScriptedBackend([invalid_source(), invalid_source(), valid])
        config = ExperimentConfig.from_mapping({"generation_max_attempts": 3})
        candidate = Candidate(
            id="bounded-success",
            generation=1,
            strategy_prompt="POLICY_GENE_SENTINEL",
            generation_prompt="GENERATION_GENE_SENTINEL",
        )
        with tempfile.TemporaryDirectory() as temp, patch(
            "eagle.evaluation.compile_agent_source",
            return_value=CompileResult(True, ["javac"]),
        ) as compile_source:
            root = Path(temp)
            result = decode_validate_compile_candidate(
                candidate,
                config=config,
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                candidate_artifact_dir=root / "candidate",
                mock=False,
            )

            self.assertEqual(result.selected_attempt, 3)
            self.assertEqual(result.final_attempt, 3)
            self.assertEqual(len(result.attempts), 3)
            self.assertEqual(
                [item.request_kind for item in result.attempts],
                ["initial_decode", "compile_repair", "compile_repair"],
            )
            self.assertEqual(len(set(backend.requests)), 3)
            for repair_request in backend.requests[1:]:
                self.assertIn("POLICY_GENE_SENTINEL", repair_request)
                self.assertIn("GENERATION_GENE_SENTINEL", repair_request)
                self.assertIn("IMMUTABLE MICRORTS ACTION/JAVA API CONTRACT", repair_request)
                self.assertIn("UNTRUSTED PREVIOUS COMPLETE", repair_request)
                self.assertIn('"validation"', repair_request)
                self.assertIn("public final class CandidateAgent", repair_request)
            self.assertEqual([item[0] for item in backend.contexts], [1, 2, 3])
            compile_source.assert_called_once()
            for number in (1, 2, 3):
                attempt_dir = root / "candidate" / "generation" / "attempts" / f"attempt_{number:03d}"
                self.assertTrue((attempt_dir / "response_raw.txt").is_file())
                self.assertTrue((attempt_dir / "validation" / "validation_result.json").is_file())
                self.assertTrue((attempt_dir / "compilation" / "compilation_result.json").is_file())
                self.assertTrue((attempt_dir / "timing.json").is_file())
            ledger = json.loads(
                (root / "candidate" / "generation" / "repair_ledger.json").read_text()
            )
            self.assertEqual(
                [item["request_kind"] for item in ledger["attempts"]],
                ["initial_decode", "compile_repair", "compile_repair"],
            )
            self.assertEqual(ledger["attempts"][1]["repair_of_attempt"], 1)
            self.assertEqual(ledger["selected_attempt"], 3)
            self.assertEqual(ledger["final_attempt"], 3)
            self.assertEqual(
                ledger["attempts"][1]["previous_source_sha256"],
                hashlib.sha256(
                    result.attempts[0].generation.assembled_java.encode("utf-8")
                ).hexdigest(),
            )
            for number, request in enumerate(backend.requests, start=1):
                self.assertEqual(
                    ledger["attempts"][number - 1]["request_sha256"],
                    hashlib.sha256(request.encode("utf-8")).hexdigest(),
                )
            self.assertFalse((root / "classes" / ".generation_attempts" / "bounded-success").exists())

    def test_compile_failure_gets_guided_repair_and_each_source_compiles_once(self) -> None:
        valid = load_java_template(JavaTemplatePaths())
        backend = ScriptedBackend([valid, valid])
        results = [
            CompileResult(False, ["javac", "first"], stderr="first failed", returncode=1),
            CompileResult(True, ["javac", "second"]),
        ]
        with tempfile.TemporaryDirectory() as temp, patch(
            "eagle.evaluation.compile_agent_source",
            side_effect=results,
        ) as compile_source:
            root = Path(temp)
            outcome = decode_validate_compile_candidate(
                Candidate(id="compile-retry", generation=1),
                config=ExperimentConfig.from_mapping({"generation_max_attempts": 2}),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=False,
            )
        self.assertEqual(outcome.selected_attempt, 2)
        self.assertEqual(compile_source.call_count, 2)
        self.assertEqual(len(set(backend.requests)), 2)
        self.assertEqual(outcome.attempts[1].request_kind, "compile_repair")
        self.assertIn("first failed", backend.requests[1])

    def test_each_repair_consumes_only_the_immediately_previous_source(self) -> None:
        first = invalid_source().replace(
            "// EAGLE_AGENT_STRATEGY_START",
            "// EAGLE_AGENT_STRATEGY_START\n    // PREVIOUS_SOURCE_ONE_ONLY",
            1,
        )
        second = invalid_source().replace(
            "// EAGLE_AGENT_STRATEGY_START",
            "// EAGLE_AGENT_STRATEGY_START\n    // PREVIOUS_SOURCE_TWO_ONLY",
            1,
        )
        valid = load_java_template(JavaTemplatePaths()).replace(
            "// EAGLE_AGENT_STRATEGY_START",
            "// EAGLE_AGENT_STRATEGY_START\n    // FINAL_SOURCE_ONLY",
            1,
        )
        backend = ScriptedBackend([first, second, valid])
        with tempfile.TemporaryDirectory() as temp, patch(
            "eagle.evaluation.compile_agent_source",
            return_value=CompileResult(True, ["javac"]),
        ):
            root = Path(temp)
            outcome = decode_validate_compile_candidate(
                Candidate(
                    id="previous-only",
                    generation=1,
                    strategy_prompt="AUTHORITATIVE_POLICY_GENE",
                    generation_prompt="AUTHORITATIVE_GENERATION_GENE",
                ),
                config=ExperimentConfig.from_mapping({"generation_max_attempts": 3}),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=False,
            )

        self.assertEqual(outcome.selected_attempt, 3)
        self.assertIn("PREVIOUS_SOURCE_ONE_ONLY", backend.requests[1])
        self.assertNotIn("PREVIOUS_SOURCE_TWO_ONLY", backend.requests[1])
        self.assertIn("PREVIOUS_SOURCE_TWO_ONLY", backend.requests[2])
        self.assertNotIn("PREVIOUS_SOURCE_ONE_ONLY", backend.requests[2])
        for request in backend.requests[1:]:
            self.assertIn("AUTHORITATIVE_POLICY_GENE", request)
            self.assertIn("AUTHORITATIVE_GENERATION_GENE", request)
            self.assertIn("IMMUTABLE MICRORTS ACTION/JAVA API CONTRACT", request)
            self.assertIn("CANONICAL CHECKED-IN SCAFFOLD", request)

    def test_all_fail_projects_last_attempt_and_cleans_canonical_classes(self) -> None:
        valid = load_java_template(JavaTemplatePaths())
        backend = ScriptedBackend([invalid_source(), valid])
        compile_failure = CompileResult(
            False,
            ["javac"],
            stderr="last compilation failed",
            returncode=1,
        )
        with tempfile.TemporaryDirectory() as temp, patch(
            "eagle.evaluation.compile_agent_source",
            return_value=compile_failure,
        ):
            root = Path(temp)
            evaluation = evaluate_candidate(
                Candidate(id="bounded-failure", generation=1),
                config=ExperimentConfig.from_mapping({"generation_max_attempts": 2}),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "candidates" / "bounded-failure" / "matches",
                mock=False,
                ordinal=0,
            )
            write_candidate_artifacts(root / "candidates", evaluation)
            main = json.loads(
                (root / "candidates" / "bounded-failure" / "generation" / "result.json").read_text()
            )

        self.assertEqual(evaluation.result.failure_stage, "compilation")
        self.assertIn("last compilation failed", evaluation.result.failure_reason or "")
        self.assertIsNone(main["selected_attempt"])
        self.assertEqual(main["final_attempt"], 2)
        self.assertIsNone(main["canonical_attempt_artifact"])
        self.assertTrue(main["representative_attempt_artifact"].endswith("attempt_002"))
        self.assertFalse((root / "classes" / "bounded-failure").exists())
        self.assertFalse(
            (root / "candidates" / "bounded-failure" / "phenotype" / "CandidateAgent.java").exists()
        )
        self.assertEqual(evaluation.candidate.generated_java, "")

    def test_initial_seed_is_loaded_once_even_when_configured_for_five(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = ExperimentConfig.from_mapping({"generation_max_attempts": 5})
            result = decode_validate_compile_candidate(
                Candidate(id="seed-once", generation=0),
                config=config,
                backend=InitialJavaSeedBackend(config.initial_java_seed_path),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                candidate_artifact_dir=root / "candidate",
                mock=True,
            )
        self.assertEqual(result.max_attempts, 1)
        self.assertEqual(len(result.attempts), 1)
        self.assertFalse((root / "candidate" / "generation" / "attempts").exists())

    def test_default_preserves_legacy_single_decode(self) -> None:
        config = ExperimentConfig.from_mapping({})
        self.assertEqual(config.generation_max_attempts, 1)
        self.assertEqual(config.to_mapping()["generation_max_attempts"], 1)
        with self.assertRaisesRegex(ValueError, "generation_max_attempts"):
            ExperimentConfig.from_mapping({"generation_max_attempts": 0}).validate()

    def test_static_0824_tracked_configs_explicitly_use_five(self) -> None:
        paths = sorted(
            Path("configs/experiments/static_0824").glob("ministral3_8b_static_*.yaml")
        )
        self.assertEqual(len(paths), 4)
        for path in paths:
            self.assertEqual(ExperimentConfig.from_file(path).generation_max_attempts, 5)

    def test_outer_and_transport_attempt_axes_are_durable_and_correlated(self) -> None:
        valid = load_java_template(JavaTemplatePaths())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            timing_path = root / "timing.jsonl"
            logger = LLMCallLogger(root / "llm_logs", run_id="attempt-run", timing_path=timing_path)
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080",
                "test-model",
                max_retries=0,
                logger=logger,
            )
            with patch(
                "generation.backend.urllib.request.urlopen",
                side_effect=[
                    FakeResponse(invalid_source()),
                    FakeResponse(invalid_source()),
                    FakeResponse(valid),
                ],
            ), patch(
                "eagle.evaluation.compile_agent_source",
                return_value=CompileResult(True, ["javac"]),
            ):
                decode_validate_compile_candidate(
                    Candidate(id="logged-attempts", generation=1),
                    config=ExperimentConfig.from_mapping({"generation_max_attempts": 3}),
                    backend=backend,
                    generated_agents_dir=root / "generated",
                    classes_dir=root / "classes",
                    mock=False,
                )

            logs = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((root / "llm_logs").glob("*.json"))
            ]
            timing = [json.loads(line) for line in timing_path.read_text().splitlines()]
            self.assertEqual([item["attempt"] for item in logs], [1, 2, 3])
            self.assertEqual([item["generation_attempt"] for item in logs], [1, 2, 3])
            self.assertEqual([item["transport_attempt"] for item in logs], [1, 1, 1])
            self.assertEqual(len({item["generation_attempt_id"] for item in logs}), 3)
            self.assertEqual(len({item["request_correlation_id"] for item in logs}), 3)
            self.assertEqual(len({item["input"] for item in logs}), 3)
            self.assertEqual(
                [item["generation_request_kind"] for item in logs],
                ["initial_decode", "compile_repair", "compile_repair"],
            )
            self.assertEqual(
                [item["generation_attempt"] for item in timing],
                [1, 2, 3],
            )
            self.assertEqual(
                [item["generation_attempt_id"] for item in timing],
                [item["generation_attempt_id"] for item in logs],
            )
            self.assertEqual(
                [item["request_correlation_id"] for item in timing],
                [item["request_correlation_id"] for item in logs],
            )
            self.assertEqual(
                [item["transport_attempt"] for item in timing],
                [1, 1, 1],
            )
            self.assertEqual(
                [item["generation_request_kind"] for item in timing],
                ["initial_decode", "compile_repair", "compile_repair"],
            )

            resumed = LLMCallLogger(root / "llm_logs", run_id="attempt-run")
            resumed.write(
                stage="generation",
                input_text="resume",
                status="success",
                backend="test",
                model="test-model",
            )
            self.assertEqual(len(list((root / "llm_logs").glob("*.json"))), 4)

    def test_logged_all_fail_exhausts_exactly_configured_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = LLMCallLogger(root / "llm_logs", run_id="all-fail")
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080",
                "test-model",
                max_retries=0,
                logger=logger,
            )
            with patch(
                "generation.backend.urllib.request.urlopen",
                side_effect=[FakeResponse(invalid_source()) for _ in range(3)],
            ):
                outcome = decode_validate_compile_candidate(
                    Candidate(id="logged-all-fail", generation=1),
                    config=ExperimentConfig.from_mapping({"generation_max_attempts": 3}),
                    backend=backend,
                    generated_agents_dir=root / "generated",
                    classes_dir=root / "classes",
                    mock=False,
                )
            logs = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((root / "llm_logs").glob("*.json"))
            ]
        self.assertIsNone(outcome.selected_attempt)
        self.assertEqual(outcome.final_attempt, 3)
        self.assertEqual(len(outcome.attempts), 3)
        self.assertEqual([item["attempt"] for item in logs], [1, 2, 3])

    def test_extraction_failure_resamples_the_unchanged_initial_decode(self) -> None:
        valid = load_java_template(JavaTemplatePaths())
        backend = ScriptedBackend(["```java\npartial", valid])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outcome = decode_validate_compile_candidate(
                Candidate(id="decode-retry", generation=1),
                config=ExperimentConfig.from_mapping({"generation_max_attempts": 2}),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=True,
            )
        self.assertEqual(outcome.selected_attempt, 2)
        self.assertEqual(backend.requests[0], backend.requests[1])
        self.assertEqual(
            [item.request_kind for item in outcome.attempts],
            ["initial_decode", "initial_decode_retry"],
        )
        self.assertIsNone(outcome.attempts[1].repair_evidence)

    def test_persisted_partial_attempt_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            partial = root / "candidate" / "generation" / "attempts" / "attempt_001"
            partial.mkdir(parents=True)
            (partial / "request.txt").write_text("durable request", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "audit-only"):
                decode_validate_compile_candidate(
                    Candidate(id="partial-candidate", generation=1),
                    config=ExperimentConfig.from_mapping({"generation_max_attempts": 3}),
                    backend=ScriptedBackend([invalid_source()]),
                    generated_agents_dir=root / "generated",
                    classes_dir=root / "classes",
                    candidate_artifact_dir=root / "candidate",
                    mock=False,
                )
            self.assertEqual((partial / "request.txt").read_text(), "durable request")

    def test_fixed_scaffold_drift_is_normalized_before_compilation(self) -> None:
        seed_path = Path("eagle/java_seeds/CandidateAgent.java").resolve()
        generated = load_java_template(JavaTemplatePaths(seed_path)).replace(
            "    private void applyAutoDefense(int player, GameState gs) {",
            "    private void modelDeletedFixedMethod(int player, GameState gs) {",
            1,
        ).replace(
            "private void decide(AgentContext context) {",
            "private void decide(AgentContext context) {\n        commandIdle(null);",
            1,
        )
        backend = ScriptedBackend([generated])
        with tempfile.TemporaryDirectory() as temp, patch(
            "eagle.evaluation.compile_agent_source",
            return_value=CompileResult(True, ["javac"]),
        ) as compile_source:
            root = Path(temp)
            outcome = decode_validate_compile_candidate(
                Candidate(id="scaffold-delta", generation=1),
                config=ExperimentConfig.from_mapping({
                    "generation_max_attempts": 2,
                    "agent_template_path": str(seed_path),
                }),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                candidate_artifact_dir=root / "candidate",
                mock=True,
            )
            attempt_dir = root / "candidate" / "generation" / "attempts" / "attempt_001"
            extracted_artifact = (
                attempt_dir / "extracted_candidate.java"
            ).read_text(encoding="utf-8")
            normalized_artifact = (
                attempt_dir / "normalized_candidate.java"
            ).read_text(encoding="utf-8")
        self.assertEqual(outcome.selected_attempt, 1)
        self.assertEqual(outcome.final_attempt, 1)
        self.assertEqual(len(outcome.attempts), 1)
        compile_source.assert_called_once()
        self.assertIn(
            "private void modelDeletedFixedMethod",
            outcome.generation.extracted_code,
        )
        self.assertNotIn(
            "private void modelDeletedFixedMethod",
            outcome.generation.assembled_java,
        )
        self.assertIn("private void applyAutoDefense", outcome.generation.assembled_java)
        self.assertIn(
            "commandIdle(null);",
            outcome.generation.assembled_java,
        )
        self.assertEqual(extracted_artifact, generated.strip())
        self.assertEqual(normalized_artifact, outcome.generation.assembled_java)

    def test_compile_repair_rejects_broad_nondiagnostic_strategy_drift(self) -> None:
        valid = load_java_template(JavaTemplatePaths())
        radical = replace_strategy(
            valid,
            """
    private void decide(AgentContext context) {
        for (Unit unit : context.units) {
            if (isIdleAlly(unit, context)) {
                commandIdle(unit);
            }
        }
    }
            """,
        )
        backend = ScriptedBackend([valid, radical])
        with tempfile.TemporaryDirectory() as temp, patch(
            "eagle.evaluation.compile_agent_source",
            return_value=CompileResult(False, ["javac"], stderr="missing symbol", returncode=1),
        ) as compile_source:
            root = Path(temp)
            outcome = decode_validate_compile_candidate(
                Candidate(id="broad-delta", generation=1),
                config=ExperimentConfig.from_mapping({"generation_max_attempts": 2}),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=False,
            )
        self.assertIsNone(outcome.selected_attempt)
        self.assertEqual(compile_source.call_count, 1)
        self.assertIn("too broadly", outcome.generation.failure_reason or "")

    def test_compile_repair_preserves_genotype_lineage_and_aos_metadata(self) -> None:
        candidate = Candidate(
            id="state-invariants",
            generation=2,
            parent_ids=("parent-a", "parent-b"),
            strategy_prompt="authoritative policy",
            generation_prompt="authoritative translation",
            operator="crossover+mutation",
            mutation_type="strategy",
            strategy_parent_id="parent-a",
            generation_prompt_parent_id="parent-b",
            source_candidate_ids=("parent-a", "parent-b"),
            metadata={"aos": {"sentinel": "unchanged"}},
        )
        backend = ScriptedBackend([
            invalid_source(),
            load_java_template(JavaTemplatePaths()),
        ])
        before_genes = (candidate.strategy_prompt, candidate.generation_prompt)
        before_lineage = candidate.lineage_to_json_dict()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evaluation = evaluate_candidate(
                candidate,
                config=ExperimentConfig.from_mapping({"generation_max_attempts": 2}),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "candidate" / "matches",
                mock=True,
                ordinal=0,
            )
        self.assertEqual(
            (evaluation.candidate.strategy_prompt, evaluation.candidate.generation_prompt),
            before_genes,
        )
        self.assertEqual(evaluation.candidate.lineage_to_json_dict(), before_lineage)
        self.assertEqual(evaluation.candidate.metadata["aos"], {"sentinel": "unchanged"})


if __name__ == "__main__":
    unittest.main()
