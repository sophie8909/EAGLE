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
                ["strategy", "prompt", "code"],
            )
            self.assertTrue(all(item["same_context_across_trials"] for item in summary["groups"]))
            self.assertTrue(all(item["same_root_requests_across_trials"] for item in summary["groups"]))
            self.assertTrue(all(item["same_pipeline_requests_across_trials"] for item in summary["groups"]))
            self.assertEqual(
                sum(item["response_attempt_count"] for item in summary["groups"]),
                45,
            )

            strategy = summary["trials"][0]
            prompt = summary["trials"][3]
            code = summary["trials"][6]
            self.assertEqual(strategy["actual_changed_fields"], ["strategy_prompt"])
            self.assertEqual(prompt["actual_changed_fields"], ["generation_prompt"])
            self.assertEqual(code["actual_changed_fields"], ["generated_java"])
            self.assertEqual(strategy["response_attempt_count"], 11)
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
                    / "coach_raw.txt"
                ).is_file()
            )

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
