import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.llm import LLMCallLogger, LLMServerError
from eagle.generation.backend import OpenAICompatibleGenerationBackend
from eagle.operators.reflection import OpenAICompatibleReflectionBackend


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

    def test_generation_http_call_indexes_canonical_stage_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = LLMCallLogger(root / "llm_logs")
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080", "test-model", max_retries=0, logger=logger, seed=37
            )
            candidate = Candidate(id="candidate-a", generation=3)
            backend.set_generation_attempt_context(2, "candidate-a:generation:002")
            response = "private Decision decide(AgentContext context) { return new Decision(); }"
            body = {"choices": [{"message": {"content": response}}]}
            with patch("eagle.generation.backend.urllib.request.urlopen", return_value=FakeResponse(body)) as request:
                self.assertEqual(
                    backend.generate(candidate, "GeneratedAgent_candidate_a"),
                    response,
                )
            request_payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
            self.assertEqual(request_payload["chat_template_kwargs"], {"enable_thinking": False})
            self.assertEqual(request_payload["seed"], 37)
            files = list((root / "llm_logs").glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "generation")
            self.assertIsNone(payload["input"])
            self.assertIsNone(payload["response"])
            self.assertFalse(payload["inline_evidence_retained"])
            self.assertEqual(payload["module_name"], "complete_java_agent")
            self.assertEqual(payload["metadata"]["sampling_seed"], 37)
            self.assertEqual(payload["candidate_id"], "candidate-a")
            evidence_dir = root / "candidates" / "candidate-a" / "generation" / "attempts" / "attempt_002"
            self.assertEqual(
                (evidence_dir / "response_raw.txt").read_text(encoding="utf-8"),
                response,
            )
            self.assertIn(
                "private void decide(AgentContext context)",
                (evidence_dir / "request.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                payload["artifact_refs"]["response_raw"],
                "candidates/candidate-a/generation/attempts/attempt_002/response_raw.txt",
            )

    def test_generation_connection_error_fails_immediately(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = LLMCallLogger(Path(temp))
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080", "test-model", max_retries=1, logger=logger
            )
            candidate = Candidate(id="candidate-retry", generation=1)
            with patch(
                "eagle.generation.backend.urllib.request.urlopen",
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
            self.assertTrue(payloads[0]["inline_evidence_retained"])
            self.assertEqual(request.call_count, 1)

    def test_generation_backend_indexes_explicit_code_artifacts_and_resets_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = LLMCallLogger(root / "llm_logs")
            backend = OpenAICompatibleGenerationBackend(
                "http://localhost:8080", "test-model", max_retries=0, logger=logger
            )
            candidate = Candidate(id="inspection-subject", generation=1)
            explicit_dir = root / "trials" / "code" / "trial_01" / "mutation" / "code_reflection"
            backend.set_generation_attempt_context(1, "inspection-subject:code_revision:001")
            backend.set_generation_request_kind("code_reflection")
            backend.set_request_artifact_dir(explicit_dir)
            responses = [
                FakeResponse({"choices": [{"message": {"content": "code response"}}]}),
                FakeResponse({"choices": [{"message": {"content": "generation response"}}]}),
            ]
            with patch("eagle.generation.backend.urllib.request.urlopen", side_effect=responses):
                backend.generate_from_request(candidate, "CandidateAgent", "code request")
                backend.set_generation_attempt_context(2, "inspection-subject:generation:002")
                backend.set_generation_request_kind("initial_decode")
                backend.generate_from_request(candidate, "CandidateAgent", "generation request")

            payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((root / "llm_logs").glob("*.json"))
            ]
            self.assertEqual(len(payloads), 2)
            self.assertEqual(
                payloads[0]["artifact_refs"]["response_raw"],
                "trials/code/trial_01/mutation/code_reflection/revision_attempt_001_response_raw.txt",
            )
            self.assertEqual(
                payloads[1]["artifact_refs"]["response_raw"],
                "candidates/inspection-subject/generation/attempts/attempt_002/response_raw.txt",
            )
            for payload in payloads:
                for reference in payload["artifact_refs"].values():
                    self.assertTrue((root / reference).is_file(), reference)

    def test_generation_accumulates_streaming_content(self):
        backend = OpenAICompatibleGenerationBackend(
            "http://localhost:8080",
            "test-model",
            max_retries=0,
        )
        candidate = Candidate(id="candidate-stream", generation=0)

        with patch(
            "eagle.generation.backend.urllib.request.urlopen",
            return_value=FakeStreamResponse(["package ai.generated;\n", "public class CandidateAgent {}"]),
        ) as request:
            content = backend.generate(candidate, "CandidateAgent")

        self.assertEqual(
            content,
            "package ai.generated;\npublic class CandidateAgent {}",
        )
        request_payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(request_payload["stream"])

    def test_reflection_request_contains_sampling_seed(self):
        backend = OpenAICompatibleReflectionBackend(
            "http://localhost:8080", "test-model", seed=41
        )
        response = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        with patch(
            "eagle.operators.reflection.urllib.request.urlopen",
            return_value=FakeResponse(response),
        ) as request:
            self.assertEqual(backend.generate("repeat this prompt"), '{"ok": true}')
        request_payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_payload["seed"], 41)

if __name__ == "__main__":
    unittest.main()
