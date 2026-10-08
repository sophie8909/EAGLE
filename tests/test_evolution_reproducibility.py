"""EA replay checks use real mock search orchestration, not a substitute algorithm."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.llm import LLMCallLogger
from eagle.evolution.generation import run_generation_step
from eagle.evaluation.pipeline import evaluate_population
from eagle.run_artifacts import record_error_memory
from eagle.evolution.offspring import plan_offspring
from eagle.evolution.resume import resume_search
from eagle.evolution.search import run_search
from eagle.operators.adaptive import build_reflection_operator_controller
from eagle.operators.selection import select_next_generation, select_parent
from eagle.opponent_cases import LEXICASE_CASES


def evolutionary_state(result):
    """Exclude wall clocks/paths while retaining every generation and phenotype."""
    snapshots = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((result.run_dir / "generations").glob("generation_*.json"))
        if path.stem.removeprefix("generation_").isdigit()
    ]
    generations = [
        (snapshot["generation"], snapshot["population"], snapshot["aos"],
         snapshot["stagnation_count"], snapshot["best_candidate_id"])
        for snapshot in snapshots
    ]
    candidates = []
    for path in sorted((result.run_dir / "candidates").glob("*/candidate.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        java_path = path.parent / "phenotype" / "CandidateAgent.java"
        candidates.append((
            value["candidate_id"], value["parent_ids"],
            (path.parent / "genotype" / "policy_prompt.txt").read_text(encoding="utf-8"),
            (path.parent / "genotype" / "code_generation_prompt.txt").read_text(encoding="utf-8"),
            value["operator"], value["mutation_type"],
            value["fitness_objectives"], value["semantic_signature"],
            hashlib.sha256(java_path.read_bytes()).hexdigest() if java_path.is_file() else None,
        ))
    return generations, candidates, result.completed_generation, result.stop_reason


class EvolutionReproducibilityTests(unittest.TestCase):
    def config(self, root, *, seed=19, workers=1, algorithm="lexicase"):
        return replace(ExperimentConfig.from_mapping({
            "population_size": 2,
            "generations": 2,
            "random_seed": seed,
            "crossover_rate": 0.65,
            "mutation_rate": 1.0,
            "algorithm": algorithm,
            "reflection_operator_mode": "aos_head2head" if algorithm == "lexicase" else "static",
            "evaluation": {
                "mode": "fixed_roster" if algorithm == "lexicase" else "self_play",
                "match_workers": workers,
                "self_play_refresh_interval": 1,
            },
            "model": {"name": "mock", "parallel": workers},
            "strategy_reflection_probability": 0.4,
            "prompt_reflection_probability": 0.4,
            "code_reflection_probability": 0.2,
        }), runs_dir=root / "runs")

    def test_repeated_search_and_thread_counts_reproduce_every_generation(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            for algorithm in ("lexicase", "game_performance_semantic_tiebreak"):
                with self.subTest(algorithm=algorithm):
                    config = self.config(root, algorithm=algorithm)
                    first = run_search(config, mock=True, run_id=f"{algorithm}-first")
                    repeated = run_search(config, mock=True, run_id=f"{algorithm}-repeat")
                    parallel = run_search(replace(config, match_workers=4,
                        model=replace(config.model, parallel=4)), mock=True,
                        run_id=f"{algorithm}-parallel")
                    self.assertEqual(evolutionary_state(first), evolutionary_state(repeated))
                    self.assertEqual(evolutionary_state(first), evolutionary_state(parallel))
                    other_seed = run_search(replace(config, random_seed=20), mock=True,
                        run_id=f"{algorithm}-other-seed")
                    self.assertNotEqual(evolutionary_state(first), evolutionary_state(other_seed))

    def test_interrupted_resume_matches_uninterrupted_search(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            config = self.config(root)
            expected = run_search(config, mock=True, run_id="uninterrupted")
            def interrupt_before_generation_two(**kwargs):
                if kwargs["generation"] == 2:
                    raise KeyboardInterrupt
                return run_generation_step(**kwargs)
            with patch("eagle.evolution.search.run_generation_step", side_effect=interrupt_before_generation_two):
                with self.assertRaises(KeyboardInterrupt):
                    run_search(config, mock=True, run_id="interrupted")
            resumed = resume_search(run_dir=root / "runs" / "interrupted", mock=True)
            self.assertEqual(evolutionary_state(expected), evolutionary_state(resumed))

    def test_partial_candidate_evidence_is_archived_before_resume(self):
        for algorithm in ("lexicase", "game_performance_semantic_tiebreak"):
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                root = Path(directory)
                config = self.config(root, algorithm=algorithm)
                expected = run_search(config, mock=True, run_id="partial-reference")
                preserved = {}
                def interrupt_after_first_candidate(candidates, **kwargs):
                    if kwargs["generation"] != 2:
                        return evaluate_population(candidates, **kwargs)
                    evaluated = evaluate_population(candidates[:1], **kwargs)
                    candidate = evaluated[0]
                    run_dir = kwargs["candidates_dir"].parent
                    path = run_dir / "candidates" / candidate.id / "candidate.json"
                    preserved["relative_path"] = path.relative_to(run_dir)
                    preserved["bytes"] = path.read_bytes()
                    log = LLMCallLogger(run_dir / "llm_logs").write(
                        stage="generation", input_text="", status="success", backend="mock",
                        model="mock", candidate_id=candidate.id, generation=2,
                        artifact_refs={"candidate": path.relative_to(run_dir).as_posix()})
                    preserved["log"] = log.relative_to(run_dir)
                    record_error_memory(run_dir, [replace(candidate, status="failed",
                        failure_reason="interrupted uncommitted evaluation")])
                    raise KeyboardInterrupt
                with patch("eagle.evolution.generation.evaluate_population", side_effect=interrupt_after_first_candidate):
                    with self.assertRaises(KeyboardInterrupt):
                        run_search(config, mock=True, run_id="partial-candidate")
                resumed = resume_search(run_dir=root / "runs" / "partial-candidate", mock=True)
                self.assertEqual(evolutionary_state(expected), evolutionary_state(resumed))
                archive = resumed.run_dir / "archives" / "interrupted_work" / "attempt_0001"
                self.assertEqual((archive / preserved["relative_path"]).read_bytes(), preserved["bytes"])
                self.assertTrue((archive / "archives" / "error_memory.jsonl").is_file())
                archived_log = json.loads((archive / preserved["log"]).read_text(encoding="utf-8"))
                self.assertEqual((resumed.run_dir / archived_log["artifact_refs"]["candidate"]).read_bytes(),
                    preserved["bytes"])
                for name in ("strategy.json", "error_memory.jsonl", "self_play_opponents.json"):
                    def contents(run_dir):
                        path = run_dir / "archives" / name
                        return path.read_text(encoding="utf-8") if path.is_file() else None
                    self.assertEqual(contents(expected.run_dir), contents(resumed.run_dir))

    def test_resume_preserves_stagnation_stop_generation(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            config = replace(self.config(root), population_size=1, mutation_rate=0.0,
                crossover_rate=0.0, stagnation_generations=2, generations=5)
            expected = run_search(config, mock=True, run_id="stagnation-full")
            def interrupt_before_generation_two(**kwargs):
                if kwargs["generation"] == 2:
                    raise KeyboardInterrupt
                return run_generation_step(**kwargs)
            with patch("eagle.evolution.search.run_generation_step", side_effect=interrupt_before_generation_two):
                with self.assertRaises(KeyboardInterrupt):
                    run_search(config, mock=True, run_id="stagnation-partial")
            resumed = resume_search(run_dir=root / "runs" / "stagnation-partial", mock=True)
            self.assertEqual(expected.stop_reason, "stagnation_2_generations")
            self.assertEqual(evolutionary_state(expected), evolutionary_state(resumed))
            stopped_resume = resume_search(run_dir=resumed.run_dir, mock=True)
            self.assertEqual(evolutionary_state(expected), evolutionary_state(stopped_resume))

    def test_root_seed_controls_plans_independent_of_order_and_rng_history(self):
        config = ExperimentConfig.from_mapping({
            "population_size": 6, "mutation_rate": 1.0, "crossover_rate": 0.65,
            "random_seed": 19,
        })
        parents = [Candidate(id=f"parent-{index}", strategy_prompt=f"policy-{index}",
            fitness_objectives={case: 0.0 for case in LEXICASE_CASES},
            game_eval_result={"game_performance": 0.0}, status="evaluated") for index in range(4)]
        mutations = {name: object() for name in ("strategy", "prompt", "code")}
        def assignments(items, settings, supplied_rng):
            with contextlib.redirect_stdout(io.StringIO()):
                plans = plan_offspring(items, config=settings, generation=2,
                    rng=supplied_rng, mutations=mutations,
                    operator_controller=build_reflection_operator_controller(settings))
            return [(plan.candidate.id, plan.candidate.parent_ids,
                     plan.candidate.strategy_parent_id, plan.candidate.generation_prompt_parent_id,
                     plan.mutation_name, plan.mutation_intent) for plan in plans]
        first = assignments(parents, config, random.Random(1))
        self.assertEqual(first, assignments(list(reversed(parents)), config, random.Random(999)))
        self.assertNotEqual([item[1:] for item in first],
            [item[1:] for item in assignments(parents, replace(config, random_seed=20), random.Random(1))])
        for mode in ("lexicase", "game_performance_semantic_tiebreak"):
            self.assertEqual(select_parent(parents, random.Random(7), selection_mode=mode).id,
                select_parent(list(reversed(parents)), random.Random(7), selection_mode=mode).id)
            left = select_next_generation(parents[:2], parents[2:], population_size=2,
                rng=random.Random(7), selection_mode=mode)
            right = select_next_generation(list(reversed(parents[:2])), list(reversed(parents[2:])),
                population_size=2, rng=random.Random(7), selection_mode=mode)
            self.assertEqual([candidate.id for candidate in left], [candidate.id for candidate in right])


if __name__ == "__main__":
    unittest.main()
