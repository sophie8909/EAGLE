from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.code_reflection import CodeReflectionMutation
from eagle.config import ExperimentConfig
from eagle.evaluation import decode_validate_compile_candidate
from eagle.reflection_context import CandidateReflectionSummary, ReflectionContext


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARENT_JAVA = (
    PROJECT_ROOT / "eagle" / "java_seeds" / "worker_rush" / "CandidateAgent.java"
).read_text(encoding="utf-8")


class ScriptedJavaBackend:
    operation = "generation"
    model = "test-model"

    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = iter(responses)
        self.requests: list[str] = []
        self.request_kinds: list[str] = []

    def prepare_request(self, request: str) -> str:
        return request

    def set_generation_attempt_context(self, attempt: int, attempt_id: str) -> None:
        pass

    def set_generation_request_kind(self, request_kind: str) -> None:
        self.request_kinds.append(request_kind)

    def generate_from_request(
        self,
        candidate: Candidate,
        class_name: str,
        request: str,
    ) -> str:
        self.requests.append(request)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def config() -> ExperimentConfig:
    return ExperimentConfig.from_mapping({
        "strategy_reflection_probability": 0.0,
        "prompt_reflection_probability": 0.0,
        "code_reflection_probability": 1.0,
        "mutation_max_attempts": 2,
        "generation_max_attempts": 2,
    })


def context() -> ReflectionContext:
    return ReflectionContext(candidate=CandidateReflectionSummary(
        candidate_id="parent",
        strategy_prompt="Continuously produce Workers and attack the enemy Base.",
        code_generation_prompt="unused parent prompt",
        generated_code=PARENT_JAVA,
        status="evaluated",
    ))


class CodeReflectionTests(unittest.TestCase):
    def test_direct_code_reflection_changes_java_and_preserves_both_prompts(self) -> None:
        revised = PARENT_JAVA.replace(
            "// EAGLE_AGENT_STRATEGY_START",
            "// EAGLE_AGENT_STRATEGY_START\n        // direct code reflection",
            1,
        )
        backend = ScriptedJavaBackend((revised,))
        candidate = Candidate(
            id="child",
            generation=1,
            strategy_prompt="Continuously produce Workers and attack the enemy Base.",
            generation_prompt="canonical reusable prompt",
            inherited_java=PARENT_JAVA,
            java_parent_id="parent",
            operator="copy",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = CodeReflectionMutation(
                config(), backend=backend, artifact_root=root
            ).mutate(candidate, context(), artifact_dir=root / candidate.id)

            self.assertEqual(child.strategy_prompt, candidate.strategy_prompt)
            self.assertEqual(child.generation_prompt, candidate.generation_prompt)
            self.assertEqual(child.inherited_java, candidate.inherited_java)
            self.assertEqual(child.generated_java, revised.strip())
            self.assertEqual(child.mutation_type, "code")
            self.assertEqual(backend.request_kinds, ["code_reflection"])
            request = backend.requests[0]
            self.assertIn("Directly revise", request)
            self.assertIn(candidate.strategy_prompt, request)
            self.assertIn(PARENT_JAVA, request)
            self.assertNotIn(candidate.generation_prompt, request)
            mutation_dir = root / candidate.id / "mutation" / "code_reflection"
            self.assertEqual(
                (mutation_dir / "reflected_candidate.java").read_text(encoding="utf-8"),
                revised.strip(),
            )
            metadata = json.loads(
                (mutation_dir / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["applied"])
            self.assertTrue(metadata["java_changed"])

    def test_failed_response_preserves_parent_java_for_direct_evaluation(self) -> None:
        backend = ScriptedJavaBackend(("", ""))
        candidate = Candidate(
            id="child",
            generation=1,
            strategy_prompt="Worker Rush.",
            generation_prompt="prompt gene",
            inherited_java=PARENT_JAVA,
            java_parent_id="parent",
        )

        child = CodeReflectionMutation(config(), backend=backend).mutate(
            candidate,
            context(),
        )

        self.assertEqual(child.generated_java, PARENT_JAVA)
        self.assertFalse(child.metadata["mutation"]["applied"])
        self.assertEqual(child.operator, candidate.operator)
        self.assertEqual(len(backend.requests), 2)
        self.assertIn("could not be used", backend.requests[1])

    def test_direct_code_output_skips_final_generator(self) -> None:
        backend = ScriptedJavaBackend((RuntimeError("final Generator must not run"),))
        candidate = Candidate(
            id="direct-code-child",
            generation=1,
            strategy_prompt="Worker Rush.",
            generation_prompt="prompt gene",
            inherited_java=PARENT_JAVA,
            java_parent_id="parent",
            generated_java=PARENT_JAVA,
            mutation_type="code",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = decode_validate_compile_candidate(
                candidate,
                config=config(),
                backend=backend,
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=True,
                candidate_artifact_dir=root / "candidate",
            )

        self.assertEqual(backend.requests, [])
        self.assertEqual(result.selected_attempt, 1)
        self.assertEqual(result.attempts[0].request_kind, "code_reflection_output")
        self.assertTrue(result.compile_result and result.compile_result.ok)


if __name__ == "__main__":
    unittest.main()
