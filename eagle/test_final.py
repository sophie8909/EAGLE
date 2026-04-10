"""Top-level entry point for final EAGLE tests."""

from __future__ import annotations

import unittest

from eagle.eval import test_final_evaluation, test_final_test_summary


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None) -> unittest.TestSuite:
    """Aggregate the final-test related suites behind one stable entry point."""
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(test_final_evaluation))
    suite.addTests(loader.loadTestsFromModule(test_final_test_summary))
    return suite


if __name__ == "__main__":
    unittest.main()
