from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from eagle.candidate import (
    Candidate,
    FRAMEWORK_SLOTS_CANDIDATE_SCHEMA_VERSION,
    FRAMEWORK_SLOTS_LINEAGE_SCHEMA_VERSION,
    FRAMEWORK_SLOTS_MATERIALIZATION_VERSION,
)
from eagle.config import (
    FRAMEWORK_BUNDLE_VERSION,
    FRAMEWORK_SLOTS_EVOLUTION_PROTOCOL,
    ExperimentConfig,
)
from eagle.operators.adaptive import ReflectionOperatorMode


class FrameworkSlotsCandidateTests(unittest.TestCase):
    def candidate(self) -> Candidate:
        return Candidate(
            id="framework-child",
            generation=2,
            parent_ids=("parent-a", "parent-b"),
            java_materialization_mode="framework_slots",
            java_compiler_version=FRAMEWORK_SLOTS_MATERIALIZATION_VERSION,
            control_genome={"threshold": 7, "policy": "defensive"},
            slot_parent_ids={"threshold": "parent-b", "policy": "parent-a"},
            framework_bundle_sha256="a" * 64,
        )

    def test_control_genome_is_the_only_active_component(self) -> None:
        candidate = self.candidate()

        self.assertEqual(candidate.active_genotype_components, ("control_genome",))
        self.assertEqual(
            candidate.materialization_to_json_dict(),
            {
                "candidate_java_mode": "generated_phenotype",
                "java_materialization_mode": "framework_slots",
                "java_compiler_version": FRAMEWORK_SLOTS_MATERIALIZATION_VERSION,
                "active_genotype_components": ["control_genome"],
                "framework_bundle_sha256": "a" * 64,
            },
        )
        with self.assertRaisesRegex(ValueError, "framework_slots"):
            candidate.generation_input()

    def test_snapshot_and_lineage_retain_genome_bundle_and_slot_provenance(self) -> None:
        candidate = self.candidate()

        snapshot = candidate.to_json_dict()
        self.assertEqual(
            snapshot["candidate_schema_version"],
            FRAMEWORK_SLOTS_CANDIDATE_SCHEMA_VERSION,
        )
        self.assertEqual(
            snapshot["control_genome"],
            {"policy": "defensive", "threshold": 7},
        )
        self.assertEqual(
            snapshot["slot_parent_ids"],
            {"policy": "parent-a", "threshold": "parent-b"},
        )
        self.assertEqual(snapshot["framework_bundle_sha256"], "a" * 64)
        self.assertEqual(snapshot["source_candidate_ids"], ["parent-a", "parent-b"])
        self.assertNotIn("strategy_prompt", snapshot)
        self.assertNotIn("generation_prompt", snapshot)
        self.assertNotIn("strategy_parent_id", snapshot)
        self.assertNotIn("generation_prompt_parent_id", snapshot)

        lineage = candidate.lineage_to_json_dict()
        self.assertEqual(
            lineage["lineage_schema_version"],
            FRAMEWORK_SLOTS_LINEAGE_SCHEMA_VERSION,
        )
        self.assertEqual(lineage["slot_parent_ids"], snapshot["slot_parent_ids"])
        self.assertEqual(lineage["source_candidate_ids"], ["parent-a", "parent-b"])
        self.assertNotIn("strategy_parent_id", lineage)
        self.assertNotIn("generation_prompt_parent_id", lineage)

    def test_framework_candidate_requires_bundle_hash_and_valid_slot_provenance(self) -> None:
        with self.assertRaisesRegex(ValueError, "framework_bundle_sha256"):
            Candidate(id="missing-bundle-hash", java_materialization_mode="framework_slots")
        with self.assertRaisesRegex(ValueError, "slot_parent_ids"):
            Candidate(
                id="invalid-slot-provenance",
                java_materialization_mode="framework_slots",
                control_genome={"known": 1},
                slot_parent_ids={"unknown": "parent"},
                framework_bundle_sha256="b" * 64,
            )
        with self.assertRaisesRegex(ValueError, "finite JSON values"):
            Candidate(
                id="non-finite-slot-value",
                java_materialization_mode="framework_slots",
                control_genome={"threshold": float("nan")},
                framework_bundle_sha256="b" * 64,
            )

    def test_legacy_modes_do_not_emit_framework_fields(self) -> None:
        candidate = Candidate(id="legacy")

        snapshot = candidate.to_json_dict()
        lineage = candidate.lineage_to_json_dict()
        for payload in (snapshot, lineage):
            self.assertNotIn("control_genome", payload)
            self.assertNotIn("slot_parent_ids", payload)
            self.assertNotIn("framework_bundle_sha256", payload)


