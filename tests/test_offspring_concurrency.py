"""Concurrency contracts for independent offspring LLM stages."""

from dataclasses import replace
from pathlib import Path
import random
import tempfile
import threading
import unittest
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.offspring import (
    OffspringPlan,
    apply_offspring_mutations,
    materialize_code_reflections,
    plan_offspring,
)
from eagle.operators.adaptive import PROMPT_REFLECTION, build_reflection_operator_controller


class ConcurrentGate:
    def __init__(self):
        self.started = threading.Barrier(2, timeout=3)
        self.calls = []

    def mutate(self, child, context, *, artifact_dir=None):
        index = context.index
        role = "source" if context.candidate.candidate_id == "a" else "donor"
        self.calls.append((index, role, context.candidate.candidate_id))
        if role == "source":
            self.started.wait()
        blocked = index == 0 and role == "source"
        return replace(child, metadata={"mutation": {
            "reflection_status": "success",
            "revision_required": blocked,
            "revision_status": "pending" if blocked else "not_required",
        }}, timing={"code_reflector_llm": {"duration_seconds": 1.0}})


class ConcurrentMutation:
    def __init__(self):
        self.started = threading.Barrier(2, timeout=3)
        self.artifact_dirs = []

    def mutate(self, child, context, *, artifact_dir=None):
        self.artifact_dirs.append(artifact_dir)
        self.started.wait()
        failed = child.id == "first"
        return replace(child, metadata={**child.metadata, "mutation": {
            "applied": not failed,
            "reflection_error": "diagnosis failed" if failed else None,
        }})


class ConcurrentRevision:
    def __init__(self):
        self.started = threading.Barrier(2, timeout=3)
        self.artifact_dirs = []

    def materialize(self, child, context, *, artifact_dir=None):
        self.artifact_dirs.append(artifact_dir)
        self.started.wait()
        return replace(child, metadata={**child.metadata, "mutation": {
            "revision_status": "failed" if child.id == "first" else "success",
            "revision_error": "invalid Java" if child.id == "first" else None,
        }})


class OffspringConcurrencyTests(unittest.TestCase):
    def test_gate_tasks_overlap_but_source_blocks_donor_and_aos(self):
        a = Candidate(id="a", strategy_prompt="policy a", generation_prompt="translate a", generated_java="java a")
        b = Candidate(id="b", strategy_prompt="policy b", generation_prompt="translate b", generated_java="java b")
        config = ExperimentConfig.from_mapping({
            "population_size": 2,
            "crossover_rate": 1.0,
            "mutation_rate": 1.0,
            "reflection_operator_mode": "static",
            "strategy_reflection_probability": 0.0,
            "prompt_reflection_probability": 1.0,
            "code_reflection_probability": 0.0,
        })
        controller = build_reflection_operator_controller(config)
        gate = ConcurrentGate()
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.evolution.offspring.select_parent", side_effect=[a, b, a, b]
        ):
            plans = plan_offspring(
                [a, b], config=config, generation=1, rng=random.Random(0),
                mutations={"code": gate, "prompt": object()},
                operator_controller=controller, artifact_root=Path(directory),
            )
            self.assertEqual([plan.context_index for plan in plans], [0, 1])
            self.assertEqual([plan.mutation_name for plan in plans], ["code", "prompt"])
            self.assertEqual(controller.total_usage[PROMPT_REFLECTION], 1)
            self.assertEqual(
                [role for index, role, _ in gate.calls if index == 0],
                ["source"],
            )
            self.assertEqual(
                [role for index, role, _ in gate.calls if index == 1],
                ["source", "donor"],
            )
            self.assertEqual(len(plans[0].candidate.metadata["pre_crossover_code_checks"]), 1)
            self.assertEqual(len(plans[1].candidate.metadata["pre_crossover_code_checks"]), 2)

    def test_prompt_mutations_overlap_and_keep_result_and_failure_evidence(self):
        mutation = ConcurrentMutation()
        plans = [
            OffspringPlan(candidate=Candidate(id=name, generation=1),
                          context_index=index, mutation_name="prompt",
                          mutation=mutation, mutation_context=object())
            for index, name in enumerate(("first", "second"))
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = apply_offspring_mutations(plans, artifact_root=root)
            self.assertEqual([plan.candidate.id for plan in results], ["first", "second"])
            self.assertEqual(
                [plan.candidate.timing["mutation"]["status"] for plan in results],
                ["failed", "success"],
            )
            self.assertEqual(
                results[0].candidate.timing["mutation"]["error"], "diagnosis failed"
            )
            self.assertCountEqual(mutation.artifact_dirs, [root / "first", root / "second"])

    def test_code_revisions_overlap_and_keep_ordered_candidate_artifacts(self):
        mutation = ConcurrentRevision()
        plans = [
            OffspringPlan(candidate=Candidate(id=name, generation=1),
                          context_index=index, mutation_name="code",
                          mutation=mutation, mutation_context=object())
            for index, name in enumerate(("first", "second"))
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = materialize_code_reflections(plans, artifact_root=root)
            self.assertEqual([plan.candidate.id for plan in results], ["first", "second"])
            self.assertEqual(
                [plan.candidate.metadata["mutation"]["revision_status"] for plan in results],
                ["failed", "success"],
            )
            self.assertEqual(
                results[0].candidate.metadata["mutation"]["revision_error"], "invalid Java"
            )
            self.assertCountEqual(mutation.artifact_dirs, [root / "first", root / "second"])


if __name__ == "__main__":
    unittest.main()
