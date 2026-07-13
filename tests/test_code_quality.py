import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate, DEFAULT_MODULE_BODIES, MODULE_NAMES
from evaluation.code_quality import (
    analyze_compilation,
    analyze_static_code,
    build_code_quality,
    evaluate_function_output,
)
from evaluation.compiler import CompileResult
from generation.agent_template import JavaTemplatePaths, load_java_template
from scripts.analyze_run import read_candidate_results


class CodeQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = load_java_template(JavaTemplatePaths())

    def test_compilation_failure_scores_negative_1000(self):
        result = analyze_compilation(
            CompileResult(False, [], stderr="A.java:1: error: bad\n1 error", returncode=1)
        )
        self.assertEqual(result.compilation_score, -1000)
        self.assertEqual(result.compile_error_count, 1)
        self.assertFalse(result.compile_success)

    def test_success_without_warnings_scores_zero(self):
        result = analyze_compilation(CompileResult(True, []))
        self.assertEqual(result.compilation_score, 0)
        self.assertEqual(result.warning_count, 0)

    def test_each_warning_subtracts_50_without_counting_errors(self):
        output = (
            "A.java:1: warning: unchecked conversion\n"
            "A.java:2: error: bad\n"
            "A.java:3: warning: deprecated\n"
        )
        result = analyze_compilation(CompileResult(True, [], stderr=output))
        self.assertEqual(result.warning_count, 2)
        self.assertEqual(result.compilation_score, -100)
        self.assertEqual(result.compile_error_count, 0)

    def test_all_valid_functions_score_100(self):
        result = evaluate_function_output(
            json.dumps({"functions": DEFAULT_MODULE_BODIES}),
            self.template,
        )
        self.assertEqual(result.function_score, 100)
        self.assertEqual(result.valid_function_count, len(MODULE_NAMES))

    def test_outer_json_fence_is_unwrapped(self):
        fence = chr(96) * 3
        raw = fence + "json\n" + json.dumps({"functions": DEFAULT_MODULE_BODIES}) + "\n" + fence
        result = evaluate_function_output(raw, self.template)
        self.assertEqual(result.function_score, 100)
        self.assertEqual(result.parsing_errors, ())

    def test_text_outside_json_fence_remains_invalid(self):
        fence = chr(96) * 3
        raw = (
            "Here is the result:\n"
            + fence
            + "json\n"
            + json.dumps({"functions": DEFAULT_MODULE_BODIES})
            + "\n"
            + fence
        )
        result = evaluate_function_output(raw, self.template)
        self.assertTrue(result.parsing_errors)
        self.assertEqual(result.valid_function_count, 0)

    def test_missing_functions_subtract_from_score(self):
        functions = dict(DEFAULT_MODULE_BODIES)
        functions.pop(MODULE_NAMES[0])
        functions.pop(MODULE_NAMES[1])
        result = evaluate_function_output(
            json.dumps({"functions": functions}),
            self.template,
        )
        self.assertAlmostEqual(
            result.function_score,
            100 * (len(MODULE_NAMES) - 4) / len(MODULE_NAMES),
        )

    def test_present_empty_function_scores_zero(self):
        functions = {name: "" for name in MODULE_NAMES}
        result = evaluate_function_output(
            json.dumps({"functions": functions}),
            self.template,
        )
        self.assertEqual(result.function_score, 0)
        self.assertEqual(result.valid_function_count, 0)
        self.assertEqual(
            result.function_validation[MODULE_NAMES[0]].errors,
            ("Function body is empty",),
        )

    def test_nonempty_valid_function_adds_to_score(self):
        functions = {MODULE_NAMES[0]: DEFAULT_MODULE_BODIES[MODULE_NAMES[0]]}
        result = evaluate_function_output(
            json.dumps({"functions": functions}),
            self.template,
        )
        self.assertAlmostEqual(
            result.function_score,
            100 * (1 - (len(MODULE_NAMES) - 1)) / len(MODULE_NAMES),
        )
        self.assertEqual(result.valid_function_count, 1)

    def test_unknown_functions_do_not_increase_score(self):
        result = evaluate_function_output(
            json.dumps(
                {"functions": {**DEFAULT_MODULE_BODIES, "helper": "return;"}}
            ),
            self.template,
        )
        self.assertEqual(result.function_score, 100)
        self.assertEqual(result.unknown_function_names, ("helper",))

    def test_static_score_changes_with_executable_code_length(self):
        short = analyze_static_code({"controller": "int budget = 10;"})
        long = analyze_static_code({"controller": "int budget = 100;"})
        self.assertEqual(short.statement_count, long.statement_count)
        self.assertNotEqual(
            short.implementation_substance_score,
            long.implementation_substance_score,
        )
        self.assertNotEqual(short.static_quality_score, long.static_quality_score)

    def test_comments_and_whitespace_do_not_create_fitness_difference(self):
        compact = analyze_static_code({"controller": "commandIdle(context);"})
        padded = analyze_static_code(
            {"controller": "  // explanation\n\n commandIdle( context ); /* note */"}
        )
        self.assertEqual(
            compact.effective_character_count,
            padded.effective_character_count,
        )
        self.assertEqual(compact.static_quality_score, padded.static_quality_score)

    def test_action_and_state_coverage_are_reported_objectively(self):
        metrics = analyze_static_code(
            {
                "controller": (
                    "if (context.player.getResources() > 0) {\n"
                    "    commandTrain(context, base, workerType);\n"
                    "} else {\n"
                    "    commandIdle(context);\n"
                    "}"
                )
            }
        )
        self.assertEqual(metrics.branch_count, 1)
        self.assertEqual(
            metrics.action_helpers_used,
            ("commandTrain", "commandIdle"),
        )
        self.assertIn("player", metrics.state_signals_used)
        self.assertIn("resources", metrics.state_signals_used)

    def test_duplicate_executable_lines_reduce_maintainability(self):
        unique = analyze_static_code(
            {"controller": "commandIdle(context);\ncommandMove(context, unit, 1, 1);"}
        )
        duplicate = analyze_static_code(
            {"controller": "commandIdle(context);\ncommandIdle(context);"}
        )
        self.assertEqual(duplicate.duplicate_line_count, 1)
        self.assertLess(
            duplicate.maintainability_score,
            unique.maintainability_score,
        )

    def test_total_code_quality_is_component_sum(self):
        compiler = analyze_compilation(
            CompileResult(True, [], stderr="A.java:1: warning: unchecked")
        )
        functions = evaluate_function_output(
            json.dumps({"functions": DEFAULT_MODULE_BODIES}),
            self.template,
        )
        quality = build_code_quality(compiler, functions, DEFAULT_MODULE_BODIES)
        self.assertEqual(
            quality.code_quality,
            quality.compilation_score
            + quality.function_score
            + quality.static_quality_score,
        )
        self.assertIsNotNone(quality.static_metrics)

    def test_optimizer_vector_uses_code_quality(self):
        candidate = Candidate(
            fitness_objectives={"game_performance": 4, "code_quality": 108}
        )
        self.assertEqual(candidate.objective_vector(), (4.0, 108.0))

    def test_legacy_artifact_is_migrated_only_by_reader(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "candidates" / "old"
            path.mkdir(parents=True)
            (path / "candidate_result.json").write_text(
                json.dumps(
                    {
                        "final_score": {
                            "game_performance": 1,
                            "strategy_alignment": 0.5,
                        }
                    }
                ),
                encoding="utf-8",
            )
            record = read_candidate_results(Path(temp))[0]
        self.assertEqual(
            record["final_score"],
            {"game_performance": 1, "code_quality": 0.5},
        )


if __name__ == "__main__":
    unittest.main()
