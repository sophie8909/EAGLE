from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.aos import (
    PROMPT_COMPLIANCE_REFLECTION,
    build_reflection_operator_controller,
)
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
from eagle.reflection_prompts import build_prompt_compliance_reflection_prompt_bundle
from eagle.rewrite import PromptComplianceReflectionMutation
from eagle.reusable_generation_prompt import parse_reusable_generation_rules
from eagle.mutation import parse_reflection_response


GENERIC_COMPLIANCE_RULE = (
    "Preserve policy-defined contingency priorities when several behaviors are simultaneously reachable."
)


def compliance_rule_delta() -> str:
    return json.dumps({
        "remove_rule_ids": [],
        "add_rules": [{
            "category": "priority_ordering",
            "instruction": GENERIC_COMPLIANCE_RULE,
        }],
    })


class ScriptedBackend:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.responses)


class PromptComplianceReflectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = Candidate(
            id="prompt-compliance-child",
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
            "strategy_prompt_issues": [{
                "category": "unobservable_condition",
                "problem": "The policy depends on hidden opponent intent.",
                "correction_goal": "Use only current observable enemy units and positions.",
            }],
            "code_generation_prompt_issues": [{
                "category": "scope_or_scaffold_violation",
                "problem": "The prompt asks the model to edit immutable scaffold code.",
                "correction_goal": "Keep generated behavior inside the editable strategy region.",
            }],
            "strategy_rewrite_focus": [
                "Replace hidden-intent conditions with observable game-state conditions."
            ],
            "code_generation_rewrite_focus": [
                "Add one reusable rule that preserves the immutable scaffold boundary."
            ],
        })

    def test_prompt_compliance_reflection_receives_only_prompt_and_contract_evidence(self) -> None:
        prompt = build_prompt_compliance_reflection_prompt_bundle(
            self.candidate,
            self.context,
        ).text

        self.assertIn("ORIGINAL STRATEGY SECRET", prompt)
        self.assertIn("ORIGINAL CODE PROMPT SECRET", prompt)
        self.assertIn("IMMUTABLE MICRORTS GAMEPLAY CONTRACT", prompt)
        self.assertIn("IMMUTABLE MICRORTS ACTION AND JAVA API CONTRACT", prompt)
        self.assertIn("strategic type is not a compliance violation", prompt)
        self.assertIn("does not evaluate wins", prompt)
        for forbidden in (
            "PARENT POLICY SECRET",
            "PARENT CODE SECRET",
            "JAVA SECRET",
            "MUST NOT LEAK",
            '"opponent":"lightrush"',
            '"map":"map_3"',
        ):
            self.assertNotIn(forbidden, prompt)

    def test_prompt_compliance_schema_rejects_performance_analysis_fields(self) -> None:
        payload = json.loads(self._analysis())
        payload["win_loss_summary"] = {"wins": 0, "losses": 9}
        with self.assertRaisesRegex(ValueError, "must contain exactly"):
            parse_reflection_response(
                json.dumps(payload),
                "prompt_compliance",
            )

    def test_prompt_compliance_rewrites_both_genes_and_persists_three_calls(self) -> None:
        backend = ScriptedBackend((
            self._analysis(),
            "REWRITTEN STRATEGY",
            compliance_rule_delta(),
        ))
        config = ExperimentConfig.from_mapping({
            "mutation_max_attempts": 1,
            "prompt_compliance_reflection_probability": 1.0,
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
        })
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / self.candidate.id
            result = PromptComplianceReflectionMutation(
                config,
                reflection_backend=backend,
                rewrite_backend=backend,
            ).mutate(self.candidate, self.context, artifact_dir=root)

            self.assertEqual(result.mutation_type, "prompt_compliance")
            self.assertEqual(result.strategy_prompt, "REWRITTEN STRATEGY")
            self.assertIn(GENERIC_COMPLIANCE_RULE, result.generation_prompt)
            self.assertEqual(len(parse_reusable_generation_rules(result.generation_prompt)), 1)
            self.assertEqual(len(backend.prompts), 3)
            self.assertIn("ORIGINAL STRATEGY SECRET", backend.prompts[0])
            self.assertIn("ORIGINAL CODE PROMPT SECRET", backend.prompts[0])
            self.assertNotIn('"opponent":"lightrush"', backend.prompts[0])
            self.assertIn("ORIGINAL STRATEGY SECRET", backend.prompts[1])
            self.assertIn("IMMUTABLE MICRORTS GAMEPLAY CONTRACT", backend.prompts[1])
            self.assertIn(
                "Do not optimize for wins or losses",
                " ".join(backend.prompts[1].split()),
            )
            self.assertIn("ORIGINAL CODE PROMPT SECRET", backend.prompts[2])
            self.assertIn("IMMUTABLE MICRORTS GAMEPLAY CONTRACT", backend.prompts[2])
            self.assertIn(
                "IMMUTABLE MICRORTS ACTION AND JAVA API CONTRACT",
                backend.prompts[2],
            )

            mutation_dir = root / "mutation" / "prompt_compliance_reflection"
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
            self.assertNotIn("objectives", metadata)
            persisted_context = json.loads(
                (mutation_dir / "reflection_context.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("outcome_table", persisted_context)
            self.assertIn("match_results", persisted_context["excluded_evidence"])
            self.assertEqual(len(result.timing["reflector_llm"]["attempts"]), 1)
            self.assertEqual(len(result.timing["rewriter_llm"]["attempts"]), 2)
            write_candidate_snapshot(root.parent, result)
            snapshot = json.loads((root / "candidate.json").read_text(encoding="utf-8"))
            self.assertEqual(
                snapshot["artifacts"]["prompt_compliance_reflection"],
                "mutation/prompt_compliance_reflection/metadata.json",
            )

    def test_compliance_code_rewrite_rejects_whole_prompt_and_retries_delta(self) -> None:
        backend = ScriptedBackend((
            self._analysis(),
            "REWRITTEN STRATEGY",
            json.dumps({"rewritten_prompt": "UNVALIDATED WHOLE PROMPT"}),
            compliance_rule_delta(),
        ))
        config = ExperimentConfig.from_mapping({
            "mutation_max_attempts": 2,
            "prompt_compliance_reflection_probability": 1.0,
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
        })

        result = PromptComplianceReflectionMutation(
            config,
            reflection_backend=backend,
            rewrite_backend=backend,
        ).mutate(self.candidate, self.context)

        self.assertTrue(result.metadata["mutation"]["applied"])
        self.assertNotIn("UNVALIDATED WHOLE PROMPT", result.generation_prompt)
        self.assertIn(GENERIC_COMPLIANCE_RULE, result.generation_prompt)
        self.assertIn("previous response was rejected", backend.prompts[3].lower())
        self.assertIn(
            "Code Rewrite response must contain exactly remove_rule_ids and add_rules.",
            backend.prompts[3],
        )
        self.assertIn(
            "EAGLE Prompt Compliance Code Generation Prompt Rewrite stage",
            backend.prompts[3],
        )
        self.assertEqual(
            [attempt["status"] for attempt in result.timing["rewriter_llm"]["attempts"]],
            ["success", "error", "success"],
        )

    def test_failed_first_rewrite_preserves_both_genes_and_skips_code_rewrite(self) -> None:
        backend = ScriptedBackend((self._analysis(), ""))
        config = ExperimentConfig.from_mapping({
            "mutation_max_attempts": 1,
            "prompt_compliance_reflection_probability": 1.0,
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
        })

        result = PromptComplianceReflectionMutation(
            config,
            reflection_backend=backend,
            rewrite_backend=backend,
        ).mutate(self.candidate, self.context)

        self.assertEqual(result.strategy_prompt, self.candidate.strategy_prompt)
        self.assertEqual(result.generation_prompt, self.candidate.generation_prompt)
        self.assertFalse(result.metadata["mutation"]["applied"])
        self.assertEqual(len(backend.prompts), 2)

    def test_prompt_compliance_operator_is_selectable_as_the_third_operator(self) -> None:
        config = ExperimentConfig.from_mapping({
            "reflection_operator_mode": "static",
            "strategy_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
            "prompt_compliance_reflection_probability": 1.0,
        })
        controller = build_reflection_operator_controller(config)
        import random

        self.assertEqual(
            controller.select_operator(random.Random(7)),
            PROMPT_COMPLIANCE_REFLECTION,
        )
        record = controller.update_generation([])
        self.assertEqual(
            record["operators"][PROMPT_COMPLIANCE_REFLECTION]["usage_count"],
            1,
        )
        self.assertEqual(record["prompt_compliance_probability_after"], 1.0)
