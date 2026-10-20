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
    apply_offspring_mutation,
    apply_offspring_mutations,
    iter_offspring_plans,
    materialize_code_reflection,
    materialize_code_reflections,
    plan_offspring,
)
from eagle.execution import current_llm_worker_slot, llm_worker_slot
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

    def test_first_plan_can_mutate_before_later_source_gate_completes(self):
        later_gate_started = threading.Event()
        first_mutation_finished = threading.Event()
        observed = []

        class Gate:
            def mutate(self, child, context, *, artifact_dir=None):
                if context.index == 0:
                    if not later_gate_started.wait(3):
                        raise AssertionError("Second source gate never started")
                else:
                    later_gate_started.set()
                    if not first_mutation_finished.wait(3):
                        raise AssertionError("First mutation waited for the whole gate batch")
                return replace(child, metadata={"mutation": {
                    "reflection_status": "success", "revision_required": False,
                    "revision_status": "not_required",
                }})

        class Mutation:
            def mutate(self, child, context, *, artifact_dir=None):
                observed.append(context.index)
                if context.index == 0:
                    first_mutation_finished.set()
                return replace(child, metadata={**child.metadata, "mutation": {"applied": True}})

        parent = Candidate(id="a", strategy_prompt='{"version":"eagle-strategy-dsl-v1","rules":[]}', generation_prompt="translate", generated_java="java")
        config = ExperimentConfig.from_mapping({
            "population_size": 2, "crossover_rate": 0.0, "mutation_rate": 1.0,
            "reflection_operator_mode": "static", "strategy_reflection_probability": 0.0,
            "prompt_reflection_probability": 1.0, "code_reflection_probability": 0.0,
        })
        controller = build_reflection_operator_controller(config)
        plans = iter_offspring_plans(
            [parent], config=config, generation=1, rng=random.Random(0),
            mutations={"code": Gate(), "prompt": Mutation()}, operator_controller=controller,
        )
        try:
            first = next(plans)
            self.assertEqual(controller.total_usage[PROMPT_REFLECTION], 1)
            apply_offspring_mutation(first, total_count=2)
            remaining = list(plans)
        finally:
            first_mutation_finished.set()
            plans.close()
        self.assertEqual(observed, [0])
        self.assertEqual([first.context_index, remaining[0].context_index], [0, 1])
        self.assertEqual(controller.total_usage[PROMPT_REFLECTION], 2)

    def test_single_plan_operations_keep_callers_worker_slot(self):
        observed = []

        class Mutation:
            def mutate(self, child, context, *, artifact_dir=None):
                observed.append(("mutation", current_llm_worker_slot()))
                return replace(child, metadata={"mutation": {"applied": True}})

            def materialize(self, child, context, *, artifact_dir=None):
                observed.append(("revision", current_llm_worker_slot()))
                return child

        mutation = Mutation()
        plan = OffspringPlan(candidate=Candidate(id="first", generation=1), context_index=1,
                             mutation_name="prompt", mutation=mutation, mutation_context=object())
        with llm_worker_slot(1):
            plan = apply_offspring_mutation(plan, total_count=2)
            materialize_code_reflection(replace(plan, mutation_name="code"), total_count=2)
        self.assertEqual(observed, [("mutation", 1), ("revision", 1)])

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
