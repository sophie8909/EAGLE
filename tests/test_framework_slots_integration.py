from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.evaluation.decoding import decode_validate_compile_candidate
from eagle.evaluation.pipeline import evaluate_population
from eagle.evolution.offspring import plan_offspring
from eagle.evolution.runtime import build_search_runtime
from eagle.generation.backend import MockGenerationBackend
from eagle.generation.framework_slots import (
    load_framework_bundle,
    render_framework,
    validate_genome,
)
from eagle.generation.java_agent_generator import validate_generated_java_source
from eagle.operators.adaptive import build_reflection_operator_controller
from eagle.operators.initialization import initialize_population


class _ForbiddenBackend:
    operation = "forbidden"
    model = "forbidden"

    def generate(self, *args, **kwargs):
        raise AssertionError("framework_slots must not invoke a generation backend")

    def authoritative_request(self, *args, **kwargs):
        raise AssertionError("framework_slots must not construct an LLM request")


class FrameworkSlotsIntegrationTests(unittest.TestCase):
    def _write_bundle(self, root: Path) -> Path:
        scaffold = Path("eagle/java_templates/CandidateAgent.java").read_text(
            encoding="utf-8"
        )
        scaffold = scaffold.replace(
            "public final class CandidateAgent extends AbstractionLayerAI {",
            "public final class CandidateAgent extends AbstractionLayerAI {\n"
            "    private static final int FRAMEWORK_REVISION = 1;",
            1,
        )
        scaffold = scaffold.replace(
            "    private void decide(AgentContext context) {\n",
            "    private void decide(AgentContext context) {\n"
            "        int horizon = {{EAGLE_SLOT:horizon}};\n"
            "        double aggression = {{EAGLE_SLOT:aggression}};\n"
            "        if ({{EAGLE_SLOT:early_return}} && horizon > 0 "
            "&& aggression >= 0.0 && context.units.isEmpty()) { return; }\n",
            1,
        )
        payload = {
            "schema_version": "eagle-framework-bundle-v1",
            "framework_id": "integration_framework_v1",
            "java_template": scaffold,
            "slots": [
                {
                    "slot_id": "horizon",
                    "kind": "integer",
                    "marker": "{{EAGLE_SLOT:horizon}}",
                    "default": 2,
                    "minimum": 1,
                    "maximum": 4,
                    "step": 1,
                    "choices": [],
                    "purpose": "Bound a local decision horizon.",
                },
                {
                    "slot_id": "aggression",
                    "kind": "number",
                    "marker": "{{EAGLE_SLOT:aggression}}",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "step": 0.5,
                    "choices": [],
                    "purpose": "Control a bounded numeric preference.",
                },
                {
                    "slot_id": "early_return",
                    "kind": "expression_choice",
                    "marker": "{{EAGLE_SLOT:early_return}}",
                    "default": "never",
                    "minimum": None,
                    "maximum": None,
                    "step": None,
                    "choices": [
                        {
                            "choice_id": "never",
                            "java_expression": "false",
                            "description": "Never take the early-return branch.",
                        },
                        {
                            "choice_id": "always",
                            "java_expression": "true",
                            "description": "Allow the guarded early-return branch.",
                        },
                    ],
                    "purpose": "Select an allowlisted branch expression.",
                },
            ],
            "slot_generation_prompt": "Return only values for the declared slots.",
            "report": {
                "architecture_summary": "Immutable scaffold with typed controls.",
                "decision_flow": ["Observe", "Control", "Act"],
                "invariants": ["No runtime LLM calls."],
                "slot_rationale": {
                    "horizon": "Integer control.",
                    "aggression": "Numeric control.",
                    "early_return": "Allowlisted expression control.",
                },
                "assumptions": ["The checked-in scaffold is authoritative."],
                "risks": ["A small domain limits diversity."],
            },
        }
        path = root / "bundle.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def _config(self, root: Path, **overrides) -> ExperimentConfig:
        bundle = self._write_bundle(root)
        payload = {
            "java_materialization_mode": "framework_slots",
            "framework": {"bundle_path": str(bundle)},
            "candidate_java_mode": "generated_phenotype",
            "parent_evaluation_mode": "reuse_cached",
            "reflection_operator_mode": "static",
            "population_size": 4,
            "random_seed": 31,
            "mutation_rate": 1.0,
            "crossover_rate": 1.0,
            "semantic_probes_enabled": False,
        }
        payload.update(overrides)
        config = ExperimentConfig.from_mapping(payload)
        config.validate()
        return config

    def test_checked_in_framework_exposes_rich_recombinable_control_surface(self):
        bundle = load_framework_bundle(
            Path("configs/framework_bundles/fixed_worker_combat/bundle.json")
        )
        self.assertEqual(len(bundle.slots), 27)
        self.assertGreaterEqual(
            sum(slot.kind == "expression_choice" for slot in bundle.slots), 16
        )
        genome = {slot.slot_id: slot.default for slot in bundle.slots}
        self.assertEqual(validate_genome(bundle, genome), genome)
        rendered = render_framework(bundle, genome)
        validation = validate_generated_java_source(
            rendered.source,
            "CandidateAgent",
            immutable_scaffold_source=bundle.java_template,
        )
        self.assertTrue(validation.ok, validation.error)
        self.assertNotIn("{{EAGLE_SLOT:", rendered.source)

    def test_initialization_and_offspring_are_reproducible_without_reflection(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._config(Path(directory))
            first = initialize_population(config)
            second = initialize_population(config)
            self.assertEqual(
                [candidate.control_genome for candidate in first],
                [candidate.control_genome for candidate in second],
            )
            self.assertTrue(all(not candidate.slot_parent_ids for candidate in first))
            self.assertTrue(
                all(
                    candidate.framework_bundle_sha256 == config.framework_bundle_sha256
                    for candidate in first
                )
            )

            controller = build_reflection_operator_controller(config)
            plans_a = plan_offspring(
                first,
                config=config,
                generation=1,
                rng=__import__("random").Random(999),
                mutations={},
                operator_controller=controller,
            )
            plans_b = plan_offspring(
                first,
                config=config,
                generation=1,
                rng=__import__("random").Random(1),
                mutations={},
                operator_controller=controller,
            )
            signatures_a = [
                (plan.candidate.control_genome, plan.candidate.slot_parent_ids)
                for plan in plans_a
            ]
            signatures_b = [
                (plan.candidate.control_genome, plan.candidate.slot_parent_ids)
                for plan in plans_b
            ]
            self.assertEqual(signatures_a, signatures_b)
            bundle = load_framework_bundle(
                config.framework_bundle_path,
                expected_sha256=config.framework_bundle_sha256,
            )
            parent_ids = {candidate.id for candidate in first}
            for plan in plans_a:
                candidate = plan.candidate
                self.assertEqual(validate_genome(bundle, candidate.control_genome), candidate.control_genome)
                self.assertEqual(set(candidate.slot_parent_ids), set(bundle.slot_ids))
                self.assertLessEqual(set(candidate.slot_parent_ids.values()), parent_ids)
                self.assertIsNone(plan.mutation)
                self.assertIsNone(plan.mutation_name)

    def test_runtime_and_decoder_never_use_llm_and_record_exact_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root, population_size=1)
            runtime = build_search_runtime(
                config,
                mock=False,
                run_dir=root / "run",
                candidates_dir=root / "run" / "candidates",
            )
            self.assertEqual(runtime.mutations, {})
            self.assertIsInstance(runtime.generation_backend, MockGenerationBackend)

            candidate = initialize_population(config)[0]
            genome_before = dict(candidate.control_genome)
            bounded = decode_validate_compile_candidate(
                candidate,
                config=config,
                backend=_ForbiddenBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=True,
                candidate_artifact_dir=root / "candidate",
            )
            evidence = bounded.compiler_evidence
            exact_hash = hashlib.sha256(config.framework_bundle_path.read_bytes()).hexdigest()
            self.assertEqual(evidence["operation"], "framework_slot_assembly")
            self.assertEqual(evidence["framework_bundle_sha256"], exact_hash)
            self.assertNotEqual(evidence["canonical_bundle_sha256"], exact_hash)
            self.assertEqual(evidence["control_genome"], genome_before)
            self.assertEqual(candidate.control_genome, genome_before)
            self.assertTrue(bounded.compile_result.ok)
            self.assertEqual(bounded.attempts[0].request_kind, "framework_slot_assembly")
            bundle = load_framework_bundle(
                config.framework_bundle_path,
                expected_sha256=config.framework_bundle_sha256,
            )
            rendered = render_framework(bundle, candidate.control_genome)
            self.assertFalse(
                validate_generated_java_source(rendered.source, "CandidateAgent").ok
            )
            self.assertTrue(
                validate_generated_java_source(
                    rendered.source,
                    "CandidateAgent",
                    immutable_scaffold_source=bundle.java_template,
                ).ok
            )
            drifted = rendered.source.replace(
                "private static final int FRAMEWORK_REVISION = 1;",
                "private static final int FRAMEWORK_REVISION = 2;",
                1,
            )
            drift_validation = validate_generated_java_source(
                drifted,
                "CandidateAgent",
                immutable_scaffold_source=bundle.java_template,
            )
            self.assertFalse(drift_validation.ok)
            self.assertIn("fixed_scaffold", {item["check"] for item in drift_validation.failed_checks})
            persisted = json.loads(
                (root / "candidate" / "generation" / "framework_evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(persisted, evidence)

    def test_evaluation_preserves_control_genome_and_uses_materialization_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root, population_size=1)
            candidate = initialize_population(config)[0]
            genome_before = dict(candidate.control_genome)
            evaluated = evaluate_population(
                [candidate],
                generation=0,
                config=config,
                backend=_ForbiddenBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                candidates_dir=root / "candidates",
                mock=True,
            )[0]
            self.assertEqual(evaluated.control_genome, genome_before)
            self.assertEqual(evaluated.slot_parent_ids, candidate.slot_parent_ids)
            self.assertEqual(
                evaluated.framework_bundle_sha256,
                candidate.framework_bundle_sha256,
            )
            self.assertIsNone(evaluated.timing["generation_llm"])
            self.assertEqual(
                evaluated.timing["java_materialization"]["operation"],
                "framework_slot_assembly",
            )
            self.assertIn("java_materialization", evaluated.timing["child_total"]["includes"])
            evidence = json.loads(
                (
                    root
                    / "candidates"
                    / evaluated.id
                    / "generation"
                    / "framework_evidence.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["control_genome"], genome_before)
            self.assertEqual(
                evidence["framework_bundle_sha256"],
                config.framework_bundle_sha256,
            )


if __name__ == "__main__":
    unittest.main()
