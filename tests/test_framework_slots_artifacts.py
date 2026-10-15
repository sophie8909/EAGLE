from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from eagle.artifacts import (
    _write_generation_artifacts,
    write_candidate_inputs,
    write_candidate_snapshot,
    write_run_config,
)
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.resume import load_resume_config, validate_resume_config
from eagle.generation.framework_slots import render_framework, validate_framework_bundle
from eagle.run_artifacts import (
    FRAMEWORK_BUNDLE_ARTIFACT,
    freeze_framework_bundle,
    initialize_run_manifest,
    load_candidate,
)


def bundle_payload() -> dict:
    return {
        "schema_version": "eagle-framework-bundle-v1",
        "framework_id": "artifact_test_v1",
        "java_template": (
            "final class CandidateAgent {\n"
            "  int horizon = {{EAGLE_SLOT:horizon}};\n"
            "}\n"
        ),
        "slots": [
            {
                "slot_id": "horizon",
                "kind": "integer",
                "marker": "{{EAGLE_SLOT:horizon}}",
                "default": 4,
                "minimum": 2,
                "maximum": 8,
                "step": 2,
                "choices": [],
                "purpose": "Bound lookahead.",
            }
        ],
        "slot_generation_prompt": "Return the declared typed controls only.",
        "report": {
            "architecture_summary": "A deterministic test framework.",
            "decision_flow": ["Observe", "Act"],
            "invariants": ["No runtime LLM"],
            "slot_rationale": {"horizon": "Controls bounded lookahead."},
            "assumptions": ["Inputs are finite"],
            "risks": ["The test domain is small"],
        },
    }


