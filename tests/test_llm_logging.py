import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.llm_errors import LLMServerError
from eagle.llm_logging import LLMCallLogger
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


class FakeStreamResponse:
    def __init__(self, chunks: list[str]):
        self.lines = [
            f'data: {json.dumps({"choices": [{"delta": {"content": chunk}}]})}\n\n'.encode()
            for chunk in chunks
        ]
        self.lines.append(b"data: [DONE]\n\n")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def __iter__(self):
        return iter(self.lines)


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
            with patch("generation.backend.urllib.request.urlopen", return_value=FakeResponse(body)) as request:
                self.assertEqual(
                    backend.generate(candidate, "GeneratedAgent_candidate_a"),
                    response,
                )
            request_payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
            self.assertEqual(request_payload["chat_template_kwargs"], {"enable_thinking": False})
            files = list(Path(temp).glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "generation")
            self.assertEqual(payload["response"], response)
            self.assertEqual(payload["module_name"], "complete_java_agent")
            self.assertEqual(payload["candidate_id"], "candidate-a")
            self.assertIn("private void decide(AgentContext context)", payload["input"])

    def test_generation_connection_error_fails_immediately(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = LLMCallLogger(Path(temp))
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080", "test-model", max_retries=1, logger=logger
            )
            candidate = Candidate(id="candidate-retry", generation=1)
            with patch(
                "generation.backend.urllib.request.urlopen",
                side_effect=urllib.error.URLError("temporary"),
            ) as request:
                with self.assertRaisesRegex(LLMServerError, "llm server error"):
                    backend.generate(candidate, "GeneratedAgent_candidate_retry")
            payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(Path(temp).glob("*.json"))
            ]
            self.assertEqual([item["status"] for item in payloads], ["error"])
            self.assertEqual([item["attempt"] for item in payloads], [1])
            self.assertEqual(request.call_count, 1)

    def test_generation_accumulates_streaming_content(self):
        backend = OpenAICompatibleGenerationBackend(
            "http://localhost:8080",
            "test-model",
            max_retries=0,
        )
        candidate = Candidate(id="candidate-stream", generation=0)

        with patch(
            "generation.backend.urllib.request.urlopen",
            return_value=FakeStreamResponse(["package ai.generated;\n", "public class CandidateAgent {}"]),
        ) as request:
            content = backend.generate(candidate, "CandidateAgent")

        self.assertEqual(
            content,
            "package ai.generated;\npublic class CandidateAgent {}",
        )
        request_payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(request_payload["stream"])

if __name__ == "__main__":
    unittest.main()
