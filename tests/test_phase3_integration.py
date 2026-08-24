import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.artifacts import write_candidate_artifacts
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_candidate
from evaluation.microrts_runner import (
    INTEGRATION_PROBE_SOURCE,
    INTEGRATION_CHECK_NAMES,
    IntegrationCheck,
    IntegrationResult,
    integrate_microrts_agent,
    parse_integration_checks,
)
from evaluation.compiler import compile_generated_agent
from generation.backend import MockGenerationBackend
from generation.agent_template import (
    JavaTemplatePaths,
    STRATEGY_END_MARKER,
    STRATEGY_START_MARKER,
    load_java_template,
)


def with_strategy(source: str, body: str) -> str:
    start = source.index(STRATEGY_START_MARKER) + len(STRATEGY_START_MARKER)
    end = source.index(STRATEGY_END_MARKER)
    return source[:start] + f"\n{body}\n    " + source[end:]


def failed_integration_result(failed_index: int = 4) -> IntegrationResult:
    checks = []
    for index, name in enumerate(INTEGRATION_CHECK_NAMES):
        if index < failed_index:
            checks.append(IntegrationCheck(name, "passed"))
        elif index == failed_index:
            checks.append(IntegrationCheck(name, "failed", f"{name} failed"))
        else:
            checks.append(IntegrationCheck(name, "blocked", f"{INTEGRATION_CHECK_NAMES[failed_index]} failed"))
    return IntegrationResult(
        status="failed",
        checks=tuple(checks),
        integration_pass_ratio=failed_index / len(INTEGRATION_CHECK_NAMES),
        stdout="synthetic integration failure",
        stderr="",
        returncode=1,
        started_at="2026-07-16T00:00:00+00:00",
        finished_at="2026-07-16T00:00:00.010000+00:00",
        duration_seconds=0.01,
        failure_stage="integration",
        failure_reason=checks[failed_index].reason,
    )


