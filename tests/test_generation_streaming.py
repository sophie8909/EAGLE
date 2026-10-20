"""The production generation path overlaps mating dependencies and matches."""

from dataclasses import replace
from pathlib import Path
import random
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.generation import run_generation_step
from eagle.operators.adaptive import build_reflection_operator_controller
from eagle.operators.selection import population_signature
from eagle.strategy_dsl import VERSION, normalize_strategy_dsl


class GenerationStreamingTests(unittest.TestCase):
    def test_first_child_matches_before_later_source_gate_completes(self):
        second_gate_started = threading.Event()
        first_match_started = threading.Event()
        second_gate_finished = threading.Event()
        match_order = []

        class Gate:
            def mutate(self, child, context, *, artifact_dir=None):
                if context.index == 1:
                    second_gate_started.set()
                    if not first_match_started.wait(3):
                        raise AssertionError("match waited for the entire source gate batch")
                    second_gate_finished.set()
                return replace(child, metadata={"mutation": {
                    "reflection_status": "success", "revision_required": False,
                    "revision_status": "not_required",
                }})

        config = ExperimentConfig.from_mapping({
            "population_size": 2, "mutation_rate": 0.0, "crossover_rate": 0.0,
            "reflection_operator_mode": "static",
        })
        parent = Candidate(
            id="parent", generated_java="existing source", status="evaluated",
            strategy_prompt=normalize_strategy_dsl({"version": VERSION, "rules": []}),
        )

        def evaluate(candidate, *, ordinal, **_kwargs):
            if ordinal == 0:
                self.assertTrue(second_gate_started.wait(3))
                self.assertFalse(second_gate_finished.is_set())
                first_match_started.set()
            match_order.append(ordinal)
            return SimpleNamespace(candidate=replace(candidate, status="evaluated"), match_results=[])

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("eagle.evaluation.pipeline.decoding.decode_validate_compile_candidate", return_value=object()),
            patch("eagle.evaluation.pipeline.evaluate_candidate", side_effect=evaluate),
            patch("eagle.evaluation.pipeline.write_candidate_artifacts"),
            patch("eagle.evaluation.pipeline.print_progress"),
            patch("eagle.evolution.generation.record_generation"),
        ):
            root = Path(directory)
            result = run_generation_step(
                generation=1, config=config, run_dir=root,
                candidates_dir=root / "candidates", generated_agents_dir=root / "agents",
                classes_dir=root / "classes", mock=True, run_id="overlap",
                rng=random.Random(0), population=[parent],
                population_state_signature=population_signature([parent]),
                stagnation_count=0, error_memory=(), self_play_opponent_snapshot=None,
                generation_backend=object(), shared_client=None, generation_client=None,
                mutations={"code": Gate()},
                operator_controller=build_reflection_operator_controller(config),
            )
        self.assertTrue(second_gate_finished.is_set())
        self.assertEqual(match_order, [0, 1])
        self.assertEqual(len(result.population), 2)


if __name__ == "__main__":
    unittest.main()
