import unittest

from scripts.test_llm_seed_restarts import _parse_seeds


class LLMSeedRestartTests(unittest.TestCase):
    def test_parse_distinct_integer_seeds(self):
        self.assertEqual(_parse_seeds("7, 8,9"), (7, 8, 9))

    def test_parse_rejects_duplicate_seeds(self):
        with self.assertRaises(SystemExit):
            _parse_seeds("7,7")


if __name__ == "__main__":
    unittest.main()
