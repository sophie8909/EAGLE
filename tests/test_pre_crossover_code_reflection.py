from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.offspring import plan_offspring, apply_offspring_mutations, materialize_code_reflections
from eagle.operators.adaptive import build_reflection_operator_controller, CODE_REFLECTION


class Gate:
    def __init__(self, events, faulty=(), failed=()):
        self.events, self.faulty, self.failed = events, faulty, failed

    def mutate(self, child, context, *, artifact_dir=None):
        source = context.candidate.candidate_id
        self.events.append(("check", source, child.inherited_java, child.strategy_prompt))
        faulty = source in self.faulty
        failed = source in self.failed
        return replace(child, timing={"code_reflector_llm": {"duration_seconds": 1.0}}, metadata={"mutation": {
            "reflection_status": "failed" if failed else "success",
            "revision_required": faulty,
            "revision_status": "not_run" if failed else "pending" if faulty else "not_required",
        }})

    def materialize(self, child, context, *, artifact_dir=None):
        self.events.append(("materialize", context.candidate.candidate_id))
        return child


class Mutation:
    def __init__(self, events):
        self.events = events

    def mutate(self, child, context, *, artifact_dir=None, mutation_intent=None):
        self.events.append(("mutation",))
        return replace(child, metadata={**child.metadata, "mutation": {"applied": True}})