class FrameworkSlotsConfigTests(unittest.TestCase):
    def write_bundle(self, directory: str, *, suffix: str = "") -> Path:
        path = Path(directory) / "framework.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": FRAMEWORK_BUNDLE_VERSION,
                    "framework_id": "config_test",
                    "java_template": (
                        "package ai.generated;\n"
                        "public final class CandidateAgent {\n"
                        "  int threshold = {{EAGLE_SLOT:threshold}};\n"
                        "}\n"
                    ),
                    "slots": [
                        {
                            "slot_id": "threshold",
                            "kind": "integer",
                            "marker": "{{EAGLE_SLOT:threshold}}",
                            "default": 2,
                            "minimum": 1,
                            "maximum": 3,
                            "step": 1,
                            "choices": [],
                            "purpose": "Bounded config-test control.",
                        }
                    ],
                    "slot_generation_prompt": "Return only the threshold control.",
                    "report": {
                        "architecture_summary": "Minimal configuration fixture.",
                        "decision_flow": ["Read threshold", "Act"],
                        "invariants": ["The template is immutable."],
                        "slot_rationale": {"threshold": "Exercises numeric controls."},
                        "assumptions": ["The Java fixture is illustrative."],
                        "risks": ["This fixture is intentionally small."],
                    },
                },
                separators=(",", ":"),
            )
            + suffix,
            encoding="utf-8",
        )
        return path

    def config(self, bundle: Path) -> ExperimentConfig:
        config = ExperimentConfig.from_mapping(
            {
                "schema_version": "experiment-v2",
                "java_materialization_mode": "framework_slots",
                "framework": {"bundle_path": str(bundle)},
                "candidate_java_mode": "generated_phenotype",
                "parent_evaluation_mode": "reuse_cached",
                "reflection_operator_mode": "static",
            }
        )
        config.validate()
        return config

    def test_bundle_is_required_hashed_and_written_to_resolved_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.write_bundle(directory, suffix="\n")
            expected_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
            config = self.config(bundle)
            resolved = config.to_mapping()

        self.assertEqual(config.evolution_protocol, FRAMEWORK_SLOTS_EVOLUTION_PROTOCOL)
        self.assertEqual(
            config.java_compiler_version,
            FRAMEWORK_SLOTS_MATERIALIZATION_VERSION,
        )
        self.assertEqual(config.framework_bundle_sha256, expected_hash)
        self.assertEqual(
            resolved["active_genotype_components"], ["control_genome"]
        )
        self.assertNotIn("strategy_policy_format", resolved)
        self.assertEqual(
            resolved["framework"],
            {
                "bundle_path": str(bundle.resolve()),
                "bundle_version": FRAMEWORK_BUNDLE_VERSION,
                "bundle_sha256": expected_hash,
                "evolution_mode": "local",
            },
        )
        self.assertFalse(config.needs_llm_runtime)

    def test_resolved_bundle_hash_fences_reload_and_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.write_bundle(directory)
            resolved = self.config(bundle).to_mapping()
            reloaded = ExperimentConfig.from_mapping(resolved)
            reloaded.validate()

            bundle.write_text(
                json.dumps({"schema_version": FRAMEWORK_BUNDLE_VERSION, "changed": True}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "bundle_sha256"):
                ExperimentConfig.from_mapping(resolved)

    def test_bundle_mapping_path_and_version_are_strict(self) -> None:
        with self.assertRaisesRegex(ValueError, "framework mapping"):
            ExperimentConfig.from_mapping(
                {"java_materialization_mode": "framework_slots"}
            )

        with tempfile.TemporaryDirectory() as directory:
            bundle = self.write_bundle(directory)
            with self.assertRaisesRegex(ValueError, "Unsupported framework bundle version"):
                bundle.write_text(
                    json.dumps({"schema_version": "future-framework"}),
                    encoding="utf-8",
                )
                ExperimentConfig.from_mapping(
                    {
                        "java_materialization_mode": "framework_slots",
                        "framework": {"bundle_path": str(bundle)},
                    }
                )

    def test_mode_requires_generated_phenotype_cached_parents_and_static_operator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(self.write_bundle(directory))
            invalid = (
                (
                    replace(config, candidate_java_mode="inherited_genotype"),
                    "generated_phenotype",
                ),
                (
                    replace(config, parent_evaluation_mode="regenerate_same_genotype"),
                    "reuse_cached",
                ),
                (
                    replace(
                        config,
                        reflection_operator_mode=ReflectionOperatorMode.AOS_OPPONENT,
                    ),
                    "reflection_operator_mode=static",
                ),
            )
            for candidate, message in invalid:
                with self.subTest(message=message), self.assertRaisesRegex(
                    ValueError, message
                ):
                    candidate.validate()


if __name__ == "__main__":
    unittest.main()
