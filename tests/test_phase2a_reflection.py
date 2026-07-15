import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.mutation import (
    Mutation,
    MutationContext,
    ReflectionStage,
    build_code_reflection_prompt,
    build_strategy_reflection_prompt,
)


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
            "Current strategy_prompt",
            "Parent generated_java",
            "Complete 10-match summary",
            "Per-match results",
            "Wins: 6",
            "draws: 1",
            "losses: 3",
            "Final player resources",
            "Unit material statistics",
            "Survival statistics",
            "Round-state summary",
            "Behavior summary",
            "ai.abstraction.LightRush",
        ):
            self.assertIn(expected, prompt)
        self.assertIn("Do not generate Java", prompt)

    def test_code_prompt_contains_complete_failure_evidence(self):
        prompt = build_code_reflection_prompt(self.candidate, self.context)
        for expected in (
            "strategy_prompt",
            "current generation_prompt",
            "parent generated_java",
            "latest generated child Java",
            "raw generation response",
            "source validation result",
            "compilation result",
            "MicroRTS integration result",
            "runtime result",
            "completed-match count",
            "function capability score",
            "strategy alignment score",
            "failure stage",
            "missing symbol",
        ):
            self.assertIn(expected, prompt)

    def test_reflection_retries_invalid_output_and_records_attempts(self):
        backend = ScriptedBackend(("```java\nclass CandidateAgent {}\n```", "Useful reflection text."))
        stage = ReflectionStage(backend, max_attempts=2)
        result = stage.run(
            stage="strategy_reflection",
            reflection_type="strategy_reflection",
            candidate=self.candidate,
            request="request",
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.reflection, "Useful reflection text.")
        self.assertEqual([attempt.attempt for attempt in result.attempts], [1, 2])
        self.assertEqual(result.attempts[0].status, "error")
        self.assertEqual(result.attempts[1].status, "success")

    def test_reflection_failure_retains_raw_response_and_error(self):
        backend = ScriptedBackend(("", ""))
        with tempfile.TemporaryDirectory() as temp:
            result = ReflectionStage(backend, max_attempts=2).run(
                stage="code_generation_reflection",
                reflection_type="code_reflection",
                candidate=self.candidate,
                request="full request",
                artifact_dir=Path(temp),
            )
            mutation_dir = Path(temp) / "mutation"
            self.assertEqual(result.status, "failed")
            self.assertEqual(len(result.attempts), 2)
            self.assertTrue((mutation_dir / "code_generation_reflection_request.txt").exists())
            self.assertTrue((mutation_dir / "code_generation_reflection_response_raw.txt").exists())
            self.assertTrue((mutation_dir / "code_generation_reflection_attempt_002_response_raw.txt").exists())
            self.assertIsNotNone(result.error)

    def test_reflection_only_mutation_does_not_change_genotype(self):
        backend = ScriptedBackend(("Reflection text",))
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"], "mutation_max_attempts": 1})
        with tempfile.TemporaryDirectory() as temp:
            child = Mutation(config, backend=backend).mutate(
                self.candidate,
                self.context,
                artifact_dir=Path(temp),
            )
        self.assertEqual(child.id, self.candidate.id)
        self.assertEqual(child.strategy_prompt, self.candidate.strategy_prompt)
        self.assertEqual(child.previous_code, self.candidate.previous_code)
        self.assertEqual(child.generation_prompt, self.candidate.generation_prompt)
        self.assertEqual(child.metadata["mutation"]["applied"], False)
        self.assertEqual(child.metadata["mutation"]["reflection"]["reflection"], "Reflection text")
        self.assertEqual(len(child.timing["reflection_llm"]["attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
