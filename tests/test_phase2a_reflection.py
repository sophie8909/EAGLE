import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.mutation import (
    MutationContext,
    ReflectionStage,
    build_code_reflection_prompt,
    build_strategy_reflection_prompt,
)
from eagle.llm import truncate_prompt


class ScriptedBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class Phase2AReflectionTests(unittest.TestCase):
    def setUp(self):
        self.candidate = Candidate(
            id="candidate-reflection",
            generation=2,
            strategy_prompt="Prioritize workers, then a fast ranged attack.",
            previous_code="parent generated Java",
            generation_prompt="Return one complete CandidateAgent.java file.",
        )
        self.context = MutationContext(
            generation=3,
            index=1,
            opponent="ai.abstraction.LightRush",
            match_summary={"completed_match_count": 10, "win_rate": 0.6},
            per_match_results=({"match_index": 0, "winner": 0},),
            wins=6,
            draws=1,
            losses=3,
            final_player_resources={"resources": 50},
            final_enemy_resources={"resources": 20},
            final_resource_difference=30,
            unit_material_statistics={"mean": 4.0},
            survival_statistics={"mean_final_tick": 90},
            round_state_summary={"last_round": 90},
            behavior_summary={"attack_timing": "late"},
            game_performance=61.0,
            latest_child_java="latest child Java",
            raw_generation_response="raw response",
            validation_result={"ok": True},
            compilation_result={"ok": False, "errors": ["missing symbol"]},
            integration_result={"status": "blocked"},
            runtime_result={"completed_match_count": 0},
            completed_match_count=0,
            function_capability_score=40,
            strategy_alignment_score=3,
            compiler_errors=("missing symbol",),
            compiler_warnings=("unchecked",),
            error_category="Java compile failure",
            error_message="missing symbol",
        )

    def test_strategy_prompt_contains_complete_game_evidence(self):
        prompt = build_strategy_reflection_prompt(self.candidate, self.context)
        for expected in (
            "Candidate strategy prompt",
            "Aggregate objectives",
            "Per-opponent summaries",
            "Gameplay diagnostics",
            "Required JSON shape",
        ):
            self.assertIn(expected, prompt)
        self.assertNotIn("Parent generated_java", prompt)

    def test_code_prompt_contains_complete_failure_evidence(self):
        prompt = build_code_reflection_prompt(self.candidate, self.context)
        for expected in (
            "Candidate prompts",
            "Generated Java",
            "Code diagnostics",
            "Required JSON shape",
            "missing symbol",
        ):
            self.assertIn(expected, prompt)
        self.assertNotIn("Opponent summaries", prompt)

    def test_reflection_retries_invalid_output_and_records_attempts(self):
        valid = json.dumps({
            "analysis": {"strengths": [], "weaknesses": ["late attack"], "priority_changes": ["attack earlier"]},
            "revised_strategy_prompt": "Attack earlier while preserving worker production.",
        })
        backend = ScriptedBackend(("```java\nclass CandidateAgent {}\n```", valid))
        stage = ReflectionStage(backend, max_attempts=2)
        result = stage.run(
            reflection_type="strategy_reflection",
            candidate=self.candidate,
            request="request",
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.revised_prompt, "Attack earlier while preserving worker production.")
        self.assertEqual([attempt.attempt for attempt in result.attempts], [1, 2])
        self.assertEqual(result.attempts[0].status, "error")
        self.assertEqual(result.attempts[1].status, "success")

    def test_reflection_failure_retains_raw_response_and_error(self):
        backend = ScriptedBackend(("", ""))
        with tempfile.TemporaryDirectory() as temp:
            result = ReflectionStage(backend, max_attempts=2).run(
                reflection_type="code_reflection",
                candidate=self.candidate,
                request="full request",
                artifact_dir=Path(temp),
            )
            mutation_dir = Path(temp) / "mutation"
            self.assertEqual(result.status, "failed")
            self.assertEqual(len(result.attempts), 2)
            self.assertTrue((mutation_dir / "reflector_request.txt").exists())
            self.assertTrue((mutation_dir / "reflector_response_raw.txt").exists())
            self.assertTrue((mutation_dir / "reflector_attempt_002_response_raw.txt").exists())
            self.assertIsNotNone(result.error)

    def test_reflection_request_is_not_blindly_truncated(self):
        response = json.dumps({
            "analysis": {"strengths": [], "weaknesses": [], "priority_changes": []},
            "revised_strategy_prompt": "Keep the strategy concise.",
        })
        backend = ScriptedBackend((response,))
        request = "BEGIN INSTRUCTIONS\n" + ("x" * 100_000) + "\nLATEST EVIDENCE"
        result = ReflectionStage(backend, max_attempts=1).run(
            reflection_type="strategy_reflection",
            candidate=self.candidate,
            request=request,
        )
        self.assertTrue(result.succeeded)
        self.assertGreater(len(backend.calls[0]), 60_000)
        self.assertIn("BEGIN INSTRUCTIONS", backend.calls[0])
        self.assertIn("LATEST EVIDENCE", backend.calls[0])

    def test_prompt_truncation_is_deterministic_and_keeps_short_prompts(self):
        short = "short prompt"
        self.assertEqual(truncate_prompt(short), short)
        oversized = "a" * 1_000 + "TAIL"
        self.assertEqual(truncate_prompt(oversized, max_chars=256), truncate_prompt(oversized, max_chars=256))
        self.assertLessEqual(len(truncate_prompt(oversized, max_chars=256)), 256)


if __name__ == "__main__":
    unittest.main()
