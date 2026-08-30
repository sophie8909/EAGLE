from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.mutation import ReflectionStage
from eagle.reflection_context import build_reflection_context
from eagle.reflection_prompts import (
    build_code_reflection_prompt_bundle,
    build_strategy_reflection_prompt_bundle,
)
from eagle.rewrite import PromptRewriteMutation
from eagle.run_artifacts import initialize_run_manifest, load_error_memory, record_error_memory


def strategy_response() -> str:
    return json.dumps({
        "analysis": {"strengths": ["economy"], "weaknesses": ["map-dependent defense"], "priority_changes": ["defend earlier"]},
        "revised_strategy_prompt": "Defend earlier while preserving the proven economy sequence.",
    })


def code_response() -> str:
    return json.dumps({
        "assessment": "policy_clear_but_java_violates",
        "alignment_review": [{"policy_requirement": "defend", "observed_java_behavior": "expands", "mismatch": "missing defense", "required_generation_behavior": "encode defense first"}],
        "required_generation_behaviors": ["encode defense first"],
    })


class ScriptedBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return next(self.responses)


class ReflectionContextRedesignTests(unittest.TestCase):
    def candidate(self) -> Candidate:
        return Candidate(
            id="candidate-redesign",
            generation=4,
            parent_ids=("parent-a", "parent-b"),
            strategy_prompt="Build workers, defend the first base, then pressure the opponent.",
            generation_prompt="Return a complete CandidateAgent.java file.",
            generated_java=(
                "package ai.generated;\n"
                "// FIXED_REGION_SENTINEL\n"
                "// EAGLE_AGENT_STRATEGY_START\n"
                "private void decide(AgentContext context) { }\n"
                "// EAGLE_AGENT_STRATEGY_END\n"
            ),
            status="evaluated",
            fitness_objectives={"game_performance": 21.5, "code_quality": 604.0},
            game_eval_result=self.game_payload(),
            code_quality_result={
                "code_quality_breakdown": {
                    "code_quality": 65.18,
                    "complexity_penalty": 34.82,
                    "cyclomatic_complexity": 15,
                    "maximum_nesting_depth": 4,
                    "logical_loc": 126,
                    "longest_function_loc": 48,
                    "cyclomatic_penalty": 14.36,
                    "nesting_penalty": 10.71,
                    "logical_loc_penalty": 7.57,
                    "longest_function_penalty": 2.18,
                    "metric_version": "1",
                    "measured_source": "candidate_generated_methods",
                    "compile_success": True,
                    "function_score": 82,
                    "strategy_alignment_score": 8.5,
                    "compiler_errors": [],
                    "compiler_warnings": ["unchecked conversion"],
                },
                "strategy_alignment": {"reason": "The defensive sequence is present."},
            },
            metadata={
                "reflection_history": [
                    {"reflection_type": "code", "analysis_summary": "old code advice", "revised_prompt": "old code prompt"},
                    {"reflection_type": "strategy", "analysis_summary": "latest strategy advice", "revised_prompt": "latest strategy prompt"},
                ],
            },
        )

    @staticmethod
    def game_payload() -> dict[str, object]:
        return {
            "objective": 21.5,
            "completed_match_count": 4,
            "expected_match_count": 4,
            "opponent_results": [
                {
                    "opponent_id": "lightrush",
                    "opponent_name": "LightRush",
                    "weight": 1.0,
                    "score": 20.0,
                    "raw_match_score": 20.0,
                    "weighted_contribution": 20.0,
                    "wins": 2,
                    "losses": 1,
                    "draws": 1,
                    "p0_average": 24.0,
                    "p1_average": 16.0,
                    "map_averages": {"map_1": 24.0, "map_2": 16.0},
                    "expected_match_count": 4,
                    "completed_match_count": 4,
                    "missing_match_count": 0,
                    "status": "completed",
                },
            ],
            "match_results": [
                {"opponent_id": "lightrush", "opponent_name": "LightRush", "map_id": "map_1", "candidate_player": 0, "winner": 0, "performance": 24.0, "performance_breakdown": {"survival_ratio": 0.8}},
                {"opponent_id": "lightrush", "opponent_name": "LightRush", "map_id": "map_1", "candidate_player": 1, "winner": 1, "performance": 24.0, "performance_breakdown": {"survival_ratio": 0.7}},
                {"opponent_id": "lightrush", "opponent_name": "LightRush", "map_id": "map_2", "candidate_player": 0, "winner": 1, "performance": 16.0, "performance_breakdown": {"survival_ratio": 0.4}},
                {"opponent_id": "lightrush", "opponent_name": "LightRush", "map_id": "map_2", "candidate_player": 1, "winner": 1, "performance": 16.0, "performance_breakdown": {"survival_ratio": 0.5}},
            ],
            "eagle_reference": {"generation": 3, "candidate_id": "old-champion", "weight": 2.25},
        }

    def test_context_preserves_weight_raw_weighted_and_map_position_fields(self):
        context = build_reflection_context(self.candidate(), generation=5, index=2, reflection_type="strategy")
        opponent = context.opponents[0]
        self.assertEqual(opponent.weight, 1.0)
        self.assertEqual(opponent.raw_score, 20.0)
        self.assertEqual(opponent.weighted_score, 20.0)
        self.assertEqual(opponent.p0_wins, 1)
        self.assertEqual(opponent.p1_wins, 2)
        self.assertEqual([item.map_name for item in opponent.map_results], ["map_1", "map_2"])
        self.assertEqual(opponent.map_results[0].games, 2)

    def test_strategy_formatter_keeps_gameplay_and_excludes_code_logs(self):
        candidate = self.candidate()
        candidate = Candidate(**{**candidate.__dict__, "code_quality_result": {"code_quality_breakdown": {"compiler_errors": ["SECRET_COMPILER_LOG"]}}})
        context = build_reflection_context(candidate, generation=5, index=2, reflection_type="strategy")
        prompt = build_strategy_reflection_prompt_bundle(candidate, context)
        self.assertIn("LightRush", prompt.text)
        self.assertIn("map_1", prompt.text)
        self.assertIn("p0_result", prompt.text)
        self.assertNotIn("SECRET_COMPILER_LOG", prompt.text)
        self.assertNotIn("CandidateAgent {}", prompt.text)
        self.assertNotIn("complexity_penalty", prompt.text)

    def test_code_formatter_receives_only_structural_compiler_diagnostics(self):
        context = build_reflection_context(self.candidate(), generation=5, index=2, reflection_type="code")
        prompt = build_code_reflection_prompt_bundle(self.candidate(), context)
        self.assertIn("unchecked conversion", prompt.text)
        self.assertNotIn("FIXED_REGION_SENTINEL", prompt.text)
        self.assertNotIn("code_quality", prompt.text)
        self.assertNotIn("complexity_penalty", prompt.text)
        self.assertNotIn("strategy_alignment", prompt.text)

    def test_code_formatter_excludes_match_table_and_bounds_code(self):
        candidate = self.candidate()
        candidate = Candidate(**{
            **candidate.__dict__,
            "generated_java": (
                "FIXED_REGION_SENTINEL\n"
                "// EAGLE_AGENT_STRATEGY_START\n"
                + "\n".join(f"// strategy line {index}" for index in range(5000))
                + "\n// EAGLE_AGENT_STRATEGY_END\n"
            ),
        })
        context = build_reflection_context(candidate, generation=5, index=2, reflection_type="code")
        prompt = build_code_reflection_prompt_bundle(candidate, context)
        self.assertIn("Optional structural/compiler evidence", prompt.text)
        self.assertNotIn('"map_1"', prompt.text)
        self.assertIn("editable_strategy_java", prompt.metadata["truncated_sections"])
        self.assertNotIn("FIXED_REGION_SENTINEL", prompt.text)
        self.assertTrue(prompt.metadata["estimated_prompt_size"] < 30_000)

    def test_reflection_stage_accepts_structured_json_without_final_slice(self):
        backend = ScriptedBackend((strategy_response(),))
        request = "header\n" + ("x" * 70_000) + "\ntail"
        result = ReflectionStage(backend, max_attempts=1).run(
            reflection_type="strategy",
            candidate=self.candidate(),
            request=request,
        )
        self.assertTrue(result.succeeded)
        self.assertGreater(len(backend.calls[0]), 60_000)
        self.assertEqual(result.parsed_response["revised_strategy_prompt"], "Defend earlier while preserving the proven economy sequence.")

    def test_error_memory_deduplicates_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            initialize_run_manifest(
                run_dir,
                config=ExperimentConfig.from_mapping({}),
            )
            failed = [Candidate(id=f"failed-{index}", generation=index, status="failed", failure_stage="compilation", failure_reason="/tmp/CandidateAgent.java:42: cannot find symbol") for index in range(4)]
            record_error_memory(run_dir, failed)
            memory = load_error_memory(run_dir)
            self.assertEqual(len(memory), 1)
            self.assertEqual(memory[0]["category"], "compile_failure")
            self.assertEqual(memory[0]["count"], 4)

    def test_history_is_type_specific_and_child_retains_only_latest_entry(self):
        candidate = self.candidate()
        context = build_reflection_context(candidate, generation=5, index=2, reflection_type="strategy")
        self.assertIn("latest strategy advice", context.previous_reflection)
        backend = ScriptedBackend((strategy_response(), "rewritten strategy"))
        mutation = PromptRewriteMutation(
            ExperimentConfig.from_mapping({"mutation_max_attempts": 1}),
            mutation_type="strategy",
            reflection_backend=backend,
            rewrite_backend=backend,
        )
        child = mutation.mutate(candidate, context)
        self.assertEqual(len(child.metadata["reflection_history"]), 1)
        self.assertEqual(child.metadata["reflection_history"][0]["reflection_type"], "strategy")
        self.assertEqual(child.metadata["reflection_history"][0]["revised_prompt"], "Defend earlier while preserving the proven economy sequence.")


if __name__ == "__main__":
    unittest.main()
