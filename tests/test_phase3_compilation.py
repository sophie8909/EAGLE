import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.artifacts import write_candidate_artifacts
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_candidate
from evaluation.code_quality import analyze_compilation
from evaluation.compiler import CompileResult, parse_compiler_diagnostics
from generation.backend import MockGenerationBackend


class Phase3CompilationTests(unittest.TestCase):
    def test_diagnostics_are_structured_and_deduplicated(self):
        output = """\
CandidateAgent.java:12: warning: [unchecked] unchecked conversion
CandidateAgent.java:12: warning: [unchecked] unchecked conversion
CandidateAgent.java:15:3: error: cannot find symbol
"""
        diagnostics = parse_compiler_diagnostics(output)
        self.assertEqual(len(diagnostics), 2)
        self.assertEqual(diagnostics[0].severity, "warning")
        self.assertEqual(diagnostics[0].code, "unchecked")
        self.assertEqual(diagnostics[0].file, "CandidateAgent.java")
        self.assertEqual(diagnostics[0].line, 12)
        self.assertIsNone(diagnostics[0].column)
        self.assertEqual(diagnostics[1].column, 3)

    def test_compilation_analysis_uses_structured_diagnostics(self):
        result = CompileResult(
            ok=True,
            command=["javac", "-Xlint:all"],
            diagnostics=parse_compiler_diagnostics("A.java:1: warning: [deprecation] old"),
        )
        analysis = analyze_compilation(result)
        self.assertEqual(analysis.warning_count, 1)
        self.assertEqual(analysis.warnings, ("old",))

    def test_mock_compile_command_enables_explicit_lint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "CandidateAgent.java"
            source.write_text("class CandidateAgent {}", encoding="utf-8")
            from evaluation.compiler import compile_generated_agent

            result = compile_generated_agent(
                source,
                microrts_dir=Path("third_party/microrts"),
                output_dir=root / "classes",
                mock=True,
            )
        self.assertIn("-Xlint:all", result.command)
        self.assertEqual(result.diagnostics, ())

    def test_compilation_artifacts_include_stdout_stderr_and_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            evaluation = evaluate_candidate(
                Candidate(id="compile-artifacts"),
                config=config,
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(root / "candidates", evaluation)
            candidate_dir = root / "candidates" / "compile-artifacts"
            payload = json.loads((candidate_dir / "compilation" / "compilation_result.json").read_text(encoding="utf-8"))
            timing = json.loads((candidate_dir / "timing.json").read_text(encoding="utf-8"))
            stdout_exists = (candidate_dir / "compilation" / "stdout.txt").exists()
            stderr_exists = (candidate_dir / "compilation" / "stderr.txt").exists()

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["timing"]["status"], "success")
        self.assertTrue(stdout_exists)
        self.assertTrue(stderr_exists)
        self.assertGreaterEqual(timing["compilation_duration_seconds"], 0.0)
        self.assertEqual(timing["compilation"]["status"], "success")

    def test_compilation_failure_stops_before_integration_and_persists_metadata(self):
        diagnostic_text = "CandidateAgent.java:9:4: error: cannot find symbol"
        compile_failure = CompileResult(
            ok=False,
            command=["javac", "-Xlint:all"],
            stderr=diagnostic_text,
            returncode=1,
            diagnostics=parse_compiler_diagnostics(diagnostic_text),
        )
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch("eagle.evaluation.compile_agent_source", return_value=compile_failure), \
             patch("eagle.evaluation.integrate_microrts_agent") as integrate:
            root = Path(temp_dir)
            evaluation = evaluate_candidate(
                Candidate(id="compile-failure"),
                config=ExperimentConfig.from_mapping({"seed_prompts": ["seed"]}),
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(root / "candidates", evaluation)
            candidate_dir = root / "candidates" / "compile-failure"
            compilation = json.loads((candidate_dir / "compilation" / "compilation_result.json").read_text(encoding="utf-8"))
            integration_payload = json.loads((candidate_dir / "integration" / "integration_result.json").read_text(encoding="utf-8"))
            timing = json.loads((candidate_dir / "timing.json").read_text(encoding="utf-8"))

        integrate.assert_not_called()
        self.assertEqual(evaluation.candidate.failure_stage, "compilation")
        self.assertEqual(evaluation.match_results, [])
        self.assertEqual(compilation["status"], "failed")
        self.assertEqual(compilation["error_count"], 1)
        self.assertEqual(integration_payload["status"], "blocked")
        self.assertEqual(integration_payload["failure_stage"], "compilation")
        self.assertEqual(timing["integration"]["status"], "blocked")

    def test_compilation_warning_is_preserved_end_to_end(self):
        warning_text = "CandidateAgent.java:12: warning: [unchecked] unchecked conversion"
        compile_success = CompileResult(
            ok=True,
            command=["javac", "-Xlint:all"],
            stderr=warning_text,
            diagnostics=parse_compiler_diagnostics(warning_text),
        )
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch("eagle.evaluation.compile_agent_source", return_value=compile_success):
            root = Path(temp_dir)
            evaluation = evaluate_candidate(
                Candidate(id="compile-warning"),
                config=ExperimentConfig.from_mapping({"seed_prompts": ["seed"]}),
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(root / "candidates", evaluation)
            payload = json.loads(
                (root / "candidates" / "compile-warning" / "compilation" / "compilation_result.json").read_text(encoding="utf-8")
            )

        self.assertIsNone(evaluation.candidate.failure_stage)
        self.assertEqual(payload["warning_count"], 1)
        self.assertEqual(payload["diagnostics"][0]["severity"], "warning")
        self.assertEqual(payload["diagnostics"][0]["code"], "unchecked")


if __name__ == "__main__":
    unittest.main()
