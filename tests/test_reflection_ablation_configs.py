from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig


CONFIG_DIR = Path("configs/experiments/0914_reflection_ablation_20x10")
BASE_CONFIG = Path(
    "configs/experiments/0912_parent_evaluation_comparison_20x10/"
    "01_reuse_cached_20x10.yaml"
)
EXPECTED_PROBABILITIES = {
    "01_without_strategy_reflection.yaml": (0.0, 0.5, 0.5),
    "02_without_prompt_reflection.yaml": (0.5, 0.0, 0.5),
    "03_without_code_reflection.yaml": (0.5, 0.5, 0.0),
}


class ReflectionAblationConfigTests(unittest.TestCase):
    def test_configs_disable_one_operator_and_split_the_remainder_evenly(self) -> None:
        paths = sorted(CONFIG_DIR.glob("*.yaml"))
        self.assertEqual([path.name for path in paths], list(EXPECTED_PROBABILITIES))

        for path in paths:
            config = ExperimentConfig.from_file(path)
            probabilities = (
                config.strategy_reflection_probability,
                config.prompt_reflection_probability,
                config.code_reflection_probability,
            )
            self.assertEqual(probabilities, EXPECTED_PROBABILITIES[path.name], path)
            self.assertEqual(sum(probabilities), 1.0, path)
            self.assertEqual(config.reflection_operator_mode.value, "static", path)
            self.assertEqual(config.parent_evaluation_mode, "reuse_cached", path)
            self.assertEqual(config.initial_population_mode, "llm_generated_policies", path)
            self.assertEqual(config.generations, 20, path)
            self.assertEqual(config.population_size, 10, path)
            self.assertEqual(config.model.parallel, 1, path)

    def test_configs_only_change_name_and_operator_probabilities_from_baseline(self) -> None:
        base = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8"))
        ignored_keys = {
            "experiment_name",
            "strategy_reflection_probability",
            "prompt_reflection_probability",
            "code_reflection_probability",
        }
        shared_base = {key: value for key, value in base.items() if key not in ignored_keys}

        for path in sorted(CONFIG_DIR.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            shared_payload = {
                key: value for key, value in payload.items() if key not in ignored_keys
            }
            self.assertEqual(shared_payload, shared_base, path)


if __name__ == "__main__":
    unittest.main()