class Phase3IntegrationTests(unittest.TestCase):
    def test_parse_checks_preserves_order_and_blocks_downstream(self):
        checks = parse_integration_checks(
            "CHECK\tclass_loading\tpassed\t\n"
            "CHECK\tai_inheritance\tfailed\twrong superclass\n"
        )
        self.assertEqual(tuple(check.name for check in checks), INTEGRATION_CHECK_NAMES)
        self.assertEqual(
            tuple(check.status for check in checks),
            ("passed", "failed", "blocked", "blocked", "blocked", "blocked", "blocked"),
        )
        self.assertEqual(checks[1].reason, "wrong superclass")
        self.assertTrue(all(check.reason for check in checks[2:]))

    def test_mock_integration_persists_request_result_and_timing_without_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            integration_dir = Path(temp_dir) / "integration"
            result = integrate_microrts_agent(
                microrts_dir=Path("third_party/microrts"),
                classes_dir=Path(temp_dir) / "classes",
                agent_class="ai.generated.CandidateAgent",
                integration_artifacts_dir=integration_dir,
                mock=True,
            )
            request = json.loads((integration_dir / "request.txt").read_text(encoding="utf-8"))
            payload = json.loads((integration_dir / "integration_result.json").read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.integration_pass_ratio, 1.0)
        self.assertEqual(tuple(item["check"] for item in payload["ordered_checks"]), INTEGRATION_CHECK_NAMES)
        self.assertEqual(request["check_order"], list(INTEGRATION_CHECK_NAMES))
        self.assertGreaterEqual(payload["duration_seconds"], 0.0)
        self.assertEqual(payload["timing"]["duration_seconds"], payload["duration_seconds"])
        self.assertTrue(payload["started_at"].endswith("+00:00"))
        self.assertTrue(payload["finished_at"].endswith("+00:00"))
        self.assertFalse((integration_dir.parent / "matches").exists())

    def test_integration_failure_stops_matches_and_persists_metadata(self):
        failure = failed_integration_result()
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch("eagle.evaluation.integrate_microrts_agent", return_value=failure), \
             patch("eagle.evaluation.evaluate_matches") as evaluate_matches:
            root = Path(temp_dir)
            candidates_dir = root / "candidates"
            evaluation = evaluate_candidate(
                Candidate(id="integration-failure"),
                config=ExperimentConfig.from_mapping({}),
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=candidates_dir / "integration-failure" / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(candidates_dir, evaluation)
            candidate_dir = candidates_dir / "integration-failure"
            payload = json.loads(
                (candidate_dir / "integration" / "integration_result.json").read_text(encoding="utf-8")
            )
            timing = json.loads((candidate_dir / "timing.json").read_text(encoding="utf-8"))
            candidate_result = json.loads(
                (candidate_dir / "candidate.json").read_text(encoding="utf-8")
            )

        evaluate_matches.assert_not_called()
        self.assertEqual(evaluation.candidate.failure_stage, "integration")
        self.assertEqual(evaluation.result.failure_category, "MicroRTS integration failure")
        self.assertEqual(evaluation.match_results, [])
        self.assertEqual(payload["status"], "failed")
        self.assertAlmostEqual(payload["integration_pass_ratio"], 4 / 7)
        self.assertEqual(payload["timing"]["status"], "failed")
        self.assertEqual(
            [item["status"] for item in payload["ordered_checks"]],
            ["passed", "passed", "passed", "passed", "failed", "blocked", "blocked"],
        )
        self.assertEqual(payload["failure_stage"], "integration")
        self.assertEqual(candidate_result["failure_stage"], "integration")
        self.assertEqual(timing["integration"]["status"], "failed")
        self.assertEqual(timing["integration_duration_seconds"], 0.01)

    def test_successful_integration_precedes_match_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ExperimentConfig.from_mapping({})
            evaluation = evaluate_candidate(
                Candidate(id="integration-success"),
                config=config,
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "candidates" / "integration-success" / "matches",
                mock=True,
                ordinal=0,
            )

        self.assertTrue(evaluation.integration_result and evaluation.integration_result.ok)
        self.assertEqual(
            tuple(check.name for check in evaluation.integration_result.checks),
            INTEGRATION_CHECK_NAMES,
        )
        self.assertEqual(len(evaluation.match_results), config.expected_match_count)
        self.assertIsNone(evaluation.candidate.failure_stage)

    def test_probe_exercises_populated_8x8_map_both_sides_and_action_integrity(self):
        self.assertGreaterEqual(
            INTEGRATION_PROBE_SOURCE.count(
                'PhysicalGameState.load("maps/8x8/basesWorkers8x8.xml", utt)'
            ),
            2,
        )
        self.assertIn("candidatePlayerZero = (AI) one.newInstance(utt)", INTEGRATION_PROBE_SOURCE)
        self.assertIn("candidatePlayerOne = (AI) one.newInstance(utt)", INTEGRATION_PROBE_SOURCE)
        self.assertIn("candidatePlayerZero.getAction(0, playerZeroState)", INTEGRATION_PROBE_SOURCE)
        self.assertIn("candidatePlayerOne.getAction(1, playerOneState)", INTEGRATION_PROBE_SOURCE)
        self.assertIn("playerZeroAction.integrityCheck()", INTEGRATION_PROBE_SOURCE)
        self.assertIn("playerZeroState.issueSafe(playerZeroAction)", INTEGRATION_PROBE_SOURCE)
        self.assertIn("playerOneState.issueSafe(playerOneAction)", INTEGRATION_PROBE_SOURCE)
        self.assertIn("playerZeroState.cycle()", INTEGRATION_PROBE_SOURCE)
        self.assertIn("playerOneState.cycle()", INTEGRATION_PROBE_SOURCE)

    @unittest.skipUnless(shutil.which("javac"), "javac is required for the real integration probe test")
    def test_real_probe_accepts_scaffold_with_out_of_bounds_strategy_requests(self):
        source = with_strategy(
            load_java_template(JavaTemplatePaths()),
            """    private void decide(AgentContext context) {
        for (Unit unit : context.units) {
            if (isIdleAlly(unit, context) && unit.getType() == workerType) {
                isFreeCell(context, -1, 99);
                commandMove(unit, -1, 99);
                commandBuild(unit, barracksType, 99, -1);
            }
        }
    }""",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "CandidateAgent.java"
            source_path.write_text(source, encoding="utf-8")
            classes_dir = root / "classes"
            compiled = compile_generated_agent(
                source_path,
                microrts_dir=Path("third_party/microrts"),
                output_dir=classes_dir,
            )
            self.assertTrue(compiled.ok, compiled.stderr)
            result = integrate_microrts_agent(
                microrts_dir=Path("third_party/microrts"),
                classes_dir=classes_dir,
                agent_class="ai.generated.CandidateAgent",
                integration_artifacts_dir=root / "integration",
            )

        self.assertTrue(result.ok, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
