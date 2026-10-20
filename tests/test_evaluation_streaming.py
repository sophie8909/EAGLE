from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.pipeline import evaluate_population
from eagle.execution import current_llm_worker_slot


class EvaluationStreamingTests(unittest.TestCase):
    def test_fast_candidate_evaluates_while_other_candidates_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            population = [Candidate(id=value) for value in ("a", "b", "c")]
            config = ExperimentConfig.from_mapping({"population_size": 3})
            slow_release = threading.Event()
            slow_finished = threading.Event()
            third_started = threading.Event()
            evaluation_order: list[str] = []
            ordinals: dict[str, int] = {}
            slots: dict[int, int] = {}

            def transform(index: int, candidate: Candidate) -> Candidate:
                slots[index] = current_llm_worker_slot()
                if index == 0:
                    self.assertTrue(slow_release.wait(timeout=3))
                    slow_finished.set()
                elif index == 2:
                    third_started.set()
                return candidate

            def decode(candidate: Candidate, **_kwargs):
                return SimpleNamespace(candidate_id=candidate.id)

            def evaluate(candidate: Candidate, *, ordinal: int, bounded_generation, **_kwargs):
                evaluation_order.append(candidate.id)
                ordinals[candidate.id] = ordinal
                self.assertEqual(bounded_generation.candidate_id, candidate.id)
                if candidate.id == "b":
                    self.assertTrue(third_started.wait(timeout=3))
                    self.assertFalse(slow_finished.is_set())
                    slow_release.set()
                return SimpleNamespace(candidate=candidate, match_results=[])

            with (
                patch(
                    "eagle.evaluation.pipeline.decoding.decode_validate_compile_candidate",
                    side_effect=decode,
                ),
                patch("eagle.evaluation.pipeline.evaluate_candidate", side_effect=evaluate),
                patch("eagle.evaluation.pipeline.write_candidate_inputs"),
                patch("eagle.evaluation.pipeline.write_candidate_artifacts"),
                patch("eagle.evaluation.pipeline.print_progress"),
            ):
                evaluated = evaluate_population(
                    iter(population),
                    population_size=len(population),
                    candidate_transform=transform,
                    generation=1,
                    config=config,
                    backend=object(),
                    generated_agents_dir=root / "java",
                    classes_dir=root / "classes",
                    candidates_dir=root / "candidates",
                    mock=True,
                )

            self.assertEqual(evaluation_order[0], "b")
            self.assertEqual([candidate.id for candidate in evaluated], ["a", "b", "c"])
            self.assertEqual(ordinals, {"a": 0, "b": 1, "c": 2})
            self.assertEqual(slots, {0: 0, 1: 1, 2: 0})

    def test_preparation_error_cancels_queue_and_waits_for_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            population = [Candidate(id=str(index)) for index in range(4)]
            config = ExperimentConfig.from_mapping({"population_size": 4})
            active_started = threading.Event()
            release_active = threading.Event()
            failure_raised = threading.Event()
            started: list[int] = []
            errors: list[BaseException] = []

            def transform(index: int, candidate: Candidate) -> Candidate:
                started.append(index)
                if index == 0:
                    self.assertTrue(active_started.wait(timeout=3))
                    failure_raised.set()
                    raise RuntimeError("prepare failed")
                if index == 1:
                    active_started.set()
                    self.assertTrue(release_active.wait(timeout=3))
                return candidate

            def invoke() -> None:
                try:
                    evaluate_population(
                        iter(population),
                        population_size=len(population),
                        candidate_transform=transform,
                        generation=1,
                        config=config,
                        backend=object(),
                        generated_agents_dir=root / "java",
                        classes_dir=root / "classes",
                        candidates_dir=root / "candidates",
                        mock=True,
                    )
                except BaseException as exc:
                    errors.append(exc)

            with (
                patch("eagle.evaluation.pipeline.write_candidate_inputs"),
                patch("eagle.evaluation.pipeline.write_candidate_artifacts"),
                patch("eagle.evaluation.pipeline.evaluate_candidate") as evaluate,
            ):
                caller = threading.Thread(target=invoke)
                caller.start()
                self.assertTrue(failure_raised.wait(timeout=3))
                time.sleep(0.05)
                self.assertTrue(caller.is_alive())
                release_active.set()
                caller.join(timeout=3)

            self.assertFalse(caller.is_alive())
            self.assertEqual(started, [0, 1])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], RuntimeError)
            self.assertEqual(str(errors[0]), "prepare failed")
            evaluate.assert_not_called()

    def test_self_play_snapshot_without_current_candidates_builds_before_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            population = [Candidate(id="a"), Candidate(id="b")]
            config = ExperimentConfig.from_mapping({
                "population_size": 2,
                "reflection_operator_mode": "static",
                "evaluation": {"mode": "self_play"},
            })
            snapshot_ready = threading.Event()
            prepared_arguments: list[list[object]] = []

            def opponents(_snapshot, *, prepared, **_kwargs):
                prepared_arguments.append(prepared)
                snapshot_ready.set()
                return ()

            def transform(_index: int, candidate: Candidate) -> Candidate:
                self.assertTrue(snapshot_ready.is_set())
                return candidate

            def decode(candidate: Candidate, **_kwargs):
                return SimpleNamespace(candidate_id=candidate.id)

            def evaluate(candidate: Candidate, **_kwargs):
                return SimpleNamespace(candidate=candidate, match_results=[])

            with (
                patch(
                    "eagle.evaluation.pipeline.opponent_setup._build_self_play_opponents",
                    side_effect=opponents,
                ) as build_opponents,
                patch(
                    "eagle.evaluation.pipeline.decoding.decode_validate_compile_candidate",
                    side_effect=decode,
                ),
                patch("eagle.evaluation.pipeline.evaluate_candidate", side_effect=evaluate),
                patch("eagle.evaluation.pipeline.write_candidate_inputs"),
                patch("eagle.evaluation.pipeline.write_candidate_artifacts"),
                patch("eagle.evaluation.pipeline.print_progress"),
            ):
                evaluated = evaluate_population(
                    iter(population),
                    population_size=len(population),
                    candidate_transform=transform,
                    generation=1,
                    config=config,
                    backend=object(),
                    generated_agents_dir=root / "java",
                    classes_dir=root / "classes",
                    candidates_dir=root / "candidates",
                    mock=True,
                )

            build_opponents.assert_called_once()
            self.assertEqual(prepared_arguments, [[]])
            self.assertEqual([candidate.id for candidate in evaluated], ["a", "b"])

    def test_unresolved_same_batch_self_play_snapshot_keeps_preparation_barrier(self) -> None:
        for streaming in (False, True):
            with self.subTest(streaming=streaming), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                population = [Candidate(id="a"), Candidate(id="b")]
                source = iter(population) if streaming else population
                config = ExperimentConfig.from_mapping({
                    "population_size": 2,
                    "reflection_operator_mode": "static",
                    "evaluation": {"mode": "self_play"},
                })
                prepared_sources: list[tuple[str, str]] = []

                def decode(candidate: Candidate, **_kwargs):
                    return SimpleNamespace(
                        candidate_id=candidate.id,
                        generation=SimpleNamespace(assembled_java=f"prepared-{candidate.id}"),
                    )

                def opponents(_snapshot, *, prepared, **_kwargs):
                    prepared_sources.extend(
                        (candidate.id, bounded.generation.assembled_java)
                        for candidate, bounded in prepared
                    )
                    return ()

                def evaluate(candidate: Candidate, **_kwargs):
                    return SimpleNamespace(candidate=candidate, match_results=[])

                with (
                    patch(
                        "eagle.evaluation.pipeline.opponent_setup._build_self_play_opponents",
                        side_effect=opponents,
                    ) as build_opponents,
                    patch(
                        "eagle.evaluation.pipeline.decoding.decode_validate_compile_candidate",
                        side_effect=decode,
                    ),
                    patch("eagle.evaluation.pipeline.evaluate_candidate", side_effect=evaluate),
                    patch("eagle.evaluation.pipeline.write_candidate_inputs"),
                    patch("eagle.evaluation.pipeline.write_candidate_artifacts"),
                    patch("eagle.evaluation.pipeline.print_progress"),
                ):
                    evaluated = evaluate_population(
                        source,
                        population_size=2,
                        generation=1,
                        config=config,
                        backend=object(),
                        generated_agents_dir=root / "java",
                        classes_dir=root / "classes",
                        candidates_dir=root / "candidates",
                        mock=True,
                        opponent_candidates=[Candidate(id="a")],
                    )

                build_opponents.assert_called_once()
                self.assertEqual(
                    prepared_sources,
                    [("a", "prepared-a"), ("b", "prepared-b")],
                )
                self.assertEqual([candidate.id for candidate in evaluated], ["a", "b"])

    def test_evaluation_interrupt_closes_source_and_waits_for_active_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ExperimentConfig.from_mapping({"population_size": 4})
            active_started = threading.Event()
            release_active = threading.Event()
            evaluation_interrupted = threading.Event()
            source_closed = threading.Event()
            errors: list[BaseException] = []

            def population():
                try:
                    for index in range(4):
                        yield Candidate(id=str(index))
                finally:
                    source_closed.set()

            def transform(index: int, candidate: Candidate) -> Candidate:
                if index == 0:
                    self.assertTrue(active_started.wait(timeout=3))
                else:
                    active_started.set()
                    self.assertTrue(release_active.wait(timeout=3))
                return candidate

            def decode(candidate: Candidate, **_kwargs):
                return SimpleNamespace(candidate_id=candidate.id)

            def evaluate(_candidate: Candidate, **_kwargs):
                evaluation_interrupted.set()
                raise KeyboardInterrupt("stop evaluation")

            def invoke() -> None:
                try:
                    evaluate_population(
                        population(),
                        population_size=4,
                        candidate_transform=transform,
                        generation=1,
                        config=config,
                        backend=object(),
                        generated_agents_dir=root / "java",
                        classes_dir=root / "classes",
                        candidates_dir=root / "candidates",
                        mock=True,
                    )
                except BaseException as exc:
                    errors.append(exc)

            with (
                patch(
                    "eagle.evaluation.pipeline.decoding.decode_validate_compile_candidate",
                    side_effect=decode,
                ),
                patch("eagle.evaluation.pipeline.evaluate_candidate", side_effect=evaluate),
                patch("eagle.evaluation.pipeline.write_candidate_inputs"),
                patch("eagle.evaluation.pipeline.write_candidate_artifacts"),
            ):
                caller = threading.Thread(target=invoke)
                caller.start()
                self.assertTrue(evaluation_interrupted.wait(timeout=3))
                self.assertTrue(source_closed.wait(timeout=3))
                self.assertTrue(caller.is_alive())
                release_active.set()
                caller.join(timeout=3)

            self.assertFalse(caller.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], KeyboardInterrupt)


if __name__ == "__main__":
    unittest.main()
