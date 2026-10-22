from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from eagle.reflection_inspection import (
    INSPECTION_SCHEMA_VERSION,
    ReflectionInspectionConfig,
    run_reflection_inspection,
)
from eagle.config import ExperimentConfig


class ReflectionInspectionTests(unittest.TestCase):
    def test_checked_in_config_runs_nine_independent_mock_trials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment_config = root / "worker_rush_base.yaml"
            experiment_config.write_text(
                yaml.safe_dump(
                    ExperimentConfig.from_mapping({
                        "candidate_java_mode": "inherited_genotype",
                        "initial_java_seed_path": "eagle/java_seeds/worker_rush/CandidateAgent.java",
                    }).to_mapping()
                ),
                encoding="utf-8",
            )
            inspection_path = root / "inspection.yaml"
            inspection_path.write_text(
                yaml.safe_dump({
                    "schema_version": INSPECTION_SCHEMA_VERSION,
                    "name": "worker_rush_three_reflections",
                    "experiment_config": str(experiment_config),
                    "output_root": "runs/reflection_inspections",
                    "trials_per_reflection": 3,
                    "strategy_mutation_intent": "REFINE",
                    "reflection_order": ["strategy", "prompt", "code"],
                }),
                encoding="utf-8",
            )
            inspection = ReflectionInspectionConfig.from_file(inspection_path)
            output = Path(temp_dir) / "inspection"
            result = run_reflection_inspection(inspection, mock=True, output_dir=output)

            self.assertEqual(len(result.trial_summaries), 9)
            self.assertTrue(result.all_trials_match_expected_scope)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["schema_version"], INSPECTION_SCHEMA_VERSION)
            self.assertTrue(summary["all_trials_match_expected_scope"])
            self.assertEqual(
                [item["reflection_type"] for item in summary["groups"]],
                ["strategy", "prompt", "code"],
            )
            self.assertTrue(all(item["same_context_across_trials"] for item in summary["groups"]))
            self.assertTrue(all(item["same_root_requests_across_trials"] for item in summary["groups"]))
            self.assertTrue(all(item["same_pipeline_requests_across_trials"] for item in summary["groups"]))
            self.assertEqual(
                sum(item["response_attempt_count"] for item in summary["groups"]),
                18,
            )

            strategy = summary["trials"][0]
            prompt = summary["trials"][3]
            code = summary["trials"][6]
            self.assertEqual(strategy["actual_changed_fields"], ["strategy_prompt"])
            self.assertEqual(prompt["actual_changed_fields"], ["generation_prompt"])
            self.assertEqual(code["actual_changed_fields"], ["generated_java"])
            self.assertEqual(strategy["response_attempt_count"], 2)
            self.assertEqual(prompt["response_attempt_count"], 2)
            self.assertEqual(code["response_attempt_count"], 2)

            fixed = json.loads(
                (output / "inputs" / "fixed_input_identity.json").read_text(encoding="utf-8")
            )
            self.assertIn("java_source", fixed)
            self.assertTrue((output / "summary.md").is_file())
            self.assertTrue(
                (
                    output
                    / "trials"
                    / "strategy"
                    / "trial_01"
                    / "mutation"
                    / "strategy_reflection"
                    / "coach_response_attempt_001.json"
                ).is_file()
            )
            referenced_artifacts: list[str] = []

            def collect_references(value: object) -> None:
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in {
                            "artifact_refs",
                            "selected_attempt_artifacts",
                            "representative_attempt_artifacts",
                        } and isinstance(item, dict):
                            referenced_artifacts.extend(
                                reference
                                for reference in item.values()
                                if isinstance(reference, str)
                            )
                        collect_references(item)
                elif isinstance(value, list):
                    for item in value:
                        collect_references(item)

            for path in output.rglob("*.json"):
                collect_references(json.loads(path.read_text(encoding="utf-8")))
            self.assertTrue(list((output / "llm_logs").glob("*.json")))
            self.assertTrue(referenced_artifacts)
            for reference in referenced_artifacts:
                self.assertFalse(Path(reference).is_absolute(), reference)
                self.assertTrue((output / reference).is_file(), reference)

    def test_config_rejects_missing_reflection_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment_config = root / "worker_rush_base.yaml"
            experiment_config.write_text(
                yaml.safe_dump(
                    ExperimentConfig.from_mapping({
                        "candidate_java_mode": "inherited_genotype",
                        "initial_java_seed_path": "eagle/java_seeds/worker_rush/CandidateAgent.java",
                    }).to_mapping()
                ),
                encoding="utf-8",
            )
            path = root / "inspection.yaml"
            path.write_text(
                "\n".join(
                    [
                        f"schema_version: {INSPECTION_SCHEMA_VERSION}",
                        "name: invalid",
                        f"experiment_config: {experiment_config}",
                        "reflection_order: [strategy, code]",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly once"):
                ReflectionInspectionConfig.from_file(path)


if __name__ == "__main__":
    unittest.main()
