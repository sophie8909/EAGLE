import json
import tempfile
import unittest
from pathlib import Path

from eagle.llm_stability import (
    run_stability_test,
    write_stability_matrix,
    write_stability_report,
)


class LLMStabilityTests(unittest.TestCase):
    def test_identical_responses_are_stable_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_stability_test(lambda: "same response", repeats=3)
            report_path = write_stability_report(Path(temp), result, metadata={"seed": 7})
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(result.stable)
            self.assertEqual(payload["unique_response_count"], 1)
            self.assertEqual(payload["seed"], 7)
            self.assertEqual(
                (Path(temp) / "responses" / "response_001.txt").read_text(encoding="utf-8"),
                "same response",
            )

    def test_different_responses_are_reported_as_unstable(self):
        responses = iter(("first", "second", "third"))
        result = run_stability_test(lambda: next(responses), repeats=3)
        self.assertFalse(result.stable)
        self.assertEqual(len(set(result.response_hashes)), 3)

    def test_repeats_must_include_a_comparison(self):
        with self.assertRaises(ValueError):
            run_stability_test(lambda: "response", repeats=1)

    def test_matrix_separates_same_seed_stability_from_cross_seed_change(self):
        with tempfile.TemporaryDirectory() as temp:
            results = {
                7: run_stability_test(lambda: "response-a", repeats=2),
                8: run_stability_test(lambda: "response-b", repeats=2),
            }
            report_path = write_stability_matrix(
                Path(temp),
                results,
                matrix_metadata={"server_restart_per_seed": True},
            )
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["same_seed_stable"])
            self.assertTrue(payload["cross_seed_changed"])
            self.assertTrue(payload["server_restart_per_seed"])
            self.assertEqual(payload["seeds"], [7, 8])
            self.assertTrue((Path(temp) / "seed_7" / "stability_report.json").is_file())


if __name__ == "__main__":
    unittest.main()
