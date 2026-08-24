from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eagle.config import ExperimentConfig
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

    def test_production_configs_reference_initial_individual_prompt_files(self) -> None:
        config_paths = sorted(Path("configs/experiments").glob("**/*.yaml"))
        self.assertTrue(config_paths)
        for path in config_paths:
            config = ExperimentConfig.from_file(path)
            self.assertEqual(config.seed_prompt_files, (DEFAULT_PROMPT_DIR / "initial_strategy.txt",), path)
            self.assertEqual(config.generation_prompt_file, DEFAULT_PROMPT_DIR / "initial_generation.txt", path)
            self.assertEqual(config.seed_prompts, (load_prompt("initial_strategy"),), path)
            self.assertEqual(config.generation_prompt, load_prompt("initial_generation"), path)

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
