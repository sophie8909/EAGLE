"""Regression tests for canonical config loading and resolved run configs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eagle.config import (
    RESOLVED_CONFIG_FILENAME,
    config_to_section_payload,
    config_to_payload,
    load_config_from_json,
    load_config_payload,
    load_resume_config,
    resolve_config,
    resolve_config_path,
    save_resolved_config,
    select_config_path,
)
from eagle.envs.microrts.compiler import locate_microrts_root
from eagle_ui import services
from eagle_ui.state import AppState


class ConfigResolutionTests(unittest.TestCase):
    def test_default_config_can_be_built_and_resolved(self) -> None:
        config = resolve_config(load_config_payload({}))

        self.assertEqual(config.application, "microrts")
        self.assertEqual(config.evaluator, "gameplay")
        self.assertTrue(resolve_config_path(config.component_pool_path).exists())

    def test_gui_generated_config_can_be_validated_and_resolved(self) -> None:
        state = AppState()
        base_path = Path(state.config.base_config_path)
        services.apply_config_payload(state, services.load_config_payload(base_path), base_path)

        payload = services.build_config_payload(state)
        config = resolve_config(load_config_payload(payload), base_dir=base_path.parent)

        self.assertEqual(config_to_payload(config)["algorithm"], state.config.algorithm)
        self.assertTrue(resolve_config_path(config.component_pool_path).exists())

    def test_resolved_config_is_saved_and_preferred_for_run_loads(self) -> None:
        config = resolve_config(
            load_config_payload(
                {
                    "algorithm": "ga",
                    "objective_config": {"mode": "single", "objective": "resource_advantage"},
                }
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            resolved_path = save_resolved_config(config, run_dir)

            self.assertEqual(resolved_path.name, RESOLVED_CONFIG_FILENAME)
            self.assertEqual(select_config_path(run_dir).name, RESOLVED_CONFIG_FILENAME)
            loaded = load_config_from_json(run_dir)

        self.assertEqual(loaded.algorithm, "ga")
        self.assertEqual(loaded.objective_config, {"mode": "single", "objective": "resource_advantage"})

    def test_resume_config_loads_existing_run_without_creating_new_folder(self) -> None:
        config = resolve_config(
            load_config_payload(
                {
                    "algorithm": "ga",
                    "objective_config": {"mode": "single", "objective": "resource_advantage"},
                }
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "existing_run"
            save_resolved_config(config, run_dir)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

            loaded = load_resume_config(run_dir)
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

        self.assertEqual(loaded.algorithm, "ga")
        self.assertEqual(before, after)

    def test_sectioned_config_view_exposes_runtime_boundaries(self) -> None:
        config = resolve_config(load_config_payload({}))
        with tempfile.TemporaryDirectory() as temp_dir:
            sections = config_to_section_payload(config, run_dir=Path(temp_dir) / "run_a")

        self.assertEqual(sections["experiment"]["mode"], "multi")
        self.assertEqual(sections["algorithm"]["algorithm_name"], config.algorithm)
        self.assertEqual(sections["llm"]["base_url"], config.llm_base_url)
        self.assertTrue(sections["microrts"]["enabled"])
        self.assertTrue(resolve_config_path(sections["components"]["prompt_components_path"]).exists())

    def test_recent_old_experiment_envelope_loads(self) -> None:
        config = load_config_payload(
            {
                "algorithm": "ga",
                "opponents": ["ai.RandomAI"],
                "ea": {
                    "objective_config": {"mode": "single", "objective": "resource_advantage"},
                },
            }
        )

        self.assertEqual(config.algorithm, "ga")
        self.assertEqual(config.gameplay_opponents, ["ai.RandomAI"])

    def test_recent_old_llm_intervals_key_loads(self) -> None:
        config = load_config_payload({"llm_intervals": [1, 10]})

        self.assertEqual(config.llm_interval, [1, 10])

    def test_recent_old_envelope_llm_intervals_key_loads(self) -> None:
        config = load_config_payload({"llm_intervals": [1, 10], "ea": {}})

        self.assertEqual(config.llm_interval, [1, 10])

    def test_microrts_paths_resolve_from_project_config(self) -> None:
        self.assertTrue(locate_microrts_root().exists())
        self.assertTrue(resolve_config_path("third_party/microrts").exists())

    def test_single_and_multi_objective_modes_parse(self) -> None:
        single = load_config_payload(
            {
                "algorithm": "ga",
                "objective_config": {"mode": "single", "objective": "resource_advantage"},
            }
        )
        multi = load_config_payload(
            {
                "algorithm": "nsga2",
                "objective_config": {"mode": "multi", "objectives": ["resource_advantage", "win_score"]},
            }
        )

        self.assertEqual(single.objective_config["mode"], "single")
        self.assertEqual(multi.objective_config["mode"], "multi")


if __name__ == "__main__":
    unittest.main()
