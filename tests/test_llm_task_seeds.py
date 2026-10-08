"""Request seeds must follow EA task identity, never scheduling or shared state."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.evaluation.determinism import derive_seed
from eagle.generation.backend import OpenAICompatibleGenerationBackend
from eagle.llm import generate_seeded
from eagle.operators.prompt import PromptRewriteStage
from eagle.operators.reflection import OpenAICompatibleReflectionBackend, ReflectionStage
from eagle.operators.strategy import StrategyReflectionPipeline


class LLMTaskSeedTests(unittest.TestCase):
    def setUp(self):
        self.candidate = Candidate(id="candidate-a", generation=2, strategy_prompt="policy", generation_prompt="rules")

    def capture_generation(self, root_seed=7, candidate=None, attempt=1, kind="initial_decode"):
        backend = OpenAICompatibleGenerationBackend("http://localhost:8080", "test", seed=root_seed, temperature=0.7)
        backend.set_generation_attempt_context(attempt, f"attempt-{attempt}")
        backend.set_generation_request_kind(kind)
        with patch("eagle.generation.backend.urllib.request.urlopen") as transport, patch(
            "eagle.generation.backend.read_chat_completion_content", return_value="Java"
        ):
            backend.generate_from_request(candidate or self.candidate, "CandidateAgent", "request")
        payload = json.loads(transport.call_args.args[0].data)
        self.assertEqual(payload["temperature"], 0.7)
        self.assertEqual(backend.seed, root_seed)
        return payload["seed"]

    def test_generation_identity_and_root_control_payload(self):
        base = self.capture_generation()
        self.assertEqual(base, self.capture_generation())
        variants = [
            self.capture_generation(root_seed=8),
            self.capture_generation(candidate=replace(self.candidate, id="candidate-b")),
            self.capture_generation(candidate=replace(self.candidate, generation=3)),
            self.capture_generation(attempt=2),
            self.capture_generation(kind="compile_repair"),
            self.capture_generation(kind="code_reflection"),
        ]
        self.assertEqual(len(set([base, *variants])), 7)
        self.assertTrue(all(0 <= seed <= 0x7FFF_FFFF for seed in [base, *variants]))

    def test_reflection_direct_calls_derive_seed_and_explicit_tasks_do_not_mutate_root(self):
        backend = OpenAICompatibleReflectionBackend("http://localhost:8080", "test", seed=7, temperature=0.6)
        with patch("eagle.operators.reflection.urllib.request.urlopen") as transport, patch(
            "eagle.operators.reflection.read_chat_completion_content", return_value="{}"
        ):
            backend.generate("request")
            backend.generate("request")
            backend.generate("other request")
            generate_seeded(backend, "request", 123)
        payloads = [json.loads(call.args[0].data) for call in transport.call_args_list]
        self.assertEqual(payloads[0]["seed"], payloads[1]["seed"])
        self.assertNotEqual(payloads[0]["seed"], payloads[2]["seed"])
        self.assertEqual(payloads[3]["seed"], 123)
        self.assertEqual(backend.seed, 7)
        self.assertTrue(all(payload["temperature"] == 0.6 for payload in payloads))

    def test_shared_reflection_backend_is_independent_of_thread_count(self):
        backend = OpenAICompatibleReflectionBackend("http://localhost:8080", "test", seed=7)
        def run(index):
            seed = derive_seed(7, "llm", "reflection", index) & 0x7FFF_FFFF
            return generate_seeded(backend, str(index), seed)
        class Response:
            def __init__(self, request):
                self.payload = json.loads(request.data)
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
        with patch("eagle.operators.reflection.urllib.request.urlopen", side_effect=lambda request, **_: Response(request)), patch(
            "eagle.operators.reflection.read_chat_completion_content", side_effect=lambda response: response.payload["seed"]
        ), patch.dict("os.environ", {"EAGLE_LLM_PROGRESS": "off"}):
            with ThreadPoolExecutor(max_workers=1) as pool:
                serial = list(pool.map(run, range(12)))
            with ThreadPoolExecutor(max_workers=4) as pool:
                parallel = list(pool.map(run, range(12)))
            self.assertEqual(serial, parallel)
            self.assertEqual(len(set(serial)), 12)
        self.assertEqual(backend.seed, 7)

    def test_reflection_rewrite_and_strategy_attempts_have_distinct_seeds(self):
        backend = OpenAICompatibleReflectionBackend("http://localhost:8080", "test", seed=7)
        seeds = []
        def response(prompt, seed):
            seeds.append(seed)
            return "{}"
        with patch.object(backend, "generate_seeded", side_effect=response):
            reflector = ReflectionStage(backend, max_attempts=2)
            reflector.run(reflection_type="prompt", candidate=self.candidate, request="request")
            rewrite = PromptRewriteStage(backend, max_attempts=2)
            rewrite.run(rewrite_type="strategy_prompt_rewrite", candidate=self.candidate, request="request")
            pipeline = StrategyReflectionPipeline(backend, selection_seed=7, max_attempts=2)
            def invalid(raw):
                raise ValueError("invalid")
            with self.assertRaises(RuntimeError):
                pipeline._call_role("coach", "request", self.candidate, None, validator=invalid)
            first = seeds.copy()
            seeds.clear()
            reflector.run(reflection_type="prompt", candidate=self.candidate, request="request")
            rewrite.run(rewrite_type="strategy_prompt_rewrite", candidate=self.candidate, request="request")
            with self.assertRaises(RuntimeError):
                pipeline._call_role("coach", "request", self.candidate, None, validator=invalid)
        self.assertEqual(first, seeds)
        self.assertEqual(len(set(seeds)), 6)

    def test_legacy_deterministic_fake_backend_remains_supported(self):
        class Fake:
            def generate(self, prompt):
                return prompt
        self.assertEqual(generate_seeded(Fake(), "request", 7), "request")


if __name__ == "__main__":
    unittest.main()
