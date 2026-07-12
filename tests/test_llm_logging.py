import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.llm_logging import LLMCallLogger
from evaluation.strategy_alignment import evaluate_strategy_alignment
from generation.backend import OpenAICompatibleGenerationBackend


class FakeResponse:
    def __init__(self, payload: dict):
        self.data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.data


class LLMLoggingTests(unittest.TestCase):
    def test_logger_writes_one_independent_unicode_json_per_call(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = LLMCallLogger(Path(temp))
            first = logger.write(
                stage="generation",
                input_text="???",
                response_text="???",
                status="success",
                backend="test",
                model="model",
                candidate_id="candidate-a",
                generation=2,
                module_name="all_behaviors",
            )
            second = logger.write(
                stage="alignment",
                input_text="???",
                response_text="???",
                status="success",
                backend="test",
                model="model",
            )
            self.assertNotEqual(first, second)
            self.assertEqual(len(list(Path(temp).glob("*.json"))), 2)
            payload = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(payload["input"], "???")
            self.assertEqual(payload["response"], "???")
            self.assertEqual(payload["candidate_id"], "candidate-a")
            self.assertEqual(payload["module_name"], "all_behaviors")
            self.assertEqual(payload["generation"], 2)

    def test_generation_http_call_logs_exact_prompt_and_response(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = LLMCallLogger(Path(temp))
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080", "test-model", max_retries=0, logger=logger
            )
            candidate = Candidate(id="candidate-a", generation=3)
            response = "private Decision decide(AgentContext context) { return new Decision(); }"
            body = {"choices": [{"message": {"content": response}}]}
            with patch("generation.backend.urllib.request.urlopen", return_value=FakeResponse(body)):
                self.assertEqual(
                    backend.generate(candidate, "GeneratedAgent_candidate_a"),
                    response,
                )
            files = list(Path(temp).glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "generation")
            self.assertEqual(payload["response"], response)
            self.assertEqual(payload["module_name"], "all_behaviors")
            self.assertEqual(payload["candidate_id"], "candidate-a")
            self.assertIn("private Decision decide(AgentContext context)", payload["input"])

    def test_generation_retry_writes_one_log_per_http_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = LLMCallLogger(Path(temp))
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080", "test-model", max_retries=1, logger=logger
            )
            candidate = Candidate(id="candidate-retry", generation=1)
            response = "private Decision decide(AgentContext context) { return new Decision(); }"
            body = {"choices": [{"message": {"content": response}}]}
            effects = [urllib.error.URLError("temporary"), FakeResponse(body)]
            with patch("generation.backend.urllib.request.urlopen", side_effect=effects), patch(
                "generation.backend.time.sleep"
            ):
                backend.generate(candidate, "GeneratedAgent_candidate_retry")
            payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(Path(temp).glob("*.json"))
            ]
            self.assertEqual([item["status"] for item in payloads], ["error", "success"])
            self.assertEqual([item["attempt"] for item in payloads], [1, 2])
            self.assertEqual(payloads[0]["input"], payloads[1]["input"])

    def test_alignment_http_call_logs_exact_prompt_and_response(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = LLMCallLogger(Path(temp))
            response = '{"score": 0.75, "rationale": "aligned"}'
            body = {"choices": [{"message": {"content": response}}]}
            with patch("evaluation.strategy_alignment.urllib.request.urlopen", return_value=FakeResponse(body)):
                result = evaluate_strategy_alignment(
                    strategy_prompt="attack",
                    generated_java_code="class Agent {}",
                    backend="openai",
                    model="test-model",
                    logger=logger,
                    candidate_id="candidate-b",
                    generation=4,
                )
            self.assertEqual(result.score, 0.75)
            files = list(Path(temp).glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "alignment")
            self.assertEqual(payload["response"], response)
            self.assertEqual(payload["candidate_id"], "candidate-b")
            self.assertIn("Strategy prompt:\nattack", payload["input"])


if __name__ == "__main__":
    unittest.main()
