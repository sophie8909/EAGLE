from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.aos import BALANCE_REFLECTION, build_reflection_operator_controller
from eagle.artifacts import write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.reflection_context import (
    CandidateReflectionSummary,
    MapReflectionResult,
    ObjectiveSummary,
    OpponentReflectionSummary,
    ReflectionContext,
)
from eagle.reflection_prompts import build_balance_reflection_prompt_bundle
from eagle.rewrite import BalanceReflectionMutation
from eagle.reusable_generation_prompt import parse_reusable_generation_rules


GENERIC_BALANCE_RULE = (
    "Preserve policy-defined contingency priorities when several behaviors are simultaneously reachable."
)


def balance_rule_delta() -> str:
    return json.dumps({
        "remove_rule_ids": [],
        "add_rules": [{
            "category": "priority_ordering",
            "instruction": GENERIC_BALANCE_RULE,
        }],
    })


class ScriptedBackend:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.responses)


class BalanceReflectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = Candidate(
            id="balance-child",
            generation=4,
            parent_ids=("parent",),
            strategy_prompt="ORIGINAL STRATEGY SECRET",
            generation_prompt="ORIGINAL CODE PROMPT SECRET",
            operator="copy",
            strategy_parent_id="parent",
            generation_prompt_parent_id="parent",
        )
        self.context = ReflectionContext(
            candidate=CandidateReflectionSummary(
                candidate_id="parent",
                strategy_prompt="PARENT POLICY SECRET",
                code_generation_prompt="PARENT CODE SECRET",
                generated_code="JAVA SECRET",
                status="evaluated",
            ),
            objectives=ObjectiveSummary(game_performance=-61.0, code_quality=80.0),
            opponents=(
                OpponentReflectionSummary(
                    opponent_id="lightrush",
                    opponent_name="LightRush",
                    wins=3,
                    losses=9,
                    draws=0,
                    map_results=(
                        MapReflectionResult(
                            map_name="map_3",
                            games=12,
                            wins=3,
                            losses=9,
                            draws=0,
                            p0_result={"games": 6, "wins": 0, "losses": 6, "draws": 0},
                            p1_result={"games": 6, "wins": 3, "losses": 3, "draws": 0},
                        ),
                    ),
                ),
            ),
            per_match_results=({"raw_game_log": "MUST NOT LEAK"},),
        )

    def _analysis(self) -> str:
        return json.dumps({
            "weaknesses": [{
                "opponent": "lightrush",
                "map": "map_3",
                "side": "p0",
                "reason": "lost all six p0 games",
            }],
            "strategy_focus": ["use a safer map_3 opening as p0"],
            "code_generation_focus": ["preserve side-aware opening branches"],
        })

    def test_balance_reflection_receives_only_aggregate_outcome_table(self) -> None:
        prompt = build_balance_reflection_prompt_bundle(self.candidate, self.context).text

        self.assertIn('"opponent":"lightrush"', prompt)
        self.assertIn('"map":"map_3"', prompt)
        self.assertIn('"p0":{"draws":0,"games":6,"losses":6,"wins":0}', prompt)
        for forbidden in (
            "ORIGINAL STRATEGY SECRET",
            "ORIGINAL CODE PROMPT SECRET",
            "PARENT POLICY SECRET",
            "PARENT CODE SECRET",
            "JAVA SECRET",
            "MUST NOT LEAK",
        ):
            self.assertNotIn(forbidden, prompt)

    def test_balance_reflection_rewrites_both_genes_and_persists_three_calls(self) -> None:
        backend = ScriptedBackend((
            self._analysis(),
            "REWRITTEN STRATEGY",
            balance_rule_delta(),
        ))
        config = ExperimentConfig.from_mapping({
            "mutation_max_attempts": 1,
            "balance_reflection_probability": 1.0,
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
        })
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / self.candidate.id
            result = BalanceReflectionMutation(
                config,
                reflection_backend=backend,
                rewrite_backend=backend,
            ).mutate(self.candidate, self.context, artifact_dir=root)

            self.assertEqual(result.mutation_type, "balance")
            self.assertEqual(result.strategy_prompt, "REWRITTEN STRATEGY")
            self.assertIn(GENERIC_BALANCE_RULE, result.generation_prompt)
            self.assertEqual(len(parse_reusable_generation_rules(result.generation_prompt)), 1)
            self.assertEqual(len(backend.prompts), 3)
            self.assertNotIn("ORIGINAL STRATEGY SECRET", backend.prompts[0])
            self.assertNotIn("ORIGINAL CODE PROMPT SECRET", backend.prompts[0])
            self.assertIn("ORIGINAL STRATEGY SECRET", backend.prompts[1])
            self.assertIn("ORIGINAL CODE PROMPT SECRET", backend.prompts[2])

            mutation_dir = root / "mutation" / "balance_reflection"
            for name in (
                "reflector_request.txt",
                "reflector_response_raw.txt",
                "strategy_rewriter_request.txt",
                "strategy_rewriter_response_raw.txt",
                "strategy_rewriter_attempt_001_request.txt",
                "code_rewriter_request.txt",
                "code_rewriter_response_raw.txt",
                "code_rewriter_attempt_001_request.txt",
                "reflection_context.json",
                "metadata.json",
            ):
                self.assertTrue((mutation_dir / name).is_file(), name)
            metadata = json.loads((mutation_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertNotIn("raw_response", metadata["reflection"])
            self.assertNotIn("raw_response", metadata["strategy_rewrite"])
            self.assertNotIn("raw_response", metadata["generation_rewrite"])
            self.assertEqual(len(result.timing["reflector_llm"]["attempts"]), 1)
            self.assertEqual(len(result.timing["rewriter_llm"]["attempts"]), 2)
            write_candidate_snapshot(root.parent, result)
            snapshot = json.loads((root / "candidate.json").read_text(encoding="utf-8"))
            self.assertEqual(
                snapshot["artifacts"]["balance_reflection"],
                "mutation/balance_reflection/metadata.json",
            )

    def test_balance_code_rewrite_rejects_whole_prompt_and_retries_delta(self) -> None:
        backend = ScriptedBackend((
            self._analysis(),
            "REWRITTEN STRATEGY",
            json.dumps({"rewritten_prompt": "UNVALIDATED WHOLE PROMPT"}),
            balance_rule_delta(),
        ))
        config = ExperimentConfig.from_mapping({
            "mutation_max_attempts": 2,
            "balance_reflection_probability": 1.0,
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
        })

        result = BalanceReflectionMutation(
            config,
            reflection_backend=backend,
            rewrite_backend=backend,
        ).mutate(self.candidate, self.context)

        self.assertTrue(result.metadata["mutation"]["applied"])
        self.assertNotIn("UNVALIDATED WHOLE PROMPT", result.generation_prompt)
        self.assertIn(GENERIC_BALANCE_RULE, result.generation_prompt)
        self.assertIn("previous response was rejected", backend.prompts[3].lower())
        self.assertIn(
            "Code Rewrite response must contain exactly remove_rule_ids and add_rules.",
            backend.prompts[3],
        )
        self.assertIn("EAGLE Balance Code Generation Prompt Rewrite stage", backend.prompts[3])
        self.assertEqual(
            [attempt["status"] for attempt in result.timing["rewriter_llm"]["attempts"]],
            ["success", "error", "success"],
        )

    def test_failed_first_rewrite_preserves_both_genes_and_skips_code_rewrite(self) -> None:
        backend = ScriptedBackend((self._analysis(), ""))
        config = ExperimentConfig.from_mapping({
            "mutation_max_attempts": 1,
            "balance_reflection_probability": 1.0,
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
        })

        result = BalanceReflectionMutation(
            config,
            reflection_backend=backend,
            rewrite_backend=backend,
        ).mutate(self.candidate, self.context)

        self.assertEqual(result.strategy_prompt, self.candidate.strategy_prompt)
        self.assertEqual(result.generation_prompt, self.candidate.generation_prompt)
        self.assertFalse(result.metadata["mutation"]["applied"])
        self.assertEqual(len(backend.prompts), 2)

    def test_balance_operator_is_selectable_as_a_configured_third_operator(self) -> None:
        config = ExperimentConfig.from_mapping({
            "reflection_operator_mode": "static",
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
            "balance_reflection_probability": 1.0,
        })
        controller = build_reflection_operator_controller(config)
        import random

        self.assertEqual(controller.select_operator(random.Random(7)), BALANCE_REFLECTION)
        record = controller.update_generation([])
        self.assertEqual(record["operators"][BALANCE_REFLECTION]["usage_count"], 1)
        self.assertEqual(record["balance_probability_after"], 1.0)
