import unittest

from eagle.eval.microrts.round_evaluator import Evaluator


class RoundEvaluatorJsonParsingTests(unittest.TestCase):
    """Parser coverage for noisy or invalid round-evaluator LLM responses."""

    def test_extracts_first_embedded_json_object(self) -> None:
        raw_output = 'notes before {"thinking": "ok", "moves": []} {"ignored": true}'

        parsed = Evaluator._extract_first_json_object(raw_output)

        self.assertEqual(parsed, {"thinking": "ok", "moves": []})

    def test_invalid_json_returns_none(self) -> None:
        raw_output = '{"thinking": "broken", "moves": [}'

        parsed = Evaluator._extract_first_json_object(raw_output)

        self.assertIsNone(parsed)

    def test_non_object_json_returns_none(self) -> None:
        parsed = Evaluator._extract_first_json_object('[{"thinking": "ok"}]')

        self.assertIsNone(parsed)


if __name__ == "__main__":
    unittest.main()
