import json
import unittest

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.compiler import normalize_compiler_paths
from eagle.evaluation.decoding import _compile_repair_request
from eagle.generation.backend import MockGenerationBackend


class CompilerPromptReproducibilityTests(unittest.TestCase):
    def test_absolute_java_paths_are_normalized_without_losing_lines_or_messages(self):
        linux = "/tmp/run-a/source folder/CandidateAgent.java:42: error: unknown symbol"
        windows = r"D:\runs\run-b\source folder\CandidateAgent.java:42: error: unknown symbol"
        expected = "CandidateAgent.java:42: error: unknown symbol"
        self.assertEqual(normalize_compiler_paths(linux), expected)
        self.assertEqual(normalize_compiler_paths(windows), expected)
        self.assertEqual(normalize_compiler_paths(json.dumps({"file": windows})), json.dumps({"file": expected}))

    def test_compile_repair_requests_are_identical_in_different_run_directories(self):
        config = ExperimentConfig.from_mapping({})
        backend = MockGenerationBackend(config.agent_template_path)
        candidate = Candidate(id="candidate", strategy_prompt="policy")
        requests = []
        for root in ("/tmp/run-a", "/tmp/run-b"):
            requests.append(_compile_repair_request(candidate, config=config, backend=backend,
                previous_source="source", evidence={"compilation": {
                    "diagnostics": [{"file": root + "/CandidateAgent.java", "line": 42}],
                    "stderr": root + "/CandidateAgent.java:42: error: unknown symbol",
                }}))
        self.assertEqual(*requests)
        self.assertIn("CandidateAgent.java:42", requests[0])


if __name__ == "__main__":
    unittest.main()
