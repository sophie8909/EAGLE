from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.execution import LLM_WORKERS, current_llm_worker_slot, parallel_map
from eagle.generation.backend import OpenAICompatibleGenerationBackend
from eagle.llm import LLMCallLogger
from eagle.operators.initialization import initialize_population
from eagle.strategy_dsl import worker_rush_policy


class Response:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return json.dumps({"choices": [{"message": {"content": self.content}}]}).encode()


class ExecutionConcurrencyTests(unittest.TestCase):
    def test_ordered_map_overlaps_tasks_with_a_fixed_worker_bound(self):
        barrier = threading.Barrier(LLM_WORKERS)
        lock = threading.Lock()
        active = maximum = 0
        finished = []
        released = [threading.Event(), threading.Event()]

        def task(index):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            barrier.wait(timeout=3)
            if index % 2 == 0:
                self.assertTrue(released[index // 2].wait(timeout=3))
            with lock:
                active -= 1
                finished.append(index)
            if index % 2:
                released[index // 2].set()
            return index

        self.assertEqual(parallel_map(task, range(4)), list(range(4)))
        self.assertEqual(maximum, LLM_WORKERS)
        self.assertEqual(finished[0], 1)

    def test_shared_generation_backend_keeps_attempts_and_artifacts_per_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = LLMCallLogger(root / "llm_logs", timing_path=root / "timing.jsonl")
            backend = OpenAICompatibleGenerationBackend("http://localhost:8080", "test", logger=logger, seed=17)
            barrier = threading.Barrier(2)

            def transport(request, **_kwargs):
                body = json.loads(request.data)
                barrier.wait(timeout=3)
                return Response("response:" + body["messages"][0]["content"])

            def generate(index):
                name = ("a", "b")[index]
                backend.set_generation_attempt_context(index + 1, name + ":attempt")
                backend.set_generation_request_kind("initial_decode" if index == 0 else "code_reflection")
                backend.set_request_artifact_dir(root / "candidates" / name / "mutation" / "code_reflection")
                return backend.generate_from_request(Candidate(id=name, generation=1), "CandidateAgent", name)

            with patch("eagle.generation.backend.urllib.request.urlopen", side_effect=transport), patch.dict("os.environ", {"EAGLE_LLM_PROGRESS": "0"}):
                self.assertEqual(parallel_map(generate, range(2)), ["response:a", "response:b"])
            records = {record["candidate_id"]: record for record in (
                json.loads(path.read_text()) for path in logger.log_dir.glob("*.json")
            )}
            self.assertEqual(records["a"]["generation_attempt"], 1)
            self.assertEqual(records["b"]["generation_attempt"], 2)
            self.assertEqual(records["a"]["generation_request_kind"], "initial_decode")
            self.assertEqual(records["b"]["generation_request_kind"], "code_reflection")
            self.assertNotEqual(records["a"]["sampling_seed"], records["b"]["sampling_seed"])
            for name, record in records.items():
                self.assertIn("candidates/" + name + "/", record["artifact_refs"]["response_raw"])
                self.assertEqual((root / record["artifact_refs"]["response_raw"]).read_text(), "response:" + name)
            events = [json.loads(line) for line in (root / "timing.jsonl").read_text().splitlines()]
            self.assertEqual(len(events), 2)

    def test_self_play_waits_for_all_parallel_java_preparation_in_input_order(self):
        from eagle.evaluation.pipeline import evaluate_population
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ExperimentConfig.from_mapping({
                "reflection_operator_mode": "static", "evaluation": {"mode": "self_play"},
            })
            population = [Candidate(id="a"), Candidate(id="b")]
            barrier = threading.Barrier(2)
            ready = set()
            prepared_order = []

            def decode(candidate, **_kwargs):
                barrier.wait(timeout=3)
                ready.add(candidate.id)
                return SimpleNamespace(candidate_id=candidate.id)

            def opponents(_population, *, prepared, **_kwargs):
                self.assertEqual(ready, {"a", "b"})
                prepared_order.extend(candidate.id for candidate, _ in prepared)
                return ()

            def evaluate(candidate, *, bounded_generation, **_kwargs):
                self.assertEqual(ready, {"a", "b"})
                self.assertEqual(bounded_generation.candidate_id, candidate.id)
                return SimpleNamespace(candidate=candidate, match_results=[])

            with patch("eagle.evaluation.pipeline.decoding.decode_validate_compile_candidate", side_effect=decode), \
                 patch("eagle.evaluation.pipeline.opponent_setup._build_self_play_opponents", side_effect=opponents), \
                 patch("eagle.evaluation.pipeline.evaluate_candidate", side_effect=evaluate), \
                 patch("eagle.evaluation.pipeline.write_candidate_artifacts"), \
                 patch("eagle.evaluation.pipeline.print_progress"):
                evaluated = evaluate_population(
                    population, generation=1, config=config, backend=object(),
                    generated_agents_dir=root / "java", classes_dir=root / "classes",
                    candidates_dir=root / "candidates", mock=True,
                    opponent_candidates=[population[0]],
                )
            self.assertEqual(prepared_order, ["a", "b"])
            self.assertEqual([candidate.id for candidate in evaluated], ["a", "b"])

    def test_parallel_initial_policy_duplicates_retry_in_order_with_original_limit(self):
        for attempts in (1, 2):
            with self.subTest(attempts=attempts), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "candidates"
                config = ExperimentConfig.from_mapping({
                    "candidate_java_mode": "inherited_genotype",
                    "initial_population_mode": "llm_generated_policies",
                    "population_size": 3,
                    "initial_policy_max_attempts": attempts,
                    "seed_prompt_files": ["seeds/worker_rush_policy.txt"],
                })
                barrier = threading.Barrier(2)
                requests = []
                slots = []

                class Backend:
                    def generate(self, prompt):
                        requests.append(prompt)
                        slots.append(current_llm_worker_slot())
                        duplicate_retry = "earlier parallel population policy" in prompt
                        if not duplicate_retry:
                            barrier.wait(timeout=3)
                        return json.dumps({"strategy_prompt": worker_rush_policy(3 if duplicate_retry else 2)})

                if attempts == 1:
                    with self.assertRaisesRegex(RuntimeError, "duplicates"):
                        initialize_population(config, policy_backend=Backend(), candidates_dir=root,
                                              timing_logger=LLMCallLogger(root.parent / "llm_logs", timing_path=root.parent / "timing.jsonl"))
                else:
                    population = initialize_population(config, policy_backend=Backend(), candidates_dir=root,
                                              timing_logger=LLMCallLogger(root.parent / "llm_logs", timing_path=root.parent / "timing.jsonl"))
                    self.assertEqual([item.strategy_prompt for item in population[1:]],
                                     [worker_rush_policy(2), worker_rush_policy(3)])
                summaries = [json.loads(path.read_text()) for path in root.glob("*/initialization/policy_generation/result.json")]
                self.assertEqual(sorted(item["final_attempt"] for item in summaries), [1, attempts])
                self.assertEqual(len(requests), 2 if attempts == 1 else 3)
                if attempts == 2:
                    self.assertEqual(slots[-1], 1)
                raw = list(root.glob("*/initialization/policy_generation/attempts/*/response_raw.txt"))
                self.assertEqual(len(raw), len(requests))
                rejected = [json.loads(path.read_text()) for path in root.glob("*/initialization/policy_generation/attempts/attempt_001/result.json")]
                self.assertEqual(sum(not item["selected"] for item in rejected), 1)
                self.assertTrue(all(item["status"] == "success" for item in rejected))
                decisions = [item["population_decision"] for item in rejected if "population_decision" in item]
                self.assertEqual(len(decisions), 1)
                self.assertEqual(decisions[0]["status"], "rejected_duplicate")
                self.assertTrue(decisions[0]["duplicate_of_candidate_id"])
                events = [json.loads(line) for line in (root.parent / "timing.jsonl").read_text().splitlines()]
                self.assertTrue(all(event["status"] == "success" for event in events))
                for path in root.glob("*/initialization/policy_generation/attempts/*/result.json"):
                    result = json.loads(path.read_text())
                    timing = json.loads(path.with_name("timing.json").read_text())
                    self.assertEqual(result["status"], timing["status"])


if __name__ == "__main__":
    unittest.main()
