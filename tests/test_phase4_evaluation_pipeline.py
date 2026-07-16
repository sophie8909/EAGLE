from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.artifacts import write_candidate_artifacts, write_candidate_inputs
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_candidate
from evaluation.microrts_runner import MatchResult
from generation.backend import MockGenerationBackend


class Phase4EvaluationPipelineTests(unittest.TestCase):
    def test_successful_evaluation_persists_complete_artifacts_and_timing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = Candidate(id="phase4-success", strategy_prompt="Build an economy, produce units, and attack intelligently.")
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            candidates_dir = root / "candidates"
            write_candidate_inputs(candidates_dir, candidate)
            evaluation = evaluate_candidate(
                candidate,
                config=config,
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                match_artifacts_dir=candidates_dir / candidate.id / "matches",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(candidates_dir, evaluation)
            candidate_dir = candidates_dir / candidate.id

            self.assertEqual(len(evaluation.match_results), 10)
            self.assertTrue(all(result.ok for result in evaluation.match_results))
            self.assertIsNone(evaluation.result.failure_stage)
            self.assertNotEqual(evaluation.candidate.fitness_objectives["game_performance"], -1000)
            self.assertIsNotNone(evaluation.function_capability_result)
            self.assertIsNotNone(evaluation.strategy_alignment_result)
            self.assertEqual(evaluation.strategy_alignment_result.score, 10)
            self.assertEqual(
                evaluation.candidate.fitness_objectives["code_quality"],
                500
                + evaluation.code_quality_breakdown.compilation_score
                + evaluation.code_quality_breakdown.function_score
                + evaluation.code_quality_breakdown.strategy_alignment_score,
            )

            timing = json.loads((candidate_dir / "timing.json").read_text(encoding="utf-8"))
            self.assertEqual(len(timing["match_durations_seconds"]), 10)
            self.assertEqual(timing["evaluation"]["status"], "success")
            self.assertEqual(timing["strategy_alignment_llm"]["attempts"][0]["attempt"], 1)
            self.assertGreaterEqual(timing["objective_calculation_duration_seconds"], 0)
            self.assertGreaterEqual(timing["matches_total_duration_seconds"], 0)

            seeds = set()
            for index in range(10):
                match_dir = candidate_dir / "matches" / f"match_{index:02d}"
                result = json.loads((match_dir / "result.json").read_text(encoding="utf-8"))
                match_timing = json.loads((match_dir / "timing.json").read_text(encoding="utf-8"))
                seeds.add(result["seed"])
                self.assertEqual(result["source_hash"], evaluation.match_results[0].source_hash)
                self.assertEqual(result["class_hash"], evaluation.match_results[0].class_hash)
                self.assertEqual(match_timing["status"], "success")
            self.assertEqual(len(seeds), 10)

            alignment = json.loads((candidate_dir / "strategy_alignment" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(alignment["parsed_response"]["score"], 10.0)
            self.assertTrue((candidate_dir / "strategy_alignment" / "request.txt").read_text(encoding="utf-8"))
            self.assertTrue((candidate_dir / "strategy_alignment" / "response_raw.txt").read_text(encoding="utf-8"))
            capability = json.loads((candidate_dir / "evaluation" / "function_capability.json").read_text(encoding="utf-8"))
            objectives = json.loads((candidate_dir / "evaluation" / "objectives.json").read_text(encoding="utf-8"))
            summary = json.loads((candidate_dir / "evaluation" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(capability["function_score"], evaluation.code_quality_breakdown.function_score)
            self.assertEqual(objectives["objective_names"], ["game_performance", "code_quality"])
            self.assertEqual(summary["completed_match_count"], 10)

    def test_partial_runtime_failure_uses_progress_score_and_retains_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = Candidate(id="phase4-partial", strategy_prompt="strategy")
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            candidates_dir = root / "candidates"
            write_candidate_inputs(candidates_dir, candidate)
            calls = []

            def fake_match(**kwargs):
                index = kwargs["match_index"]
                calls.append(index)
                if index == 5:
                    return MatchResult(
                        ok=False,
                        score=0.0,
                        command=["java"],
                        returncode=1,
                        match_index=index,
                        seed=kwargs["seed"],
                        status="failed",
                        failure_category="runtime_exception",
                        failure_reason="boom",
                        duration_seconds=0.01,
                    )
                return MatchResult(
                    ok=True,
                    score=100.0,
                    command=["java"],
                    match_index=index,
                    seed=kwargs["seed"],
                    status="success",
                    duration_seconds=0.01,
                    raw_result={"winner": 0, "result": "p0_win"},
                )

            with patch("eagle.evaluation.run_microrts_match", side_effect=fake_match):
                evaluation = evaluate_candidate(
                    candidate,
                    config=config,
                    backend=MockGenerationBackend(),
                    generated_agents_dir=root / "generated_agents",
                    classes_dir=root / "classes",
                    match_artifacts_dir=candidates_dir / candidate.id / "matches",
                    mock=True,
                    ordinal=0,
                )
            write_candidate_artifacts(candidates_dir, evaluation)
            candidate_dir = candidates_dir / candidate.id

            self.assertEqual(calls, list(range(6)))
            self.assertEqual(evaluation.result.failure_stage, "runtime")
            self.assertEqual(evaluation.result.failure_category, "runtime_exception")
            self.assertEqual(evaluation.candidate.fitness_objectives["game_performance"], -1000)
            self.assertEqual(evaluation.candidate.fitness_objectives["code_quality"], -300)
            self.assertIsNone(evaluation.function_capability_result)
            self.assertIsNone(evaluation.strategy_alignment_result)
            runtime_failure = json.loads((candidate_dir / "evaluation" / "runtime_failure.json").read_text(encoding="utf-8"))
            game_performance = json.loads((candidate_dir / "evaluation" / "game_performance.json").read_text(encoding="utf-8"))
            timing = json.loads((candidate_dir / "timing.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime_failure["completed_match_count"], 5)
            self.assertEqual(len(runtime_failure["retained_matches"]), 6)
            self.assertEqual(game_performance["completed_match_count"], 5)
            self.assertEqual(len(timing["match_durations_seconds"]), 6)
            self.assertEqual(timing["evaluation"]["status"], "failed")
            self.assertEqual(timing["strategy_alignment_llm"]["attempts"], [])


if __name__ == "__main__":
    unittest.main()
