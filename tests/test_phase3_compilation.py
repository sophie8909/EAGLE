import json
import tempfile
import unittest
from pathlib import Path

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
