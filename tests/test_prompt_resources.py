from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from eagle.config import DEFAULT_SEED_POLICY_PATH, ExperimentConfig
from eagle.prompts import (
    DEFAULT_PROMPT_DIR,
    load_prompt,
    load_prompt_templates,
    render_prompt,
    save_prompt_template,
)


class PromptResourceTests(unittest.TestCase):
    def test_initial_strategy_is_a_concrete_worker_rush_policy(self) -> None:
        policy = load_prompt("initial_strategy")
        self.assertIn("continuously produce Workers", policy)
        self.assertIn("harvest", policy)
        self.assertIn("attack the enemy Base", policy)
        self.assertNotIn("Define a concrete", policy)
        for coach_name in ("coach_refine", "coach_counter", "coach_structural", "coach_alternative"):
            coach = load_prompt_templates()[coach_name].template
            self.assertIn("concrete game-playing policy itself", coach)

    def test_every_prompt_is_one_registered_text_file(self) -> None:
        templates = load_prompt_templates()
        registered = {template.source_path.resolve() for template in templates.values()}
        text_files = {path.resolve() for path in DEFAULT_PROMPT_DIR.glob("*.txt")}
        self.assertEqual(registered, text_files)
        self.assertEqual(len(registered), len(templates))
        for template in templates.values():
            self.assertEqual(template.source_path.suffix, ".txt")
            self.assertEqual(template.placeholders, tuple(dict.fromkeys(template.required_variables)))
            self.assertTrue(template.render(template.mock_context()).strip())

    def test_prompt_bodies_are_not_embedded_in_runtime_python(self) -> None:
        runtime_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for package in (Path("eagle"), Path("evaluation"), Path("generation"))
            for path in package.rglob("*.py")
        )
        for path in DEFAULT_PROMPT_DIR.glob("*.txt"):
            body = path.read_text(encoding="utf-8").strip()
            self.assertNotIn(body, runtime_sources, path.name)

    def test_save_updates_only_selected_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.toml").write_text(
                "[prompts.example]\n"
                'file = "example.txt"\n'
                'role = "seed"\n'
                'stages = ["population_initialization"]\n'
                'required_variables = ["value"]\n',
                encoding="utf-8",
            )
            (root / "example.txt").write_text("before $value\n", encoding="utf-8")
            save_prompt_template("example", "after $value", path=root)
            self.assertEqual(render_prompt("example", {"value": "ok"}, path=root), "after ok")

    def test_production_configs_use_file_backed_policies_and_checked_in_java_seed(self) -> None:
        config_paths = sorted(Path("configs/experiments").glob("**/*.yaml"))
        self.assertTrue(config_paths)
        for path in config_paths:
            config = ExperimentConfig.from_file(path)
            self.assertTrue(config.seed_prompt_files, path)
            self.assertEqual(
                config.seed_prompts,
                tuple(
                    seed_path.read_text(encoding="utf-8").strip()
                    for seed_path in config.seed_prompt_files
                ),
                path,
            )
            self.assertEqual(config.generation_prompt_file, DEFAULT_PROMPT_DIR / "initial_generation.txt", path)
            self.assertEqual(config.generation_prompt, load_prompt("initial_generation"), path)
            self.assertEqual(
                config.initial_java_seed_path,
                Path("eagle/java_seeds/CandidateAgent.java").resolve(),
                path,
            )
            self.assertEqual(
                hashlib.sha256(config.initial_java_seed_path.read_bytes()).hexdigest(),
                "1d2361e34329ee7c6b21be5da431b61585d965ffebfc7572fb65cabe292ecf8b",
                path,
            )

    def test_static_0826_uses_three_distinct_seed_policies_and_equal_operator_weights(self) -> None:
        config = ExperimentConfig.from_file(
            "configs/experiments/static_0826/ministral3_8b_static_0.5_0.5.yaml"
        )
        self.assertEqual(
            config.seed_prompt_files,
            (
                DEFAULT_SEED_POLICY_PATH,
                Path("seeds/worker_rush_policy.txt").resolve(),
                Path("seeds/random_policy.txt").resolve(),
            ),
        )
        self.assertEqual(config.population_size, 3)
        self.assertEqual(config.survivor_selection, "mu_plus_lambda")
        self.assertEqual(config.strategy_reflection_probability, 0.5)
        self.assertEqual(config.code_reflection_probability, 0.5)
        self.assertEqual(config.initial_java_seed_path, Path("eagle/java_seeds/CandidateAgent.java").resolve())
        self.assertEqual(config.seed_prompts[0], "")
        self.assertIn("continuous Worker-rush", config.seed_prompts[1])
        self.assertIn("deterministic pseudo-random policy", config.seed_prompts[2])

    def test_survivor_selection_defaults_and_rejects_noncanonical_modes(self) -> None:
        config = ExperimentConfig.from_mapping({})
        self.assertEqual(config.survivor_selection, "mu_plus_lambda")
        self.assertEqual(config.to_mapping()["survivor_selection"], "mu_plus_lambda")
        with self.assertRaisesRegex(ValueError, "mu_plus_lambda"):
            ExperimentConfig.from_mapping({"survivor_selection": "offspring_first"})

    def test_inline_prompt_and_template_fields_are_rejected(self) -> None:
        for field, value in (
            ("seed_prompts", ["inline"]),
            ("seed_prompt_template", "legacy"),
            ("generation_prompt", "inline"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                ExperimentConfig.from_mapping({field: value})

    def test_obsolete_backend_and_derived_fields_are_rejected(self) -> None:
        for field, value in (
            ("generation_backend", "openai"),
            ("alignment_backend", "openai"),
            ("opponent", "ai.PassiveAI"),
            ("matches_per_candidate", 1),
            ("map_path", "map.xml"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                ExperimentConfig.from_mapping({field: value})
        with self.assertRaisesRegex(ValueError, "derived"):
            ExperimentConfig.from_mapping({"evaluation": {"matches_per_candidate": 126}})


if __name__ == "__main__":
    unittest.main()
