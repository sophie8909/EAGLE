import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from eagle.evolution.component.base import EA
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

    def test_can_switch_to_runtime_pool_file(self) -> None:
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

        with TemporaryDirectory() as tmp_dir:
            pool_path = Path(tmp_dir) / "examples_pool.jsonl"
            memory.set_pool_path(pool_path)

            self.assertTrue(pool_path.exists())
            self.assertIn("base train(worker)", pool_path.read_text(encoding="utf-8"))

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

    def test_few_shot_controls_disable_or_sample_examples(self) -> None:
        pool = ComponentPool(
            {
                "field_requirements": [["FIELDS"]],
                "json_schema": [["SCHEMA"]],
            }
        )
        examples = [
            {"name": "one", "content": ["OUTPUT:", "{\"moves\": []}"]},
            {"name": "two", "content": ["OUTPUT:", "{\"thinking\": \"two\", \"moves\": []}"]},
        ]

        disabled_prompt = "\n".join(
            pool.render_prompt_lines(
                {"field_requirements": 0, "json_schema": 0},
                selected_training_examples=examples,
                use_few_shot_examples=False,
                min_examples=1,
                max_examples=1,
            )
        )
        sampled_prompt = "\n".join(
            pool.render_prompt_lines(
                {"field_requirements": 0, "json_schema": 0},
                selected_training_examples=examples,
                use_few_shot_examples=True,
                min_examples=1,
                max_examples=1,
            )
        )

        self.assertNotIn("OUTPUT:", disabled_prompt)
        self.assertEqual(sampled_prompt.count("OUTPUT:"), 1)

    def test_example_crossover_pads_shorter_parent_with_empty_slots(self) -> None:
        algorithm = object.__new__(EA)
        algorithm.config = SimpleNamespace(max_examples=3)
        left = Individual()
        right = Individual()
        left.training_examples = [
            {"name": "left_1", "content": ["LEFT 1"]},
            {"name": "left_2", "content": ["LEFT 2"]},
        ]
        right.training_examples = [{"name": "right_1", "content": ["RIGHT 1"]}]

        child_examples = algorithm._uniform_crossover_training_examples(left, right)

        self.assertLessEqual(len(child_examples), 2)
        self.assertTrue(all(not example.get("_empty_example") for example in child_examples))

    def test_example_mutation_replaces_current_example_from_memory(self) -> None:
        algorithm = object.__new__(EA)
        algorithm.config = SimpleNamespace(max_examples=2)
        algorithm.example_memory = ExampleMemory(max_examples=4)
        algorithm.example_memory.add_examples(
            [
                {
                    "raw_move": "(3,1): base train(worker)",
                    "unit_position": [3, 1],
                    "unit_type": "base",
                    "action_type": "train",
                }
            ]
        )
        current_examples = [
            {
                "name": "old",
                "moves": [
                    {
                        "raw_move": "(1,1): worker move(1,2)",
                        "unit_position": [1, 1],
                        "unit_type": "worker",
                        "action_type": "move",
                    }
                ],
                "content": ["OLD"],
            }
        ]

        mutated = algorithm._mutate_training_examples_from_memory(current_examples)

        self.assertEqual(len(mutated), 1)
        self.assertEqual(mutated[0]["moves"][0]["raw_move"], "(3,1): base train(worker)")

    def test_example_mutation_can_generate_fresh_example_from_previous_round(self) -> None:
        algorithm = object.__new__(EA)
        algorithm.config = SimpleNamespace(max_examples=2)
        algorithm.example_memory = ExampleMemory(max_examples=4)
        parent = Individual()
        parent.last_round_evaluation = {
            "samples": [
                {
                    "format_valid": True,
                    "parsed_response": {
                        "moves": [
                            {
                                "raw_move": "(4,1): base train(worker)",
                                "unit_position": [4, 1],
                                "unit_type": "base",
                                "action_type": "train",
                            }
                        ]
                    },
                },
                {
                    "format_valid": True,
                    "parsed_response": {
                        "moves": [
                            {
                                "raw_move": "(5,1): worker build(barracks)",
                                "unit_position": [5, 1],
                                "unit_type": "worker",
                                "action_type": "build",
                            }
                        ]
                    },
                },
            ]
        }
        current_examples = [
            {
                "name": "old",
                "moves": [
                    {
                        "raw_move": "(1,1): worker move(1,2)",
                        "unit_position": [1, 1],
                        "unit_type": "worker",
                        "action_type": "move",
                    }
                ],
                "content": ["OLD"],
            },
            {
                "name": "old_2",
                "moves": [
                    {
                        "raw_move": "(2,1): worker move(2,2)",
                        "unit_position": [2, 1],
                        "unit_type": "worker",
                        "action_type": "move",
                    }
                ],
                "content": ["OLD 2"],
            }
        ]

        with patch("eagle.evolution.component.base.random.choices", return_value=["fresh"]):
            mutated = algorithm._mutate_training_examples_from_memory(
                current_examples,
                source_individual=parent,
            )

        self.assertEqual(
            [example["moves"][0]["raw_move"] for example in mutated],
            ["(4,1): base train(worker)", "(5,1): worker build(barracks)"],
        )
        self.assertEqual(len(algorithm.example_memory.examples), 2)

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
