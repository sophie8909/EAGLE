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

    def __init__(self, responses: tuple[str, ...], events: list[str] | None = None) -> None:
        self.responses = iter(responses)
        self.requests: list[str] = []
        self.request_kinds: list[str] = []
        self.events = events

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
        if self.events is not None:
            self.events.append("revision")
        self.requests.append(request)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


class ScriptedReflectionBackend:
    operation = "reflection"
    model = "test-model"

    def __init__(self, responses: tuple[str, ...], events: list[str] | None = None) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []
        self.events = events

    def generate(self, prompt: str) -> str:
        if self.events is not None:
            self.events.append("reflection")
        self.prompts.append(prompt)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def reflection_response(*, requires_revision: bool = True) -> str:
    return json.dumps({
        "assessment": (
            "code_requires_revision"
            if requires_revision
            else "code_faithfully_implements_strategy"
        ),
        "diagnosis": ([{
            "strategy_requirement": "Workers must attack the enemy Base.",
            "observed_java_behavior": "The editable strategy does not record this test marker.",
            "required_code_change": "Add the minimal Worker attack behavior in the editable region.",
        }] if requires_revision else []),
        "behaviors_to_preserve": ["Preserve legal Worker production."],
    })


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
        events: list[str] = []
        backend = ScriptedJavaBackend((revised,), events)
        reflector = ScriptedReflectionBackend((reflection_response(),), events)
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
                config(),
                backend=backend,
                reflection_backend=reflector,
                artifact_root=root,
            ).mutate(candidate, context(), artifact_dir=root / candidate.id)

            self.assertEqual(child.strategy_prompt, candidate.strategy_prompt)
            self.assertEqual(child.generation_prompt, candidate.generation_prompt)
            self.assertEqual(child.inherited_java, candidate.inherited_java)
            self.assertEqual(child.generated_java, revised.strip())
            self.assertEqual(child.mutation_type, "code")
            self.assertEqual(events, ["reflection", "revision"])
            self.assertEqual(backend.request_kinds, ["code_reflection"])
            self.assertEqual(len(reflector.prompts), 1)
            self.assertIn("diagnosis stage", reflector.prompts[0])
            request = backend.requests[0]
            self.assertIn("Java revision stage", request)
            self.assertIn("required_code_change", request)
            self.assertIn("Add the minimal Worker attack behavior", request)
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
            self.assertEqual(metadata["reflection_status"], "success")
            self.assertEqual(metadata["revision_status"], "success")
            conclusion = json.loads(
                (mutation_dir / "reflection_conclusion.json").read_text(encoding="utf-8")
            )
            self.assertEqual(conclusion["assessment"], "code_requires_revision")
            self.assertTrue((mutation_dir / "revision_request.txt").exists())
            self.assertTrue((mutation_dir / "revision_response_raw.txt").exists())

    def test_failed_revision_preserves_parent_java_for_direct_evaluation(self) -> None:
        backend = ScriptedJavaBackend(("", ""))
        reflector = ScriptedReflectionBackend((reflection_response(),))
        candidate = Candidate(
            id="child",
            generation=1,
            strategy_prompt="Worker Rush.",
            generation_prompt="prompt gene",
            inherited_java=PARENT_JAVA,
            java_parent_id="parent",
        )

        child = CodeReflectionMutation(
            config(), backend=backend, reflection_backend=reflector
        ).mutate(
            candidate,
            context(),
        )

        self.assertEqual(child.generated_java, PARENT_JAVA)
        self.assertFalse(child.metadata["mutation"]["applied"])
        self.assertEqual(child.operator, candidate.operator)
        self.assertEqual(len(backend.requests), 2)
        self.assertIn("could not be used", backend.requests[1])

    def test_failed_diagnosis_never_calls_java_revision(self) -> None:
        backend = ScriptedJavaBackend((RuntimeError("revision must not run"),))
        reflector = ScriptedReflectionBackend(("not json", "still not json"))
        candidate = Candidate(
            id="child",
            generation=1,
            strategy_prompt="Worker Rush.",
            generation_prompt="prompt gene",
            inherited_java=PARENT_JAVA,
            java_parent_id="parent",
        )

        child = CodeReflectionMutation(
            config(), backend=backend, reflection_backend=reflector
        ).mutate(candidate, context())

        self.assertEqual(child.generated_java, PARENT_JAVA)
        self.assertFalse(child.metadata["mutation"]["applied"])
        self.assertEqual(child.metadata["mutation"]["reflection_status"], "failed")
        self.assertEqual(child.metadata["mutation"]["revision_status"], "not_run")
        self.assertEqual(backend.requests, [])

    def test_code_diagnosis_normalizes_structured_preservation_descriptions(self) -> None:
        backend = ScriptedJavaBackend((PARENT_JAVA,))
        reflector = ScriptedReflectionBackend((json.dumps({
            "assessment": "code_faithfully_implements_strategy",
            "diagnosis": [],
            "behaviors_to_preserve": [{
                "description": "Preserve continuous legal Worker production.",
                "evidence": [{"method": "trainWorkers"}],
            }],
        }),))
        candidate = Candidate(
            id="child",
            generation=1,
            strategy_prompt="Worker Rush.",
            generation_prompt="prompt gene",
            inherited_java=PARENT_JAVA,
            java_parent_id="parent",
        )

        child = CodeReflectionMutation(
            config(), backend=backend, reflection_backend=reflector
        ).mutate(candidate, context())

        conclusion = child.metadata["mutation"]["reflection_conclusion"]
        self.assertEqual(
            conclusion["behaviors_to_preserve"],
            ["Preserve continuous legal Worker production."],
        )
        self.assertIn(
            "Preserve continuous legal Worker production.",
            backend.requests[0],
        )

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
