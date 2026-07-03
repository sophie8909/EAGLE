import unittest

from eagle.eval.microrts.response_validator import validate_llm_response


class ResponseValidatorTests(unittest.TestCase):
    def test_validates_schema_and_state_backed_move(self) -> None:
        response = """
        notes
        {
          "thinking": "train from idle base",
          "moves": [
            {
              "raw_move": "(2,1): base train(worker)",
              "unit_position": [2, 1],
              "unit_type": "base",
              "action_type": "train"
            }
          ]
        }
        """
        state = """
        Map size: 8x8
        Feature locations:
        (2, 1) Ally Base Unit {resources=5, current_action="idling", HP=10}
        """

        result = validate_llm_response(response, state)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.legality_level, "state_checked")
        self.assertEqual(result.valid_moves[0]["unit_type"], "base")

    def test_returns_schema_only_when_state_unavailable(self) -> None:
        response = '{"thinking":"ok","moves":[{"raw_move":"(1,1): worker move(1,2)","unit_position":[1,1],"unit_type":"worker","action_type":"move"}]}'

        result = validate_llm_response(response, None)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.legality_level, "schema_only")
        self.assertEqual(len(result.valid_moves), 1)

    def test_filters_invalid_moves_but_keeps_valid_moves(self) -> None:
        response = '{"thinking":"mixed","moves":[{"raw_move":"(1,1): worker harvest((0,0),(2,1))","unit_position":[1,1],"unit_type":"worker","action_type":"harvest"},{"raw_move":"(3,3): worker move(3,4)","unit_position":[3,3],"unit_type":"worker","action_type":"attack"}]}'

        result = validate_llm_response(response, None)

        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.valid_moves), 1)
        self.assertIn("action_type does not match raw_move action", result.errors[0])

    def test_rejects_busy_or_wrong_type_units(self) -> None:
        response = '{"thinking":"bad","moves":[{"raw_move":"(1,1): worker move(1,2)","unit_position":[1,1],"unit_type":"worker","action_type":"move"},{"raw_move":"(2,1): worker move(2,2)","unit_position":[2,1],"unit_type":"worker","action_type":"move"}]}'
        state = """
        Map size: 8x8
        Feature locations:
        (1, 1) Ally Worker Unit {current_action="harvesting", HP=1}
        (2, 1) Ally Base Unit {resources=5, current_action="idling", HP=10}
        """

        result = validate_llm_response(response, state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.valid_moves, [])
        self.assertTrue(any("not idle/actionable" in error for error in result.errors))
        self.assertTrue(any("unit_type mismatch" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
