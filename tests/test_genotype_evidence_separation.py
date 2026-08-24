from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.mutation import ReflectionContext
from eagle.reflection_context import build_reflection_context
from eagle.reflection_prompts import build_code_reflection_prompt_bundle
from eagle.rewrite import PromptRewriteMutation, build_code_rewrite_prompt
from eagle.strategy_reflection import (
    MockRoleBackend,
    StrategyReflectionMutation,
    _parse_coach,
    _coach_prompt,
    _commentator_prompt,
)


JAVA_SENTINEL = "PHENOTYPE_JAVA_SENTINEL"
CODE_PROMPT_SENTINEL = "CODE_GENERATION_PROMPT_SENTINEL"
GAME_LOG_SENTINEL = "RAW_GAME_LOG_SENTINEL"
POLICY_SENTINEL = "POLICY_PROMPT_SENTINEL"


class ScriptedBackend:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.responses)


def code_review() -> str:
    return json.dumps({
        "assessment": "policy_clear_but_java_violates",
        "alignment_review": [{
            "policy_requirement": "defend before expanding",
            "observed_java_behavior": "expands on resources alone",
            "mismatch": "enemy pressure is ignored",
            "required_generation_behavior": "encode the defensive prerequisite",
        }],
        "required_generation_behaviors": ["encode policy preconditions explicitly"],
    })


