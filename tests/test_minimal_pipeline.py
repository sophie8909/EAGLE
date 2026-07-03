import tempfile
import unittest
from pathlib import Path

from agents.workspace import AgentWorkspace
from eagle.candidate import CandidatePrompt
from eagle.config import ExperimentConfig
from eagle.experiment import run_experiment
from generation.backend import TemplateGenerationBackend, generated_class_name
from generation.parsing import extract_java_source


class MinimalPipelineTests(unittest.TestCase):
    def test_template_backend_generates_valid_java(self) -> None:
        candidate = CandidatePrompt("Generate a MicroRTS agent.")
        source = TemplateGenerationBackend().generate(candidate)
        self.assertIn("package ai.generated;", source)
        self.assertIn(generated_class_name(candidate.candidate_id), source)

    def test_extract_java_source_from_fence(self) -> None:
        output = "Text\n```java\npublic class A {}\n```\n"
        self.assertEqual(extract_java_source(output), "public class A {}")

    def test_minimal_experiment_writes_generated_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "generated"
            config = ExperimentConfig(
                seed_prompts=("Generate a Java MicroRTS agent.",),
                population_size=1,
                generated_agent_dir=output_dir,
                dry_run=True,
            )
            results = run_experiment(config)
            self.assertEqual(len(results), 1)
            source_path = Path(results[0].artifacts["source_path"])
            self.assertTrue(source_path.exists())
            self.assertTrue(source_path.read_text(encoding="utf-8").startswith("package ai.generated;"))

    def test_workspace_uses_generated_package_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = CandidatePrompt("Generate an agent.")
            path = AgentWorkspace(root).write_source(candidate, "package ai.generated;\npublic class A {}\n")
            self.assertEqual(path.parent, root / "src" / "ai" / "generated")


if __name__ == "__main__":
    unittest.main()
