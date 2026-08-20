from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.artifacts import write_candidate_inputs
from eagle.candidate import Candidate
from eagle.strategy_diversity import (
    archive_niches,
    build_strategy_niche,
    ensure_strategy_archive,
    generation_diversity_metrics,
    load_strategy_archive,
    normalize_strategy_signature,
    strategy_distance,
    update_strategy_archive,
)
from eagle.strategy_reflection import (
    STRATEGY_MUTATION_INTENT_DISTRIBUTION,
    MockRoleBackend,
    StrategyReflectionMutation,
    select_strategy_mutation_intent,
)
from eagle.mutation import ReflectionContext
from eagle.reflection_context import EvolutionContext
from eagle.opponent_cases import LEXICASE_CASES


def candidate(
    candidate_id: str,
    niche: str,
    *,
    generation: int = 0,
    game: float = 0.0,
    quality: float = 0.0,
    mutation_type: str | None = None,
    intent: str | None = None,
    parent_niche: str | None = None,
    changed: bool | None = None,
) -> Candidate:
    signature = {
        "opening": "worker_first",
        "economy": "balanced_worker",
        "production": ["light"],
        "attack_timing": "early",
        "combat_style": "rush",
        "expansion": "none",
        "defense": "reactive",
        "target_priority": "workers",
    } if niche != "unknown" else {}
    return Candidate(
        id=candidate_id,
        generation=generation,
        strategy_prompt="Use a deterministic strategy.",
        generated_java="class CandidateAgent {}",
        strategy_signature=signature,
        strategy_niche=niche,
        mutation_type=mutation_type,
        mutation_intent=intent,
        parent_strategy_niche=parent_niche,
        niche_changed=changed,
        status="evaluated",
        fitness_objectives={case: game for case in LEXICASE_CASES},
        game_eval_result={"game_performance": game},
        code_quality_result={"code_quality": quality},
    )