class PreCrossoverGateTests(unittest.TestCase):
    def plans(self, events, *, faulty=(), failed=(), size=1, code_only=False, artifact_root=None):
        a = Candidate(id="a", strategy_prompt="policy a", generation_prompt="translator a", generated_java="java a")
        b = Candidate(id="b", strategy_prompt="policy b", generation_prompt="translator b", generated_java="java b")
        config = ExperimentConfig.from_mapping({"population_size": size, "crossover_rate": 1.0,
            "mutation_rate": 1.0, "strategy_reflection_probability": 0.0,
            "prompt_reflection_probability": 0.0 if code_only else 1.0,
            "code_reflection_probability": 1.0 if code_only else 0.0,
            "reflection_operator_mode": "static"})
        gate = Gate(events, faulty, failed)
        controller = build_reflection_operator_controller(config)
        original_select = controller.select_operator
        def select(*args, **kwargs):
            events.append(("assign",))
            return original_select(*args, **kwargs)
        controller.select_operator = select
        with patch("eagle.evolution.offspring.select_parent", side_effect=[a, b] * size):
            plans = plan_offspring([a, b], config=config, generation=1, rng=random.Random(0),
                mutations={"code": gate, "prompt": Mutation(events)}, operator_controller=controller,
                artifact_root=artifact_root)
        return plans, config

    def test_both_sources_checked_before_assignment_and_mutation(self):
        events = []
        plans, _ = self.plans(events)
        self.assertEqual([e[0] for e in events], ["check", "check", "assign"])
        self.assertEqual(events[:2], [("check", "a", "java a", "policy a"), ("check", "b", "java b", "policy b")])
        plans = apply_offspring_mutations(plans)
        materialize_code_reflections(plans)
        self.assertEqual([e[0] for e in events], ["check", "check", "assign", "mutation"])
        self.assertEqual(len(plans[0].candidate.metadata["pre_crossover_code_checks"]), 2)
        self.assertEqual(plans[0].candidate.timing["pre_crossover_code_checks_llm"]["duration_seconds"], 2.0)

    def test_faulty_source_and_donor_skip_crossover_and_normal_mutation(self):
        for source in ("a", "b"):
            with self.subTest(source=source):
                events = []
                plans, _ = self.plans(events, faulty=(source,))
                plan = plans[0]
                self.assertEqual(plan.candidate.parent_ids, (source,))
                self.assertEqual(plan.candidate.strategy_prompt, "policy " + source)
                self.assertEqual(plan.candidate.generation_prompt, "translator " + source)
                self.assertEqual(plan.candidate.generated_java, "java " + source)
                self.assertIsNone(plan.operator_id)
                self.assertEqual(plan.candidate.timing["pre_crossover_code_checks_llm"]["duration_seconds"], 0.0 if source == "a" else 1.0)
                self.assertEqual(plan.candidate.timing["code_reflector_llm"]["duration_seconds"], 1.0)
                plans = apply_offspring_mutations(plans)
                materialize_code_reflections(plans)
                self.assertNotIn(("assign",), events)
                self.assertNotIn(("mutation",), events)
                self.assertEqual(events[-1], ("materialize", source))

    def test_failed_gate_is_retained_and_never_crossed(self):
        events = []
        plans, _ = self.plans(events, failed=("a",))
        self.assertEqual(plans[0].candidate.parent_ids, ("a",))
        self.assertEqual(plans[0].candidate.generated_java, "java a")
        self.assertEqual(len(events), 1)

    def test_zero_normal_weights_still_run_independent_gate(self):
        events = []
        plans, config = self.plans(events, code_only=True)
        self.assertEqual(config.reflection_operator_settings.enabled_operators, ())
        self.assertEqual(config.reflection_operator_settings.initial_probabilities[CODE_REFLECTION], 0.0)
        self.assertIsNone(plans[0].mutation_name)
        self.assertEqual([e[0] for e in events], ["check", "check"])

    def test_reused_sources_have_distinct_deterministic_audit_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            plans, _ = self.plans([], size=2, artifact_root=Path(directory))
            refs = [check for plan in plans for check in plan.candidate.metadata["pre_crossover_code_checks"]]
            ids = [check["gate_candidate_id"] for check in refs]
            self.assertEqual(len(set(ids)), 4)
            for identity in ids:
                self.assertTrue((Path(directory) / identity / "candidate.json").is_file())
                self.assertTrue((Path(directory) / identity / "lineage.json").is_file())
                self.assertEqual(json.loads((Path(directory) / identity / "candidate.json").read_text())["operator"], "code_check")
            repeated, _ = self.plans([], size=2)
            self.assertEqual([p.candidate.id for p in plans], [p.candidate.id for p in repeated])

    def test_legacy_controller_state_rejected_and_current_state_resumes(self):
        _, config = self.plans([])
        with self.assertRaisesRegex(ValueError, "predates"):
            build_reflection_operator_controller(config, state={"mode": "static"})
        controller = build_reflection_operator_controller(config)
        state = controller.initial_generation_record()["state"]
        resumed = build_reflection_operator_controller(config, state=state)
        self.assertEqual(resumed.initial_generation_record()["selection_probabilities"],
                         controller.initial_generation_record()["selection_probabilities"])

    def test_streamed_child_diagnosis_precedes_revision_and_evaluation(self):
        from eagle.evolution.generation import run_generation_step
        from eagle.operators.selection import population_signature
        from eagle.strategy_dsl import normalize_strategy_dsl, VERSION
        events = []
        parent = Candidate(id="a", strategy_prompt=normalize_strategy_dsl({"version": VERSION, "rules": []}),
                           generated_java="java a")
        config = ExperimentConfig.from_mapping({"population_size": 1, "mutation_rate": 1.0,
            "crossover_rate": 0.0, "reflection_operator_mode": "static",
            "model": {"name": "primary"},
            "generation_model": {"name": "generator", "host": "generation.test"}})
        gate = Gate(events, faulty=("a",))
        def evaluate(children, **kwargs):
            transform = kwargs["candidate_transform"]
            children = [transform(index, child) for index, child in enumerate(children)]
            events.append(("evaluate",))
            return [replace(child, status="evaluated") for child in children]
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.evolution.generation.evaluate_population", side_effect=evaluate
        ), patch("eagle.evolution.generation.record_generation"):

            root = Path(directory)
            run_generation_step(generation=1, config=config, run_dir=root,
                candidates_dir=root / "candidates", generated_agents_dir=root / "agents",
                classes_dir=root / "classes", mock=True, run_id="boundary", rng=random.Random(0),
                population=[parent], population_state_signature=population_signature([parent]),
                stagnation_count=0, error_memory=(), self_play_opponent_snapshot=None,
                generation_backend=None, shared_client=None, generation_client=None,
                mutations={"code": gate}, operator_controller=build_reflection_operator_controller(config))
        self.assertEqual([event[0] for event in events], ["check", "materialize", "evaluate"])

    def test_generation_aggregate_counts_healthy_and_faulty_gate_calls_once(self):
        from eagle.timing import build_generation_event
        healthy, _ = self.plans([])
        defective, _ = self.plans([], faulty=("b",))
        for plans in (healthy, defective):
            record = build_generation_event(run_id="timing", generation=1,
                candidates=[plans[0].candidate], span={})
            self.assertEqual(record["aggregate_llm_request_duration_seconds"], 2.0)
        child = replace(defective[0].candidate, timing={**defective[0].candidate.timing,
                        "code_revision_llm": {"duration_seconds": 3.0}})
        self.assertEqual(build_generation_event(run_id="timing", generation=1,
            candidates=[child], span={})["aggregate_llm_request_duration_seconds"], 5.0)

    def test_malformed_and_timeout_diagnoses_fail_closed_with_raw_evidence(self):
        from eagle.operators.code import CodeReflectionMutation
        from eagle.strategy_dsl import VERSION, normalize_strategy_dsl
        class ReflectionBackend:
            def __init__(self, timeout):
                self.timeout = timeout
            def generate(self, prompt):
                if self.timeout:
                    raise TimeoutError("gate timeout")
                return "malformed response"
        for timeout in (True, False):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as directory:
                config = ExperimentConfig.from_mapping({"population_size": 1, "crossover_rate": 0.0,
                    "mutation_rate": 1.0, "mutation_max_attempts": 1, "reflection_operator_mode": "static"})
                source = Candidate(id="source", strategy_prompt=normalize_strategy_dsl({"version": VERSION, "rules": []}),
                                   generated_java="package ai.generated; public class CandidateAgent {}")
                gate = CodeReflectionMutation(config, backend=object(),
                        reflection_backend=ReflectionBackend(timeout))
                plans = plan_offspring([source], config=config, generation=1, rng=random.Random(0),
                    mutations={"code": gate}, operator_controller=build_reflection_operator_controller(config),
                    artifact_root=Path(directory))
                self.assertEqual(plans[0].candidate.parent_ids, (source.id,))
                self.assertIsNone(plans[0].operator_id)
                self.assertEqual(plans[0].candidate.metadata["mutation"]["reflection_status"], "failed")
                self.assertEqual(plans[0].candidate.generated_java, source.generated_java)
                materialized = materialize_code_reflections(apply_offspring_mutations(plans), artifact_root=Path(directory))
                self.assertEqual(materialized[0].candidate.generated_java, source.generated_java)
                stage = Path(directory) / plans[0].candidate.id / "mutation" / "code_reflection"
                self.assertTrue((stage / "reflector_attempt_001_request.txt").is_file())
                self.assertEqual(json.loads((stage.parents[1] / "lineage.json").read_text())["operator"], "mutation")
                if not timeout:
                    self.assertEqual((stage / "reflector_attempt_001_response_raw.txt").read_text(), "malformed response")
