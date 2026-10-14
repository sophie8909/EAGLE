from __future__ import annotations

import hashlib
import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from eagle.artifacts import write_candidate_artifacts, write_candidate_inputs, write_candidate_snapshot, write_run_config
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.compiler import CompileResult
from eagle.evaluation.decoding import decode_validate_compile_candidate
from eagle.evaluation.pipeline import evaluate_candidate
from eagle.evaluation.microrts_runner import IntegrationResult
from eagle.evaluation.semantic_signature import unavailable_semantic_signature
from eagle.evolution.offspring import plan_offspring
from eagle.evolution.resume import load_resume_config, validate_resume_config
from eagle.evolution.runtime import build_search_runtime
from eagle.generation.backend import GenerationBackend
from eagle.generation.java_agent_generator import ValidationResult
from eagle.operators.initialization import initialize_population
from eagle.run_artifacts import load_candidate


class ForbiddenBackend(GenerationBackend):
    def generate(self, *args, **kwargs):
        raise AssertionError("Java LLM must never be called")

    def authoritative_request(self, *args, **kwargs):
        raise AssertionError("Java request must never be built")


class DeterministicMaterializationTests(unittest.TestCase):
    def config(self):
        return ExperimentConfig.from_mapping({"java_materialization_mode": "deterministic_dsl", "mutation_rate": 0, "population_size": 1})

    def test_config_default_and_unused_generation_resources(self):
        self.assertEqual(ExperimentConfig.from_mapping({}).java_materialization_mode, "llm")
        config = ExperimentConfig.from_mapping({"schema_version": "experiment-v2", "java_materialization_mode": "deterministic_dsl", "generation_prompt_file": "missing.txt", "mutation_rate": 0})
        config.validate()
        config.validate_runtime_files()
        self.assertFalse(config.needs_llm_runtime)
        self.assertEqual(config.reflection_operator_settings.enabled_operators, ("strategy_reflection",))
        self.assertEqual(initialize_population(config)[0].active_genotype_components, ("strategy_prompt",))

    def test_zero_backend_calls_one_compile_hashes_readback_and_timing(self):
        config = self.config()
        candidate = replace(initialize_population(config)[0], generation_prompt="inactive", inherited_java="inactive")
        with tempfile.TemporaryDirectory() as temp, patch("eagle.evaluation.decoding.compile_agent_source", return_value=CompileResult(True, ["javac"])) as javac:
            root = Path(temp)
            write_candidate_inputs(root / "candidates", candidate)
            evaluation = evaluate_candidate(candidate, config=config, backend=ForbiddenBackend(), generated_agents_dir=root / "agents", classes_dir=root / "classes", mock=True, ordinal=0, match_artifacts_dir=root / "candidates" / candidate.id / "matches")
            self.assertEqual(javac.call_count, 1)
            self.assertEqual(evaluation.candidate.status, "evaluated")
            self.assertIsNone(evaluation.candidate.timing["generation_llm"])
            materialization = evaluation.candidate.timing["java_materialization"]
            total = evaluation.candidate.timing["child_total"]
            self.assertIn("java_materialization", total["includes"])
            self.assertGreaterEqual(total["duration_seconds"], materialization["duration_seconds"])
            write_candidate_artifacts(root / "candidates", evaluation)
            evidence = json.loads((root / "candidates" / candidate.id / "generation/result.json").read_text())
            self.assertEqual(evidence["llm_attempts"], [])
            self.assertEqual(evidence["operation"], "deterministic_dsl_compile")
            self.assertEqual(evidence["source_sha256"], hashlib.sha256(evaluation.candidate.generated_java.encode()).hexdigest())
            self.assertEqual(evidence["source_sha256"], hashlib.sha256((root / "candidates" / candidate.id / "phenotype/CandidateAgent.java").read_bytes()).hexdigest())
            self.assertEqual(load_candidate(root, candidate.id).active_genotype_components, ("strategy_prompt",))
            candidate_dir = root / "candidates" / candidate.id
            for relative, tampered in (("genotype/policy_prompt.txt", '{"version":"eagle-strategy-dsl-v1","rules":[{"actor":"Worker","when":true,"action":{"type":"idle"}}]}'),
                                       ("generation/normalized_policy.json", "{}"),
                                       ("phenotype/CandidateAgent.java", "tampered"),
                                       ("generation/scaffold.java", "tampered")):
                path = candidate_dir / relative
                original = path.read_text()
                path.write_text(tampered)
                with self.assertRaises(ValueError):
                    load_candidate(root, candidate.id)
                path.write_text(original)
            evidence_path = candidate_dir / "generation/compiler_evidence.json"
            original = evidence_path.read_text()
            missing_hash = json.loads(original)
            missing_hash["source_sha256"] = None
            evidence_path.write_text(json.dumps(missing_hash))
            with self.assertRaises(ValueError):
                load_candidate(root, candidate.id)
            evidence_path.write_text(original)
            snapshot = root / "candidates" / candidate.id / "candidate.json"
            payload = json.loads(snapshot.read_text())
            original = snapshot.read_text()
            payload["candidate_schema_version"] = "future"
            snapshot.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "candidate schema"):
                load_candidate(root, candidate.id)
            snapshot.write_text(original)
            payload = json.loads(original)
            result_path = candidate_dir / "generation/result.json"
            original_result = result_path.read_text()
            result_payload = json.loads(original_result)
            result_payload["source_sha256"] = "0" * 64
            result_path.write_text(json.dumps(result_payload))
            with self.assertRaisesRegex(ValueError, "evidence mismatch"):
                load_candidate(root, candidate.id)
            result_path.write_text(original_result)
            payload["java_compiler_version"] = "unknown"
            snapshot.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "compiler version"):
                load_candidate(root, candidate.id)

    def test_compiler_and_javac_failure_never_repair(self):
        config = replace(self.config(), generation_max_attempts=5)
        candidate = initialize_population(config)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("eagle.generation.dsl_java_compiler.compile_strategy_dsl", side_effect=ValueError("fixture compiler failure")), patch("eagle.evaluation.decoding.compile_agent_source") as javac:
                result = decode_validate_compile_candidate(candidate, config=config, backend=ForbiddenBackend(), generated_agents_dir=root / "agents", classes_dir=root / "classes", mock=True, candidate_artifact_dir=root / "candidate")
                self.assertEqual(result.generation.failure_stage, "materialization")
                self.assertEqual(len(result.attempts), 1)
                javac.assert_not_called()
                self.assertTrue((root / "candidate/generation/compiler_evidence.json").is_file())
                evaluation = evaluate_candidate(candidate, config=config, backend=ForbiddenBackend(), generated_agents_dir=root / "agents", classes_dir=root / "classes", mock=True, ordinal=0)
                self.assertEqual(evaluation.candidate.failure_stage, "materialization")
                self.assertEqual(set(evaluation.candidate.fitness_objectives.values()), {-1000.0})
                self.assertIsNone(evaluation.candidate.timing["generation_llm"])
            with patch("eagle.evaluation.decoding.compile_agent_source", return_value=CompileResult(False, ["javac"], stderr="failure", returncode=1)) as javac:
                result = decode_validate_compile_candidate(candidate, config=config, backend=ForbiddenBackend(), generated_agents_dir=root / "agents", classes_dir=root / "classes", mock=True)
                self.assertEqual(javac.call_count, 1)
                self.assertIsNone(result.selected_attempt)
                self.assertEqual(len(result.attempts), 1)
            invalid = ValidationResult(False, "fixture invalid source", failed_checks=({"check": "package", "reason": "fixture"},))
            with patch("eagle.evaluation.decoding.validate_generated_java_source", return_value=invalid), patch("eagle.evaluation.decoding.compile_agent_source") as javac:
                evaluation = evaluate_candidate(candidate, config=config, backend=ForbiddenBackend(), generated_agents_dir=root / "agents", classes_dir=root / "classes", mock=True, ordinal=0)
                self.assertEqual(evaluation.candidate.failure_stage, "validation")
                self.assertEqual(set(evaluation.candidate.fitness_objectives.values()), {-1000.0})
                javac.assert_not_called()

    def test_resume_mode_and_version_fences(self):
        config = self.config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_run_config(root, config, mock=False)
            self.assertEqual(load_resume_config(root).java_compiler_version, config.java_compiler_version)
            with self.assertRaisesRegex(ValueError, "materialization_mode"):
                validate_resume_config(replace(config, java_materialization_mode="llm"), config)
            with self.assertRaisesRegex(ValueError, "materialization_mode"):
                validate_resume_config(config, replace(config, java_materialization_mode="llm"))
            with self.assertRaisesRegex(ValueError, "compiler version"):
                replace(config, java_compiler_version="future").validate()
            path = root / "config.yaml"
            original = path.read_text()
            path.write_text(original.replace("eagle-dsl-java-v1", "future"))
            with self.assertRaisesRegex(ValueError, "compiler version"):
                load_resume_config(root)
            path.write_text(original)
            (root / "manifest.json").write_text(json.dumps({"java_materialization_mode": "llm", "evolution_protocol": config.evolution_protocol}))
            with self.assertRaisesRegex(ValueError, "protocol mismatch"):
                load_resume_config(root)

    def test_legacy_manifest_can_omit_protocol_but_cannot_switch_modes(self):
        config = ExperimentConfig.from_mapping({})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_run_config(root, config, mock=False)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": "eagle-run-v2"}))
            self.assertEqual(load_resume_config(root).java_materialization_mode, "llm")
            manifest.write_text(json.dumps({"java_materialization_mode": "deterministic_dsl"}))
            with self.assertRaisesRegex(ValueError, "protocol mismatch"):
                load_resume_config(root)

    def test_stage_order_integration_probe_matches_with_unavailable_probe(self):
        config = replace(self.config(), semantic_probes_enabled=True)
        candidate = initialize_population(config)[0]
        order = []
        clock = [0.0]
        def integrate(**kwargs):
            order.append("integration")
            return IntegrationResult("success", (), 1.0)
        def probe(**kwargs):
            order.append("semantic_probe")
            clock[0] += 3.0
            return unavailable_semantic_signature("fixture diagnostic failure")
        def matches(**kwargs):
            order.append("matches")
            clock[0] += 5.0
            return [], None
        with tempfile.TemporaryDirectory() as temp, patch("eagle.evaluation.pipeline.time.monotonic", side_effect=lambda: clock[0]), patch("eagle.evaluation.decoding.compile_agent_source", return_value=CompileResult(True, ["javac"])), patch("eagle.evaluation.pipeline.integrate_microrts_agent", side_effect=integrate), patch("eagle.evaluation.pipeline.evaluate_semantic_signature", side_effect=probe), patch("eagle.evaluation.matches.evaluate_matches", side_effect=matches):
            root = Path(temp)
            evaluation = evaluate_candidate(candidate, config=config, backend=ForbiddenBackend(), generated_agents_dir=root / "agents", classes_dir=root / "classes", mock=False, ordinal=0, semantic_dataset=object())
        self.assertEqual(order, ["integration", "semantic_probe", "matches"])
        self.assertEqual(evaluation.candidate.timing["evaluation"]["duration_seconds"], 8.0)
        self.assertGreaterEqual(evaluation.candidate.timing["child_total"]["duration_seconds"], 8.0)

    def test_inactive_genes_have_no_artifact_or_lineage_provenance(self):
        candidate = Candidate(id="inactive", java_materialization_mode="deterministic_dsl",
                              java_compiler_version="eagle-dsl-java-v1", inherited_java="unused",
                              java_parent_id="unused", generation_prompt_parent_id="unused")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_candidate_inputs(root, candidate)
            write_candidate_snapshot(root, candidate)
            payload = json.loads((root / "inactive/candidate.json").read_text())
            self.assertNotIn("inherited_java", payload["artifacts"])
            self.assertNotIn("code_generation_prompt", payload["artifacts"])
            self.assertIsNone(payload["generation_prompt_parent_id"])
            self.assertNotIn("java_parent_id", payload)
            self.assertNotIn("unused", payload["source_candidate_ids"])

    def test_legacy_inherited_boundary_comes_from_run_config(self):
        config = replace(ExperimentConfig.from_mapping({}), candidate_java_mode="inherited_genotype")
        candidate = replace(Candidate(id="legacy"), inherited_java="legacy Java", java_parent_id="parent")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_run_config(root, config, mock=False)
            write_candidate_inputs(root / "candidates", candidate)
            write_candidate_snapshot(root / "candidates", candidate)
            path = root / "candidates/legacy/candidate.json"
            payload = json.loads(path.read_text())
            for key in ("candidate_java_mode", "java_materialization_mode", "java_compiler_version", "active_genotype_components"):
                payload.pop(key, None)
            path.write_text(json.dumps(payload))
            self.assertIn("inherited_java", load_candidate(root, candidate.id).active_genotype_components)
            (root / "config.yaml").unlink()
            write_run_config(root, replace(config, candidate_java_mode="generated_phenotype"), mock=False)
            self.assertNotIn("inherited_java", load_candidate(root, candidate.id).active_genotype_components)

    def test_offspring_no_code_gate_and_strategy_only(self):
        config = self.config()
        parent = initialize_population(config)[0]
        with tempfile.TemporaryDirectory() as temp:
            runtime = build_search_runtime(config, mock=True, run_dir=Path(temp), candidates_dir=Path(temp) / "candidates")
            self.assertEqual(tuple(runtime.mutations), ("strategy",))
            plans = plan_offspring([parent], config=config, generation=1, rng=random.Random(1), mutations={}, operator_controller=runtime.operator_controller)
            self.assertEqual(plans[0].candidate.active_genotype_components, ("strategy_prompt",))
            self.assertIsNone(plans[0].candidate.generation_prompt_parent_id)
            self.assertNotIn("pre_crossover_code_checks", plans[0].candidate.metadata)
            other = replace(parent, id="other", strategy_prompt='{"rules":[],"version":"eagle-strategy-dsl-v1"}')
            plans = plan_offspring([parent, other], config=replace(config, crossover_rate=1), generation=2, rng=random.Random(1), mutations={}, operator_controller=runtime.operator_controller)
            child = plans[0].candidate
            self.assertEqual(child.operator, "crossover")
            self.assertIn(child.strategy_prompt, (parent.strategy_prompt, other.strategy_prompt))
            self.assertIsNone(child.generation_prompt_parent_id)
            self.assertEqual(child.active_genotype_components, ("strategy_prompt",))


if __name__ == "__main__":
    unittest.main()
