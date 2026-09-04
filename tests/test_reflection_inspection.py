from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.reflection_inspection import (
    INSPECTION_SCHEMA_VERSION,
    ReflectionInspectionConfig,
    run_reflection_inspection,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "reflection_inspections" / "0903_worker_rush" / "inspection.yaml"
CHAINED_CONFIG = (
    ROOT
    / "configs"
    / "reflection_inspections"
    / "0904_prompt_compliance_children"
    / "inspection.yaml"
)


class ReflectionInspectionTests(unittest.TestCase):
    def test_checked_in_config_runs_nine_independent_mock_trials(self) -> None:
        inspection = ReflectionInspectionConfig.from_file(CONFIG)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "inspection"
            result = run_reflection_inspection(inspection, mock=True, output_dir=output)

            self.assertEqual(len(result.trial_summaries), 9)
            self.assertTrue(result.all_trials_match_expected_scope)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["schema_version"], INSPECTION_SCHEMA_VERSION)
            self.assertTrue(summary["all_trials_match_expected_scope"])
            self.assertEqual(
                [item["reflection_type"] for item in summary["groups"]],
                ["strategy", "code", "prompt_compliance"],
            )
            self.assertTrue(all(item["same_context_across_trials"] for item in summary["groups"]))
            self.assertTrue(all(item["same_root_requests_across_trials"] for item in summary["groups"]))
            self.assertTrue(all(item["same_pipeline_requests_across_trials"] for item in summary["groups"]))
            self.assertEqual(
                sum(item["response_attempt_count"] for item in summary["groups"]),
                48,
            )

            strategy = summary["trials"][0]
            code = summary["trials"][3]
            compliance = summary["trials"][6]
            self.assertEqual(strategy["actual_changed_fields"], ["strategy_prompt"])
            self.assertEqual(code["actual_changed_fields"], ["generation_prompt"])
            self.assertEqual(
                compliance["actual_changed_fields"],
                ["strategy_prompt", "generation_prompt"],
            )
            self.assertEqual(strategy["response_attempt_count"], 11)
            self.assertEqual(code["response_attempt_count"], 2)
            self.assertEqual(compliance["response_attempt_count"], 3)

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
                    / "coach_raw.txt"
                ).is_file()
            )

    def test_chained_inspection_feeds_successful_strategy_and_code_children_to_compliance(self) -> None:
        inspection = ReflectionInspectionConfig.from_file(CHAINED_CONFIG)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "inspection"
            result = run_reflection_inspection(inspection, mock=True, output_dir=output)

            self.assertEqual(len(result.trial_summaries), 12)
            self.assertTrue(result.all_trials_match_expected_scope)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(
                summary["prompt_compliance_parent_mode"],
                "successful_strategy_and_code_children",
            )
            self.assertEqual(
                summary["prompt_compliance_parent_sources"]["counts"],
                {"strategy": 3, "code": 3},
            )
            self.assertTrue(
                summary["prompt_compliance_parent_sources"][
                    "all_required_source_types_present"
                ]
            )
            compliance = [
                item
                for item in summary["trials"]
                if item["reflection_type"] == "prompt_compliance"
            ]
            self.assertEqual(len(compliance), 6)
            self.assertEqual(
                [item["source_reflection_type"] for item in compliance],
                ["strategy", "strategy", "strategy", "code", "code", "code"],
            )
            for item in compliance:
                source_summary = json.loads(
                    (output / item["source_trial_artifact"]).read_text(encoding="utf-8")
                )
                self.assertEqual(source_summary["mutation_status"], "applied")
                self.assertEqual(
                    item["input_genotype_sha256"],
                    source_summary["output_genotype_sha256"],
                )
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["trial_count_expected"], 12)
            self.assertEqual(manifest["trial_count_completed"], 12)
            self.assertTrue(manifest["all_required_parent_sources_present"])

    def test_chained_mode_requires_upstream_reflections_before_compliance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inspection.yaml"
            path.write_text(
                "\n".join(
                    [
                        f"schema_version: {INSPECTION_SCHEMA_VERSION}",
                        "name: invalid_chained_order",
                        f"experiment_config: {CONFIG.parent / 'worker_rush_base.yaml'}",
                        "reflection_order: [prompt_compliance, strategy, code]",
                        "prompt_compliance_parent_mode: successful_strategy_and_code_children",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "requires reflection_order"):
                ReflectionInspectionConfig.from_file(path)

    def test_config_rejects_missing_reflection_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inspection.yaml"
            path.write_text(
                "\n".join(
                    [
                        f"schema_version: {INSPECTION_SCHEMA_VERSION}",
                        "name: invalid",
                        f"experiment_config: {CONFIG.parent / 'worker_rush_base.yaml'}",
                        "reflection_order: [strategy, code]",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly once"):
                ReflectionInspectionConfig.from_file(path)


if __name__ == "__main__":
    unittest.main()
