import json
import unittest

from evaluation.code_quality import (
    analyze_compilation,
    build_failure_code_quality,
    build_successful_code_quality,
    failure_code_quality,
)
from evaluation.compiler import CompileResult
from evaluation.function_capability import (
    FunctionCapabilityResult,
    evaluate_function_capability,
)
from evaluation.microrts_runner import MatchResult
from evaluation.strategy_alignment import (
    StrategyAlignmentBackend,
    StrategyAlignmentResult,
    evaluate_strategy_alignment,
    parse_strategy_alignment_response,
)


class FixedAlignmentBackend(StrategyAlignmentBackend):
    def __init__(self, response):
        self.response = response
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        return self.response


def alignment_result(score):
    return StrategyAlignmentResult(
        request="request",
        raw_response=json.dumps({"score": score, "reason": "aligned"}),
        parsed_response={"score": float(score), "reason": "aligned"},
        score=float(score),
        reason="aligned",
        status="success",
        error=None,
        started_at="2026-07-16T00:00:00+00:00",
        finished_at="2026-07-16T00:00:01+00:00",
        duration_seconds=1.0,
        attempts=(),
    )


def capability_result(score_per_capability):
    return FunctionCapabilityResult(
        economy_score=score_per_capability,
        production_score=score_per_capability,
        combat_score=score_per_capability,
        targeting_score=score_per_capability,
        state_aware_decision_score=score_per_capability,
        evidence={},
    )


class Phase4CodeQualityTests(unittest.TestCase):
    def test_compilation_warning_penalty_deduplicates_and_caps(self):
        repeated = "A.java:1: warning: [unchecked] duplicate\n" * 2
        compiler = analyze_compilation(CompileResult(True, [], stderr=repeated))
        self.assertEqual(compiler.warning_count, 1)
        self.assertEqual(compiler.compilation_score, -50)

        warnings = "\n".join(
            f"A.java:{line}: warning: warning {line}" for line in range(1, 12)
        )
        capped = analyze_compilation(CompileResult(True, [], stderr=warnings))
        self.assertEqual(capped.warning_count, 11)
        self.assertEqual(capped.compilation_score, -500)

    def test_failure_hierarchy_and_boundaries(self):
        self.assertEqual(failure_code_quality("generation"), -1000)
        self.assertEqual(failure_code_quality("validation"), -950)
        self.assertEqual(failure_code_quality("compilation", error_count=20), -900)
        self.assertEqual(failure_code_quality("integration", integration_pass_ratio=0.5), -550)
        self.assertEqual(failure_code_quality("runtime", completed_matches=0), -400)
        self.assertEqual(failure_code_quality("runtime", completed_matches=5), -300)
        self.assertEqual(failure_code_quality("runtime", completed_matches=9), -221)

    def test_successful_formula_exact_range(self):
        clean = analyze_compilation(CompileResult(True, []))
        maximum = build_successful_code_quality(
            clean,
            capability_result(20),
            alignment_result(10),
        )
        self.assertEqual(maximum.code_quality, 610)

        warnings = "\n".join(
            f"A.java:{line}: warning: warning {line}" for line in range(1, 12)
        )
        penalized = analyze_compilation(CompileResult(True, [], stderr=warnings))
        minimum = build_successful_code_quality(
            penalized,
            capability_result(0),
            alignment_result(0),
        )
        self.assertEqual(minimum.code_quality, 0)
        self.assertEqual(maximum.objective_formula_version, "eagle-objectives-phase4-v1")

    def test_compilation_failure_uses_structured_error_count(self):
        compiler = analyze_compilation(
            CompileResult(False, [], stderr="A.java:1: error: bad", returncode=1)
        )
        quality = build_failure_code_quality("compilation", compiler=compiler)
        self.assertEqual(quality.compile_error_count, 1)
        self.assertEqual(quality.code_quality, -805)

    def test_function_capability_combines_static_and_runtime_evidence(self):
        source = """
        public PlayerAction getAction(int player, GameState gs) {
            if (gs.getPlayer(player).getResources() > 0) {
                harvest(worker, resource);
                train(base, unitType);
                attack(unit, target);
                int x = target.getX();
            }
            return new PlayerAction();
        }
        """
        match = MatchResult(
            ok=True,
            score=100.0,
            command=[],
            winner=0,
            raw_result={
                "players": {"p0": {"carried_resources": 1}},
                "final_scoreboard": {
                    "units_produced": 2,
                    "damage_dealt": 4,
                    "state_transitions": 3,
                },
            },
        )
        result = evaluate_function_capability(source, [match])
        self.assertEqual(result.function_score, 100)
        self.assertEqual(
            [
                result.economy_score,
                result.production_score,
                result.combat_score,
                result.targeting_score,
                result.state_aware_decision_score,
            ],
            [20, 20, 20, 20, 20],
        )

    def test_function_capability_ignores_unreachable_evidence_and_method_names(self):
        source = """
        public PlayerAction arbitraryEntry(int p, GameState state) {
            if (false) {
                harvest(a, b); train(a, b); attack(a, b); b.getX();
                if (state.getUnits() != null) { return null; }
            }
            return new PlayerAction();
        }
        """
        result = evaluate_function_capability(source, [])
        self.assertEqual(result.function_score, 0)

    def test_strategy_alignment_persists_raw_and_parsed_response(self):
        backend = FixedAlignmentBackend('{"score": 7.5, "reason": "Production matches."}')
        result = evaluate_strategy_alignment(
            strategy_prompt="Build workers before attacking.",
            generated_java="public class CandidateAgent {}",
            behavior_summary={"units_produced": 4},
            backend=backend,
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.score, 7.5)
        self.assertEqual(result.reason, "Production matches.")
        self.assertEqual(result.parsed_response, {"score": 7.5, "reason": "Production matches."})
        self.assertEqual(result.raw_response, backend.response)
        self.assertEqual(len(result.attempts), 1)
        self.assertIn("Build workers before attacking.", backend.requests[0])

    def test_strategy_alignment_rejects_invalid_results(self):
        with self.assertRaises(ValueError):
            parse_strategy_alignment_response('{"score": 11, "reason": "too high"}')
        backend = FixedAlignmentBackend('{"score": "bad", "reason": "invalid"}')
        result = evaluate_strategy_alignment(
            strategy_prompt="strategy",
            generated_java="source",
            behavior_summary=None,
            backend=backend,
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.score, 0)
        self.assertIsNone(result.parsed_response)
        self.assertEqual(result.raw_response, backend.response)


if __name__ == "__main__":
    unittest.main()
