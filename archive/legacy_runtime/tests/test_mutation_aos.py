import unittest
from types import SimpleNamespace

from eagle.operators.mutation import support


def _config(mode="aos"):
    return SimpleNamespace(
        mutation_selection_mode=mode,
        strategy_mutation_mode_weights=lambda: {
            "bitmask_flip": 0.25,
            "identity_preserving_rewrite": 0.25,
            "identity_shift_rewrite": 0.25,
            "pool_replacement": 0.25,
        }
    )


class MutationAOSTests(unittest.TestCase):
    def setUp(self) -> None:
        support._mutation_component_weights.clear()

    def test_initializes_all_active_mutation_weights_to_ten(self) -> None:
        self.assertEqual(
            support.current_mutation_weights(_config()),
            {
                "bitmask_flip": 10.0,
                "identity_preserving_rewrite": 10.0,
                "identity_shift_rewrite": 10.0,
                "pool_replacement": 10.0,
            },
        )

    def test_updates_only_selected_operator_by_success_reward(self) -> None:
        support.current_mutation_weights(_config())

        support.update_mutation_component_feedback("bitmask_flip", 1.0, 2.0)

        weights = support.current_mutation_weights(_config())
        self.assertEqual(weights["bitmask_flip"], 11.0)
        self.assertEqual(weights["identity_preserving_rewrite"], 10.0)

    def test_samples_with_runtime_weights(self) -> None:
        support._mutation_component_weights.update(
            {
                "bitmask_flip": 3.0,
                "identity_preserving_rewrite": 5.0,
                "identity_shift_rewrite": 7.0,
                "pool_replacement": 11.0,
            }
        )
        observed = {}
        original_choices = support.random.choices

        def fake_choices(modes, *, weights, k):
            observed["modes"] = list(modes)
            observed["weights"] = list(weights)
            observed["k"] = k
            return ["pool_replacement"]

        support.random.choices = fake_choices
        try:
            selected = support.sample_mutation_mode(_config())
        finally:
            support.random.choices = original_choices

        self.assertEqual(selected, "pool_replacement")
        self.assertEqual(observed["weights"], [3.0, 5.0, 7.0, 11.0])
        self.assertEqual(observed["k"], 1)

    def test_fixed_mode_samples_uniformly_without_weights(self) -> None:
        observed = {}
        original_choice = support.random.choice

        def fake_choice(modes):
            observed["modes"] = list(modes)
            return "identity_shift_rewrite"

        support.random.choice = fake_choice
        try:
            selected = support.sample_mutation_mode(_config("fixed"))
        finally:
            support.random.choice = original_choice

        self.assertEqual(selected, "identity_shift_rewrite")
        self.assertEqual(
            observed["modes"],
            [
                "bitmask_flip",
                "identity_preserving_rewrite",
                "identity_shift_rewrite",
                "pool_replacement",
            ],
        )
        self.assertEqual(support._mutation_component_weights, {})

    def test_decays_selected_operator_and_clamps_to_one(self) -> None:
        support._mutation_component_weights["pool_replacement"] = 1.05

        support.update_mutation_component_feedback("pool_replacement", 2.0, 1.0)

        self.assertEqual(
            support.current_mutation_weights(_config())["pool_replacement"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
