import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from evaluation.code_quality import (
    analyze_compilation,
    analyze_static_code,
    build_code_quality,
    evaluate_agent_strategy_region,
)
from evaluation.compiler import CompileResult
from scripts.analyze_run import read_candidate_results, read_objective_scatter_records


class CodeQualityTests(unittest.TestCase):
    def test_compilation_failure_is_scored_by_failure_stage(self):
        result = analyze_compilation(
            CompileResult(False, [], stderr="A.java:1: error: bad\n1 error", returncode=1)
        )
        self.assertEqual(result.compilation_score, 0)
        self.assertEqual(result.compile_error_count, 1)
        self.assertFalse(result.compile_success)

    def test_success_without_warnings_scores_zero(self):
        result = analyze_compilation(CompileResult(True, []))
        self.assertEqual(result.compilation_score, 0)
        self.assertEqual(result.warning_count, 0)

    def test_each_warning_subtracts_50_and_diagnostics_retain_errors(self):
        output = (
            "A.java:1: warning: unchecked conversion\n"
            "A.java:2: error: bad\n"
            "A.java:3: warning: deprecated\n"
        )
        result = analyze_compilation(CompileResult(True, [], stderr=output))
        self.assertEqual(result.warning_count, 2)
        self.assertEqual(result.compilation_score, -100)
        self.assertEqual(result.compile_error_count, 1)

    def test_complete_java_strategy_region_scores_100(self):
        result = evaluate_agent_strategy_region(
            "private void decide(AgentContext context) { commandIdle(unit); }"
        )
        self.assertEqual(result.strategy_region_score, 100)
        self.assertEqual(result.required_region_count, 1)
        self.assertEqual(result.valid_region_count, 1)
        self.assertEqual(
            set(result.strategy_region_validation),
            {"agent_strategy_region"},
        )

    def test_missing_strategy_region_scores_negative_100(self):
        result = evaluate_agent_strategy_region(
            "",
            error="Agent strategy markers are missing.",
        )
        self.assertEqual(result.strategy_region_score, -100)
        self.assertEqual(result.valid_region_count, 0)
        self.assertIn(
            "Agent strategy markers are missing.",
            result.strategy_region_validation["agent_strategy_region"].errors,
        )

    def test_static_score_changes_with_executable_code_length(self):
        short = analyze_static_code({"agent_strategy_region": "int budget = 10;"})
        long = analyze_static_code({"agent_strategy_region": "int budget = 100;"})
        self.assertEqual(short.statement_count, long.statement_count)
        self.assertNotEqual(
            short.implementation_substance_score,
            long.implementation_substance_score,
        )
        self.assertNotEqual(short.static_quality_score, long.static_quality_score)

    def test_comments_and_whitespace_do_not_create_fitness_difference(self):
        compact = analyze_static_code(
            {"agent_strategy_region": "commandIdle(context);"}
        )
        padded = analyze_static_code(
            {
                "agent_strategy_region": (
                    "  // explanation\n\n commandIdle( context ); /* note */"
                )
            }
        )
        self.assertEqual(
            compact.effective_character_count,
            padded.effective_character_count,
        )
        self.assertEqual(compact.static_quality_score, padded.static_quality_score)

    def test_action_and_state_coverage_are_reported_objectively(self):
        metrics = analyze_static_code(
            {
                "agent_strategy_region": (
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

    def test_strategy_connectivity_uses_declared_methods_not_fixed_names(self):
        metrics = analyze_static_code(
            {
                "agent_strategy_region": (
                    "private void decide(AgentContext context) { customPlan(context); }\n"
                    "private void customPlan(AgentContext context) { commandIdle(unit); }"
                )
            }
        )
        self.assertEqual(metrics.strategy_functions_called, ("customPlan",))
        self.assertGreater(metrics.strategy_connectivity_score, 0)

    def test_duplicate_executable_lines_reduce_maintainability(self):
        unique = analyze_static_code(
            {
                "agent_strategy_region": (
                    "commandIdle(context);\ncommandMove(context, unit, 1, 1);"
                )
            }
        )
        duplicate = analyze_static_code(
            {
                "agent_strategy_region": (
                    "commandIdle(context);\ncommandIdle(context);"
                )
            }
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
        strategy_region = (
            "private void decide(AgentContext context) { commandIdle(unit); }"
        )
        structure = evaluate_agent_strategy_region(strategy_region)
        quality = build_code_quality(
            compiler,
            structure,
            {"agent_strategy_region": strategy_region},
        )
        self.assertEqual(
            quality.code_quality,
            500 + quality.compilation_score,
        )
        self.assertIsNone(quality.static_metrics)
        self.assertEqual(
            quality.to_json_dict()["code_quality"],
            quality.code_quality,
        )

    def test_optimizer_vector_uses_code_quality(self):
        candidate = Candidate(
            fitness_objectives={"game_performance": 4, "code_quality": 108}
        )
        self.assertEqual(candidate.objective_vector(), (4.0, 108.0))

if __name__ == "__main__":
    unittest.main()
