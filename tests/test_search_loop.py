"""Shared continuation preserves checkpoint state and finalization boundaries."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, sentinel

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.generation import GenerationStepResult
from eagle.evolution.loop import continue_search
from eagle.evolution.runtime import SearchRuntime


class SearchLoopTests(unittest.TestCase):
    def setUp(self):
        self.config = ExperimentConfig.from_mapping({"generations": 5, "stagnation_generations": 2})
        self.population = [Candidate(id="parent", status="evaluated")]
        self.runtime = SearchRuntime(
            client=sentinel.client,
            generation_client=sentinel.generation_client,
            generation_backend=sentinel.backend,
            initial_policy_backend=None,
            llm_logger=None,
            mutations=sentinel.mutations,
            operator_controller=sentinel.controller,
        )
        self.arguments = dict(
            config=self.config, run_dir=Path("runs/example"), run_id="example",
            runtime=self.runtime, population=self.population,
            completed_generation=0, stagnation_count=0, error_memory=(),
            self_play_opponent_snapshot=None, mock=True,
        )

    def test_next_generation_receives_all_updated_state_before_early_stop(self):
        first = GenerationStepResult(
            population=[replace(self.population[0], id="child")],
            self_play_opponent_snapshot=[], population_state_signature="updated",
            stagnation_count=1, error_memory=({"error": "retained"},),
            diversity={}, aos_record={}, stop_reason=None,
            config=replace(self.config, llm_max_tokens=1234),
        )
        stopped = replace(first, stagnation_count=2, stop_reason="stagnation_2_generations")
        with patch("eagle.evolution.loop.run_generation_step", side_effect=[first, stopped]) as step, \
                patch("eagle.evolution.loop.write_summary") as summary, \
                patch("eagle.evolution.loop.finalize_run") as finalize:
            result = continue_search(**self.arguments)
        self.assertEqual([call.kwargs["generation"] for call in step.call_args_list], [1, 2])
        second = SimpleNamespace(**step.call_args_list[1].kwargs)
        self.assertIs(second.population, first.population)
        self.assertIs(second.config, first.config)
        self.assertIs(second.self_play_opponent_snapshot, first.self_play_opponent_snapshot)
        self.assertIs(second.error_memory, first.error_memory)
        self.assertEqual(second.population_state_signature, "updated")
        self.assertEqual(second.stagnation_count, 1)
        self.assertIs(second.rng, step.call_args_list[0].kwargs["rng"])
        self.assertIs(second.generation_backend, self.runtime.generation_backend)
        self.assertIs(second.shared_client, self.runtime.client)
        self.assertIs(second.generation_client, self.runtime.generation_client)
        self.assertIs(second.mutations, self.runtime.mutations)
        self.assertIs(second.operator_controller, self.runtime.operator_controller)
        self.assertEqual(result.completed_generation, 2)
        self.assertEqual(result.stop_reason, stopped.stop_reason)
        self.assertIs(result.final_population, stopped.population)
        self.assertEqual(summary.call_args.kwargs["completed_generation"], 2)
        finalize.assert_called_once_with(result.run_dir, stopped.population, stop_reason=stopped.stop_reason)

    def test_already_stagnant_checkpoint_finalizes_without_another_generation(self):
        self.arguments.update(completed_generation=3, stagnation_count=2)
        with patch("eagle.evolution.loop.run_generation_step") as step, \
                patch("eagle.evolution.loop.write_summary") as summary, \
                patch("eagle.evolution.loop.finalize_run") as finalize:
            result = continue_search(**self.arguments)
        step.assert_not_called()
        self.assertEqual(result.completed_generation, 3)
        self.assertEqual(result.stop_reason, "stagnation_2_generations")
        self.assertEqual(summary.call_args.kwargs["stop_reason"], result.stop_reason)
        finalize.assert_called_once()

    def test_failed_or_interrupted_generation_does_not_finalize(self):
        for failure in (KeyboardInterrupt(), RuntimeError("generation failed")):
            with self.subTest(failure=type(failure).__name__), \
                    patch("eagle.evolution.loop.run_generation_step", side_effect=failure), \
                    patch("eagle.evolution.loop.write_summary") as summary, \
                    patch("eagle.evolution.loop.finalize_run") as finalize:
                with self.assertRaises(type(failure)):
                    continue_search(**self.arguments)
                summary.assert_not_called()
                finalize.assert_not_called()