class FrameworkSlotsArtifactTests(unittest.TestCase):
    def make_source_config(self, root: Path) -> tuple[Path, ExperimentConfig, bytes]:
        source = root / "source_bundle.json"
        bundle_bytes = (
            json.dumps(bundle_payload(), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        source.write_bytes(bundle_bytes)
        config = ExperimentConfig.from_mapping(
            {
                "java_materialization_mode": "framework_slots",
                "framework": {"bundle_path": str(source)},
                "candidate_java_mode": "generated_phenotype",
                "parent_evaluation_mode": "reuse_cached",
                "reflection_operator_mode": "static",
            }
        )
        return source, config, bundle_bytes

    def initialize_run(
        self, root: Path
    ) -> tuple[Path, ExperimentConfig, ExperimentConfig, bytes]:
        source, source_config, bundle_bytes = self.make_source_config(root)
        run_dir = root / "run"
        run_dir.mkdir()
        frozen = freeze_framework_bundle(run_dir, source_config)
        initialize_run_manifest(run_dir, config=frozen)
        write_run_config(run_dir, frozen, mock=False)
        return source, source_config, frozen, bundle_bytes

    def write_seed_candidate(self, run_dir: Path, config: ExperimentConfig) -> Candidate:
        bundle = validate_framework_bundle(bundle_payload())
        genome = {"horizon": 6}
        rendered = render_framework(bundle, genome)
        candidate = Candidate(
            id="gen_0000_framework",
            generation=0,
            candidate_java_mode="generated_phenotype",
            java_materialization_mode="framework_slots",
            java_compiler_version=config.java_compiler_version,
            control_genome=genome,
            slot_parent_ids={},
            framework_bundle_sha256=config.framework_bundle_sha256,
            generation_prompt="",
            generated_java=rendered.source,
            operator="seed",
            compile_status="success",
            status="evaluated",
        )
        write_candidate_inputs(run_dir / "candidates", candidate)
        evidence = {
            "schema_version": "eagle-framework-materialization-v1",
            "operation": "framework_slot_assembly",
            "materialization_mode": "framework_slots",
            "materialization_version": config.java_compiler_version,
            "framework_id": bundle.framework_id,
            "framework_bundle_sha256": config.framework_bundle_sha256,
            "canonical_bundle_sha256": rendered.bundle_sha256,
            "template_sha256": rendered.template_sha256,
            "genome_sha256": rendered.genome_sha256,
            "source_sha256": rendered.source_sha256,
            "control_genome": genome,
            "slot_parent_ids": {},
            "llm_attempts": 0,
        }
        evaluation = SimpleNamespace(
            candidate=candidate,
            generation_timing=evidence,
            generation_attempts=(),
            compile_result=SimpleNamespace(ok=True),
            result=SimpleNamespace(
                assembled_java=rendered.source,
                failure_category=None,
                failure_reason=None,
                validation_result=None,
            ),
        )
        _write_generation_artifacts(run_dir / "candidates" / candidate.id, evaluation)
        write_candidate_snapshot(run_dir / "candidates", candidate)
        return candidate

    def test_freeze_preserves_exact_bytes_and_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, frozen, original_bytes = self.initialize_run(root)
            frozen_path = root / "run" / FRAMEWORK_BUNDLE_ARTIFACT
            manifest = json.loads((root / "run" / "manifest.json").read_text())
            resolved = yaml.safe_load((root / "run" / "config.yaml").read_text())

            self.assertEqual(frozen_path.read_bytes(), original_bytes)
            self.assertEqual(frozen.framework_bundle_path, frozen_path.resolve())
            self.assertNotEqual(frozen.framework_bundle_path, source.resolve())
            self.assertEqual(
                manifest["framework_bundle_sha256"],
                hashlib.sha256(original_bytes).hexdigest(),
            )
            self.assertEqual(
                manifest["framework_bundle_version"], "eagle-framework-bundle-v1"
            )
            self.assertEqual(
                manifest["java_compiler_version"], "eagle-framework-slots-v1"
            )
            self.assertEqual(
                resolved["framework"]["bundle_path"], str(frozen_path.resolve())
            )

    def test_candidate_round_trip_validates_genome_evidence_and_phenotype(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, config, _ = self.initialize_run(root)
            candidate = self.write_seed_candidate(root / "run", config)

            restored = load_candidate(root / "run", candidate.id)

            self.assertEqual(restored.control_genome, {"horizon": 6})
            self.assertEqual(restored.framework_bundle_sha256, config.framework_bundle_sha256)
            self.assertEqual(restored.generated_java, candidate.generated_java)
            candidate_payload = json.loads(
                (root / "run" / "candidates" / candidate.id / "candidate.json").read_text()
            )
            self.assertEqual(candidate_payload["candidate_schema_version"], "eagle-candidate-v8")
            self.assertNotIn("strategy_policy_format", candidate_payload)
            self.assertEqual(
                candidate_payload["artifacts"]["control_genome"],
                "genotype/control_genome.json",
            )

    def test_loader_rejects_bundle_genome_and_provenance_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, config, _ = self.initialize_run(root)
            candidate = self.write_seed_candidate(root / "run", config)
            candidate_dir = root / "run" / "candidates" / candidate.id

            genome_path = candidate_dir / "genotype" / "control_genome.json"
            original_genome = genome_path.read_bytes()
            genome_path.write_text('{"horizon":8}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence mismatch: control_genome"):
                load_candidate(root / "run", candidate.id)
            genome_path.write_bytes(original_genome)

            candidate_path = candidate_dir / "candidate.json"
            candidate_payload = json.loads(candidate_path.read_text())
            candidate_payload["slot_parent_ids"] = {"horizon": "not_a_parent"}
            candidate_path.write_text(json.dumps(candidate_payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Generation-zero"):
                load_candidate(root / "run", candidate.id)

            candidate_payload["slot_parent_ids"] = {}
            candidate_path.write_text(json.dumps(candidate_payload), encoding="utf-8")
            bundle_path = root / "run" / FRAMEWORK_BUNDLE_ARTIFACT
            bundle_path.write_bytes(bundle_path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "bundle hash mismatch"):
                load_candidate(root / "run", candidate.id)

    def test_failed_materialization_persists_null_derived_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, config, _ = self.initialize_run(root)
            candidate = Candidate(
                id="gen_0000_failed_framework",
                generation=0,
                candidate_java_mode="generated_phenotype",
                java_materialization_mode="framework_slots",
                java_compiler_version=config.java_compiler_version,
                control_genome={"horizon": 6},
                slot_parent_ids={},
                framework_bundle_sha256=config.framework_bundle_sha256,
                generation_prompt="",
                compile_status="failed",
                status="failed",
                failure_stage="materialization",
                failure_reason="bundle unavailable",
            )
            evidence = {
                "schema_version": "eagle-framework-materialization-v1",
                "operation": "framework_slot_assembly",
                "materialization_mode": "framework_slots",
                "materialization_version": config.java_compiler_version,
                "framework_id": None,
                "framework_bundle_sha256": config.framework_bundle_sha256,
                "canonical_bundle_sha256": None,
                "template_sha256": None,
                "genome_sha256": None,
                "source_sha256": None,
                "control_genome": dict(candidate.control_genome),
                "slot_parent_ids": {},
            }
            evaluation = SimpleNamespace(
                candidate=candidate,
                generation_timing=evidence,
                generation_attempts=(),
                compile_result=None,
                result=SimpleNamespace(
                    assembled_java="",
                    failure_category="materialization",
                    failure_reason="bundle unavailable",
                    validation_result=None,
                ),
            )

            candidate_dir = root / "run" / "candidates" / candidate.id
            write_candidate_inputs(root / "run" / "candidates", candidate)
            _write_generation_artifacts(candidate_dir, evaluation)
            write_candidate_snapshot(root / "run" / "candidates", candidate)

            persisted = json.loads(
                (candidate_dir / "generation" / "framework_evidence.json").read_text()
            )
            self.assertIsNone(persisted["framework_id"])
            self.assertIsNone(persisted["source_sha256"])
            self.assertEqual(persisted["control_genome"], candidate.control_genome)
            restored = load_candidate(root / "run", candidate.id)
            self.assertEqual(restored.status, "failed")
            self.assertEqual(restored.control_genome, candidate.control_genome)

    def test_resume_uses_frozen_bundle_and_never_generates_a_framework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, source_config, frozen, _ = self.initialize_run(root)
            with patch(
                "eagle.generation.gemini_framework.generate_framework_bundle"
            ) as generate:
                persisted = load_resume_config(root / "run")
            generate.assert_not_called()
            self.assertEqual(
                persisted.framework_bundle_path,
                (root / "run" / FRAMEWORK_BUNDLE_ARTIFACT).resolve(),
            )
            validate_resume_config(source_config, frozen)

            manifest_path = root / "run" / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["evolution_protocol"] = "legacy-framework-protocol"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "protocol mismatch"):
                load_resume_config(root / "run")


if __name__ == "__main__":
    unittest.main()
