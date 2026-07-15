import json
import tempfile
import unittest
from pathlib import Path

from eagle.artifacts import write_candidate_artifacts
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_candidate
from generation.java_agent_generator import (
    validate_assembled_java,
    validate_generated_java_source,
)


VALID_SOURCE = """\
package ai.generated;
import ai.abstraction.AbstractionLayerAI;
import ai.abstraction.pathfinding.AStarPathFinding;
import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.Collections;
import java.util.List;
import rts.GameState;
import rts.PlayerAction;
import rts.units.UnitTypeTable;

public final class CandidateAgent extends AbstractionLayerAI {
    public CandidateAgent(UnitTypeTable utt) {
        this(utt, new AStarPathFinding());
    }
    public CandidateAgent(UnitTypeTable utt, AStarPathFinding pathFinding) {
        super(pathFinding);
    }
    @Override public void reset() {
        super.reset();
    }
    @Override public AI clone() {
        return new CandidateAgent(new UnitTypeTable());
    }
    @Override public PlayerAction getAction(int player, GameState gs) {
        return new PlayerAction();
    }
    @Override public List<ParameterSpecification> getParameters() {
        return Collections.emptyList();
    }
    private void differentlyNamedInternalMethod() {}
}
"""


class Phase3ValidationTests(unittest.TestCase):
    def test_valid_source_accepts_arbitrary_internal_structure(self):
        result = validate_generated_java_source(VALID_SOURCE, "CandidateAgent")
        self.assertTrue(result.ok)
        self.assertIn("runtime_contract", result.passed_checks)
        self.assertEqual(result.failed_checks, ())
        self.assertEqual(result.blocked_checks, ())

    def test_invalid_package_is_a_structured_validation_failure(self):
        result = validate_assembled_java(VALID_SOURCE.replace("ai.generated", "ai.invalid", 1), "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertEqual(result.failed_checks[0]["check"], "package")
        self.assertEqual(result.blocked_checks, ())
        self.assertTrue(result.failure_reason)

    def test_invalid_class_is_a_structured_validation_failure(self):
        result = validate_assembled_java(VALID_SOURCE.replace("CandidateAgent", "WrongAgent"), "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("public_class", {item["check"] for item in result.failed_checks})

    def test_invalid_constructor_is_a_structured_validation_failure(self):
        source = VALID_SOURCE.replace(
            "public CandidateAgent(UnitTypeTable utt, AStarPathFinding pathFinding)",
            "private CandidateAgent(UnitTypeTable utt, AStarPathFinding pathFinding)",
        )
        result = validate_assembled_java(source, "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("constructors", {item["check"] for item in result.failed_checks})

    def test_invalid_superclass_is_a_structured_validation_failure(self):
        result = validate_assembled_java(VALID_SOURCE.replace("extends AbstractionLayerAI", "extends Object"), "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("superclass", {item["check"] for item in result.failed_checks})

    def test_missing_get_action_is_a_structured_validation_failure(self):
        source = VALID_SOURCE.replace(
            "    @Override public PlayerAction getAction(int player, GameState gs) {\n        return new PlayerAction();\n    }\n",
            "",
        )
        result = validate_assembled_java(source, "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("callable_methods", {item["check"] for item in result.failed_checks})

    def test_forbidden_process_behavior_is_rejected(self):
        result = validate_assembled_java(VALID_SOURCE.replace(
            "private void differentlyNamedInternalMethod() {}",
            "private void differentlyNamedInternalMethod() { new ProcessBuilder(); }",
        ), "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("forbidden_behaviors", {item["check"] for item in result.failed_checks})

    def test_generation_failure_blocks_validation_checks(self):
        result = validate_assembled_java("", "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertEqual(len(result.blocked_checks), 7)
        self.assertEqual(result.failed_checks, ())

    def test_validation_artifact_is_persisted_on_failure(self):
        class InvalidBackend:
            def generate(self, candidate, class_name):
                return VALID_SOURCE.replace("ai.generated", "ai.invalid", 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            evaluation = evaluate_candidate(
                Candidate(id="invalid-package"),
                config=config,
                backend=InvalidBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(root / "candidates", evaluation)
            payload = json.loads(
                (root / "candidates" / "invalid-package" / "validation" / "validation_result.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("package", {item["check"] for item in payload["failed_checks"]})
        self.assertIn("passed_checks", payload)
        self.assertIn("blocked_checks", payload)


if __name__ == "__main__":
    unittest.main()