class GenotypeEvidenceSeparationTests(unittest.TestCase):
    def candidate(self) -> Candidate:
        return Candidate(
            id="boundary-candidate",
            generation=2,
            strategy_prompt=POLICY_SENTINEL + ": defend before expanding",
            generation_prompt=CODE_PROMPT_SENTINEL,
            generated_java="package ai.generated; // " + JAVA_SENTINEL,
            status="evaluated",
            game_eval_result={
                "game_performance": -1.0,
                "match_results": [{"match_id": "m1", "raw_log": GAME_LOG_SENTINEL}],
            },
        )

    def test_match_commentator_prompt_excludes_java_and_code_prompt(self) -> None:
        candidate = self.candidate()
        item = {
            "match_id": "m1",
            "opponent_name": "LightRush",
            "map_name": "map-1",
            "candidate_player": 0,
            "winner": 1,
            "generated_java": JAVA_SENTINEL,
            "code_generation_prompt": CODE_PROMPT_SENTINEL,
        }
        prompt = _commentator_prompt(candidate, ReflectionContext(), item, "m1", [{"tick": 0}])
        self.assertIn(POLICY_SENTINEL, prompt)
        self.assertIn('"turning_points":[{"tick":0', prompt)
        self.assertIn("without Markdown fences, wrapper objects, or prose", prompt)
        self.assertNotIn(JAVA_SENTINEL, prompt)
        self.assertNotIn(CODE_PROMPT_SENTINEL, prompt)

    def test_coach_prompt_excludes_java_and_code_generation_prompt(self) -> None:
        candidate = self.candidate()
        prompt = _coach_prompt(candidate.strategy_prompt, {"commentator_diagnoses": []}, "REFINE")
        self.assertIn(POLICY_SENTINEL, prompt)
        self.assertNotIn(JAVA_SENTINEL, prompt)
        self.assertNotIn(CODE_PROMPT_SENTINEL, prompt)

    def test_code_reviewer_receives_policy_and_java_but_no_game_logs(self) -> None:
        candidate = self.candidate()
        context = build_reflection_context(candidate, generation=3, index=0, reflection_type="code")
        prompt = build_code_reflection_prompt_bundle(candidate, context).text
        self.assertIn(POLICY_SENTINEL, prompt)
        self.assertIn(JAVA_SENTINEL, prompt)
        self.assertNotIn(GAME_LOG_SENTINEL, prompt)
        self.assertNotIn(CODE_PROMPT_SENTINEL, prompt)

    def test_code_reflection_records_source_phenotype_without_previous_code_gene(self) -> None:
        source = self.candidate()
        child = Candidate(
            id="child-candidate",
            generation=3,
            strategy_prompt=source.strategy_prompt,
            generation_prompt=source.generation_prompt,
            generation_prompt_parent_id=source.id,
        )
        context = build_reflection_context(source, generation=3, index=0, reflection_type="code")
        backend = ScriptedBackend((code_review(), "new reusable translation instructions"))
        mutation = PromptRewriteMutation(
            ExperimentConfig.from_mapping({"mutation_max_attempts": 1}),
            mutation_type="code",
            reflection_backend=backend,
            rewrite_backend=backend,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = mutation.mutate(child, context, artifact_dir=root)
            metadata = json.loads(
                (root / "mutation" / "code_reflection" / "metadata.json").read_text()
            )
        self.assertIn(JAVA_SENTINEL, backend.prompts[0])
        self.assertEqual(
            metadata["evidence"]["reviewed_phenotype_artifact"],
            f"candidates/{source.id}/phenotype/CandidateAgent.java",
        )
        self.assertFalse(hasattr(result, "previous_code"))

    def test_coach_parser_accepts_fenced_json_and_literal_newlines(self) -> None:
        response = """```json
{"strategy_changes":{"preserved":[],"removed_or_reduced":[],"added_or_strengthened":[]},"strategy_signature":{},"parent_strategy_prompt":"old","new_strategy_prompt":"Train Workers.
Harvest resources.
Attack the enemy Base."}
```"""
        parsed = _parse_coach(response, parent_strategy_prompt="old")
        self.assertEqual(
            parsed.new_strategy_prompt,
            "Train Workers.\nHarvest resources.\nAttack the enemy Base.",
        )

    def test_code_prompt_rewriter_receives_only_code_prompt_and_review(self) -> None:
        candidate = self.candidate()
        backend = ScriptedBackend((code_review(),))
        from eagle.mutation import ReflectionStage

        review = ReflectionStage(backend, max_attempts=1).run(
            reflection_type="code", candidate=candidate, request="review"
        )
        prompt = build_code_rewrite_prompt(candidate, review, ReflectionContext())
        self.assertIn(CODE_PROMPT_SENTINEL, prompt)
        self.assertIn("defensive prerequisite", prompt)
        self.assertNotIn(POLICY_SENTINEL, prompt)
        self.assertNotIn(JAVA_SENTINEL, prompt)
        self.assertNotIn(GAME_LOG_SENTINEL, prompt)

    def test_strategy_mutation_cannot_modify_code_generation_prompt(self) -> None:
        candidate = self.candidate()
        result = StrategyReflectionMutation(MockRoleBackend(), max_attempts=1).mutate(
            candidate,
            ReflectionContext(),
        )
        self.assertEqual(result.generation_prompt, candidate.generation_prompt)

    def test_code_mutation_cannot_modify_policy_prompt(self) -> None:
        candidate = self.candidate()
        backend = ScriptedBackend((code_review(), "new reusable translation instructions"))
        mutation = PromptRewriteMutation(
            ExperimentConfig.from_mapping({"mutation_max_attempts": 1}),
            mutation_type="code",
            reflection_backend=backend,
            rewrite_backend=backend,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = mutation.mutate(candidate, ReflectionContext(), artifact_dir=root)
            metadata = (root / "mutation" / "code_reflection" / "metadata.json").read_text()
            self.assertNotIn(JAVA_SENTINEL, metadata)
        self.assertEqual(result.strategy_prompt, candidate.strategy_prompt)
        self.assertEqual(result.generation_prompt, "new reusable translation instructions")

    def test_generator_request_does_not_mutate_genotype(self) -> None:
        candidate = self.candidate()
        before = (candidate.strategy_prompt, candidate.generation_prompt)
        candidate.generation_input(class_name="CandidateAgent")
        self.assertEqual((candidate.strategy_prompt, candidate.generation_prompt), before)


if __name__ == "__main__":
    unittest.main()
