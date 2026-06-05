"""Regression tests for MicroRTS experiment prompt selection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle_ui import services


class MicroRTSPromptSelectionTests(unittest.TestCase):
    def test_load_experiment_prompt_records_keeps_generation_and_individual_choices(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            rows = [
                {
                    "generation": 0,
                    "phase": "initial_population",
                    "individual": {"id": "ind-a", "rendered_prompt": "prompt gen 1 ind a"},
                },
                {
                    "generation": 1,
                    "phase": "generation_complete",
                    "individual": {"id": "ind-b", "rendered_prompt": "prompt gen 2 ind b"},
                },
                {
                    "generation": 1,
                    "phase": "generation_complete",
                    "individual": {"id": "ind-c", "rendered_prompt": "prompt gen 2 ind c"},
                },
            ]
            (run_dir / "checkpoints.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows),
                encoding="utf-8",
            )

            records = services.load_experiment_prompt_records(run_dir)

        self.assertEqual(services.prompt_generation_choices(records), ["1", "2"])
        self.assertEqual(services.prompt_individual_choices(records, "2"), ["ind-b", "ind-c"])
        selected = services.selected_prompt_record(records, "2", "ind-c")
        self.assertIsNotNone(selected)
        self.assertEqual(selected["prompt"], "prompt gen 2 ind c")


if __name__ == "__main__":
    unittest.main()