class StrategyDiversityTests(unittest.TestCase):
    def test_signature_normalizes_synonyms_and_multiple_production_types(self):
        signature = normalize_strategy_signature({
            "opening": "fast rush",
            "economy": "balanced workers",
            "production": ["lights", "ranged"],
            "attack_timing": "early attack",
            "combat_style": "counterattack",
        })
        self.assertEqual(signature["opening"], "fast_combat")
        self.assertEqual(signature["economy"], "balanced_worker")
        self.assertEqual(signature["production"], ["light", "ranged"])
        self.assertEqual(signature["attack_timing"], "early")
        self.assertEqual(signature["combat_style"], "counter_attack")
        self.assertEqual(normalize_strategy_signature({"production": ["light", "lights"]})["production"], ["light"])

    def test_niche_is_deterministic_and_uses_major_structure(self):
        first = {"attack_timing": "early", "production": ["light"], "combat_style": "rush"}
        equivalent = {"attack_timing": "early attack", "production": ["lights"], "combat_style": "fast rush"}
        self.assertEqual(build_strategy_niche(first), "early-light-rush")
        self.assertEqual(build_strategy_niche(first), build_strategy_niche(equivalent))
        self.assertEqual(build_strategy_niche({"attack_timing": "mid", "production": ["light", "ranged"], "economy": "balanced_worker", "combat_style": "balanced"}), "mid-mixed-balanced")
        self.assertNotEqual(build_strategy_niche(first), build_strategy_niche({"attack_timing": "late", "production": ["heavy"], "combat_style": "defensive"}))
        self.assertEqual(build_strategy_niche({}), "unknown")

    def test_signature_distance_is_normalized_and_single_candidate_safe(self):
        signature = {"attack_timing": "early", "production": ["light"], "combat_style": "rush"}
        different = {"attack_timing": "late", "production": ["heavy"], "combat_style": "defensive"}
        self.assertEqual(strategy_distance(signature, signature), 0.0)
        self.assertGreater(strategy_distance(signature, different), 0.0)
        self.assertLessEqual(strategy_distance(signature, different), 1.0)
        metrics = generation_diversity_metrics([candidate("one", "early-light-rush")])
        self.assertEqual(metrics["unique_niches"], 1)
        self.assertEqual(metrics["mean_strategy_distance"], 0.0)

    def test_intent_distribution_and_reproducible_selection(self):
        self.assertAlmostEqual(sum(probability for _, probability in STRATEGY_MUTATION_INTENT_DISTRIBUTION), 1.0)
        self.assertEqual({select_strategy_mutation_intent(seed=seed) for seed in range(500)}, {"REFINE", "COUNTER", "STRUCTURAL", "ALTERNATIVE"})
        self.assertEqual(select_strategy_mutation_intent(seed=123), select_strategy_mutation_intent(seed=123))

    def test_coach_outputs_signature_intent_and_persists_intent_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = root / "states"
            from evaluation.match_trace import write_match_trace
            from evaluation.runtime_evaluation import write_mock_round_state
            write_mock_round_state(states, tick=0, p0_resource=1, p1_resource=1)
            log = write_match_trace(
                round_state_dir=states,
                match_dir=root / "match",
                metadata={"match_id": "m", "opponent_name": "passive"},
                result={},
                expected_last_tick=0,
            ).trace_path
            backend = MockRoleBackend()
            result = StrategyReflectionMutation(backend, max_attempts=1, selection_seed=4).run(
                candidate("parent", "early-light-rush", generation=2),
                ReflectionContext(
                    evolution=EvolutionContext(generation_index=2),
                    per_match_results=({"match_id": "m", "winner": 0, "candidate_player": 0, "match_trace_path": str(log)},),
                ),
                artifact_dir=root / "child",
                mutation_intent="STRUCTURAL",
            )
            self.assertEqual(result.status, "success")
            self.assertEqual(result.candidate.mutation_intent, "STRUCTURAL")
            self.assertEqual(result.candidate.strategy_niche, "mid-mixed-pressure")
            self.assertIn("Mutation Intent: STRUCTURAL", next(item for item in backend.prompts if "ROLE: coach" in item))
            payload = json.loads((root / "child" / "reflection" / "mutation_intent.json").read_text())
            self.assertEqual(payload["mutation_intent"], "STRUCTURAL")
            self.assertTrue(result.candidate.niche_changed)

    def test_candidate_signature_artifact_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = candidate("candidate", "early-light-rush", intent="REFINE")
            write_candidate_inputs(root, item)
            payload = json.loads((root / item.id / "genotype" / "strategy_signature.json").read_text())
            self.assertEqual(payload["strategy_niche"], "early-light-rush")
            self.assertEqual(payload["mutation_intent"], "REFINE")

    def test_archive_keeps_one_best_valid_representative(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            ensure_strategy_archive(run)
            update_strategy_archive(run, [candidate("worse", "early-light-rush", game=2, quality=90)])
            update_strategy_archive(run, [candidate("better", "early-light-rush", game=3, quality=1)])
            update_strategy_archive(run, [candidate("invalid", "late-heavy-defensive", game=-1000)])
            update_strategy_archive(run, [candidate("other", "mid-mixed-balanced", game=1, quality=99)])
            archive = load_strategy_archive(run)["niches"]
            self.assertEqual(archive_niches(run), {"early-light-rush", "mid-mixed-balanced"})
            self.assertEqual(archive["early-light-rush"]["representative_candidate_id"], "better")

    def test_generation_metrics_track_niches_revisits_and_intent_rates(self):
        population = [
            candidate("a", "early-light-rush", game=1),
            candidate("b", "early-light-rush", game=2, mutation_type="strategy", intent="REFINE", parent_niche="early-light-rush", changed=False),
            candidate("c", "mid-mixed-balanced", game=3, mutation_type="strategy", intent="STRUCTURAL", parent_niche="early-light-rush", changed=True),
            candidate("legacy", "unknown"),
        ]
        metrics = generation_diversity_metrics(population, previous_archive_niches={"early-light-rush"})
        self.assertEqual(metrics["unique_niches"], 2)
        self.assertEqual(metrics["dominant_niche"], "early-light-rush")
        self.assertEqual(metrics["dominant_niche_ratio"], 0.5)
        self.assertEqual(metrics["new_niches"], 1)
        self.assertEqual(metrics["revisited_niches"], 2)
        self.assertEqual(metrics["niche_change_rate"], 0.5)
        self.assertEqual(metrics["intent_niche_change_rates"]["REFINE"], 0.0)
        self.assertEqual(metrics["intent_niche_change_rates"]["STRUCTURAL"], 1.0)
        self.assertEqual(metrics["unknown_signature_count"], 1)


if __name__ == "__main__":
    unittest.main()
