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
from generation.agent_template import (
    JavaTemplatePaths,
    STRATEGY_END_MARKER,
    STRATEGY_START_MARKER,
    fixed_scaffold_equivalent,
    load_java_template,
)


VALID_SOURCE = load_java_template(JavaTemplatePaths())


def with_strategy(source: str, body: str) -> str:
    start = source.index(STRATEGY_START_MARKER) + len(STRATEGY_START_MARKER)
    end = source.index(STRATEGY_END_MARKER)
    return source[:start] + f"\n{body}\n    " + source[end:]


class Phase3ValidationTests(unittest.TestCase):
    def test_valid_source_accepts_arbitrary_internal_structure(self):
        source = with_strategy(
            VALID_SOURCE,
            "    private void differentlyNamedInternalMethod() {}",
        )
        result = validate_generated_java_source(source, "CandidateAgent")
        self.assertTrue(result.ok)
        self.assertIn("runtime_contract", result.passed_checks)
        self.assertIn("fixed_scaffold", result.passed_checks)
        self.assertEqual(result.failed_checks, ())
        self.assertEqual(result.blocked_checks, ())

    def test_fixed_scaffold_allows_only_whitespace_comments_and_strategy_changes(self):
        strategy_change = with_strategy(VALID_SOURCE, "    private void changedStrategy() {}")
        comment_change = VALID_SOURCE.replace(
            "// Stable Agent operation API: strategy code should issue actions through these helpers.",
            "// The same fixed helpers, with different prose.",
        )
        self.assertTrue(fixed_scaffold_equivalent(strategy_change, VALID_SOURCE))
        self.assertTrue(fixed_scaffold_equivalent(comment_change, VALID_SOURCE))
        self.assertFalse(
            fixed_scaffold_equivalent(
                VALID_SOURCE.replace("return true;", "return false;", 1),
                VALID_SOURCE,
            )
        )

    def test_modified_fixed_helper_is_a_structured_validation_failure(self):
        source = VALID_SOURCE.replace("move(unit, x, y);", "idle(unit);")
        result = validate_generated_java_source(source, "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("fixed_scaffold", {item["check"] for item in result.failed_checks})

    def test_strategy_contract_rejects_cross_method_game_time_reference(self):
        source = with_strategy(
            VALID_SOURCE,
            """    private void decide(AgentContext context) {
        int gameTime = context.gs.getTime();
        manageWorkers(context);
    }
    private void manageWorkers(AgentContext context) {
        if (gameTime >= 250) { commandIdle(null); }
    }""",
        )
        result = validate_generated_java_source(source, "CandidateAgent")
        self.assertFalse(result.ok)
        reason = next(
            item["reason"] for item in result.failed_checks
            if item["check"] == "strategy_contract"
        )
        self.assertIn("manageWorkers uses gameTime", reason)

    def test_strategy_contract_rejects_context_without_parameter_and_unavailable_lookup(self):
        source = with_strategy(
            VALID_SOURCE,
            """    private int[] findBuildLocation(Unit base) {
        PhysicalGameState pgs = context.gs.getPhysicalGameState();
        return pgs.getUnitAt(base.getX(), base.getY()) == null ? new int[]{0, 0} : null;
    }""",
        )
        result = validate_generated_java_source(source, "CandidateAgent")
        self.assertFalse(result.ok)
        reason = next(
            item["reason"] for item in result.failed_checks
            if item["check"] == "strategy_contract"
        )
        self.assertIn("does not declare AgentContext context", reason)
        self.assertIn("getUnitAt is not an available", reason)

    def test_strategy_contract_rejects_direct_unbounded_map_reads(self):
        source = with_strategy(
            VALID_SOURCE,
            """    private void decide(AgentContext context) {
        if (context.gs.free(-1, 0)) { commandIdle(null); }
        PhysicalGameState physical = context.gs.getPhysicalGameState();
        if (physical.getTerrain(99, 99) == PhysicalGameState.TERRAIN_NONE) { commandIdle(null); }
    }""",
        )
        result = validate_generated_java_source(source, "CandidateAgent")
        self.assertFalse(result.ok)
        reason = next(
            item["reason"] for item in result.failed_checks
            if item["check"] == "strategy_contract"
        )
        self.assertIn("isFreeCell(context, x, y)", reason)
        self.assertIn("GameState.free directly", reason)
        self.assertIn("PhysicalGameState.getTerrain directly", reason)

    def test_strategy_contract_rejects_nested_pairs_declared_as_one_dimensional(self):
        source = with_strategy(
            VALID_SOURCE,
            """    private int[] direction() {
        int[] directions = {{-1, 0}, {1, 0}};
        for (int[] direction : directions) { return direction; }
        return null;
    }""",
        )
        result = validate_generated_java_source(source, "CandidateAgent")
        self.assertFalse(result.ok)
        reason = next(
            item["reason"] for item in result.failed_checks
            if item["check"] == "strategy_contract"
        )
        self.assertIn("int[][]", reason)

    def test_strategy_contract_accepts_explicit_scope_and_two_dimensional_pairs(self):
        source = with_strategy(
            VALID_SOURCE,
            """    private void decide(AgentContext context) {
        int gameTime = context.gs.getTime();
        manageWorkers(context, gameTime);
    }
    private void manageWorkers(AgentContext context, int gameTime) {
        int[][] directions = new int[][]{{-1, 0}, {1, 0}};
        for (int[] direction : directions) {
            if (gameTime >= 250 && isFreeCell(context, direction[0], direction[1])) {
                return;
            }
        }
    }""",
        )
        result = validate_generated_java_source(source, "CandidateAgent")
        self.assertTrue(result.ok, result.failed_checks)

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
        start = VALID_SOURCE.index("    @Override\n    public PlayerAction getAction")
        end = VALID_SOURCE.index("\n    // EAGLE_AGENT_STRATEGY_START", start)
        source = VALID_SOURCE[:start] + VALID_SOURCE[end:]
        result = validate_assembled_java(source, "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("callable_methods", {item["check"] for item in result.failed_checks})

    def test_forbidden_process_behavior_is_rejected(self):
        result = validate_assembled_java(
            with_strategy(
                VALID_SOURCE,
                "    private void differentlyNamedInternalMethod() { new ProcessBuilder(); }",
            ),
            "CandidateAgent",
        )
        self.assertFalse(result.ok)
        self.assertIn("forbidden_behaviors", {item["check"] for item in result.failed_checks})

    def test_unavailable_dependency_is_rejected(self):
        source = VALID_SOURCE.replace(
            "import java.util.ArrayList;",
            "import com.example.missing.Dependency;",
        )
        result = validate_assembled_java(source, "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertIn("unavailable_dependencies", result.failed_checks[0]["reason"])

    def test_forbidden_file_network_and_reflection_behaviors_are_rejected(self):
        for snippet in ('new File("x");', 'new URL("http://x");', 'setAccessible(true);'):
            with self.subTest(snippet=snippet):
                source = with_strategy(
                    VALID_SOURCE,
                    f"    private void differentlyNamedInternalMethod() {{ {snippet} }}",
                )
                result = validate_assembled_java(source, "CandidateAgent")
                self.assertFalse(result.ok)
                self.assertIn("forbidden_behaviors", {item["check"] for item in result.failed_checks})
    def test_generation_failure_blocks_validation_checks(self):
        result = validate_assembled_java("", "CandidateAgent")
        self.assertFalse(result.ok)
        self.assertEqual(len(result.blocked_checks), 9)
        self.assertEqual(result.failed_checks, ())

    def test_validation_artifact_is_persisted_on_failure(self):
        class InvalidBackend:
            def generate(self, candidate, class_name):
                return VALID_SOURCE.replace("ai.generated", "ai.invalid", 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ExperimentConfig.from_mapping({})
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
            timing = json.loads((root / "candidates" / "invalid-package" / "timing.json").read_text(encoding="utf-8"))
            compilation = json.loads((root / "candidates" / "invalid-package" / "compilation" / "compilation_result.json").read_text(encoding="utf-8"))
            integration = json.loads((root / "candidates" / "invalid-package" / "integration" / "integration_result.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "failed")
        self.assertIn("package", {item["check"] for item in payload["failed_checks"]})
        self.assertIn("passed_checks", payload)
        self.assertIn("blocked_checks", payload)
        self.assertIsNotNone(payload["timing"])
        self.assertEqual(compilation["status"], "blocked")
        self.assertEqual(compilation["failure_stage"], "validation")
        self.assertEqual(integration["status"], "blocked")
        self.assertEqual(integration["failure_stage"], "validation")
        self.assertEqual(timing["validation"]["status"], "failed")
        self.assertGreaterEqual(timing["validation_duration_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
