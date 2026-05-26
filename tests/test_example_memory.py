import unittest

from eagle.evolution.component.individual import Individual
from eagle.prompt.example_memory import ExampleMemory
from eagle.utils.component_pool import ComponentPool


class ExampleMemoryTests(unittest.TestCase):
    """Coverage for code-managed MicroRTS training examples."""

    def test_deduplicates_by_move_type_and_unit(self) -> None:
        memory = ExampleMemory(max_examples=4)
        move = {
            "raw_move": "(1,1): worker harvest((0,0),(2,1))",
            "unit_position": [1, 1],
            "unit_type": "Worker",
            "action_type": "Harvest",
        }

        self.assertEqual(memory.add_examples([move, dict(move)]), 1)

        self.assertEqual(len(memory.examples), 1)
        self.assertEqual(memory.examples[0]["moves"][0]["unit_type"], "worker")
        self.assertEqual(memory.examples[0]["moves"][0]["action_type"], "harvest")

    def test_keeps_pool_within_twenty_by_default(self) -> None:
        memory = ExampleMemory(max_examples=25)

        memory.add_examples(
            {
                "raw_move": f"({index},0): worker move({index},1)",
                "unit_position": [index, 0],
                "unit_type": "worker",
                "action_type": "move",
            }
            for index in range(25)
        )

        self.assertLessEqual(len(memory.examples), 20)

    def test_adds_examples_from_round_evaluation_samples(self) -> None:
        memory = ExampleMemory(max_examples=4)

        added = memory.add_from_round_evaluation(
            {
                "samples": [
                    {
                        "format_valid": True,
                        "dynamic_prompt": "Map size: 8x8",
                        "parsed_response": {
                            "thinking": "build worker",
                            "moves": [
                                {
                                    "raw_move": "(2,1): base train(worker)",
                                    "unit_position": [2, 1],
                                    "unit_type": "base",
                                    "action_type": "train",
                                }
                            ],
                        },
                    }
                ]
            }
        )

        self.assertEqual(added, 1)
        self.assertEqual(memory.examples[0]["moves"][0]["action_type"], "train")
        self.assertIn("INPUT:", memory.examples[0]["content"])
        self.assertIn("OUTPUT:", memory.examples[0]["content"])

    def test_renders_individual_examples_at_training_example_position(self) -> None:
        pool = ComponentPool(
            {
                "role": [["ROLE"]],
                "field_requirements": [["FIELDS"]],
                "json_schema": [["SCHEMA"]],
            }
        )
        individual = Individual()
        individual.set_component_index("role", 0)
        individual.set_component_index("field_requirements", 0)
        individual.set_component_index("json_schema", 0)
        individual.training_examples = ExampleMemory(max_examples=4).examples
        memory = ExampleMemory(max_examples=4)
        memory.add_examples(
            [
                {
                    "raw_move": "(2,1): base train(worker)",
                    "unit_position": [2, 1],
                    "unit_type": "base",
                    "action_type": "train",
                }
            ]
        )
        individual.training_examples = memory.examples

        prompt = "\n".join(
            pool.render_prompt_lines(
                individual.component_indices,
                selected_training_examples=individual.training_examples,
            )
        )

        self.assertIn("ROLE", prompt)
        self.assertIn("FIELDS", prompt)
        self.assertIn('"raw_move": "(2,1): base train(worker)"', prompt)
        self.assertIn('"unit_position": [', prompt)
        self.assertIn('"unit_type": "base"', prompt)
        self.assertIn('"action_type": "train"', prompt)
        self.assertIn("SCHEMA", prompt)

    def test_component_dict_does_not_emit_examples(self) -> None:
        pool = ComponentPool(
            {
                "metadata": {"non_evolving_component_keys": ["training_examples", "json_schema"]},
                "field_requirements": [["FIELDS"]],
                "training_examples": [{"name": "old", "content": ["OUTPUT:", "{}"]}],
                "json_schema": [["SCHEMA"]],
            }
        )

        payload = pool.to_component_dict()

        self.assertNotIn("training_examples", payload)
        self.assertNotIn("training_examples", payload["metadata"]["non_evolving_component_keys"])


if __name__ == "__main__":
    unittest.main()
