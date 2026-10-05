from __future__ import annotations

import random
import unittest

from eagle.candidate import Candidate
from eagle.operators.selection import (
    GAME_PERFORMANCE_SELECTION,
    population_signature,
    select_next_generation,
    select_parent,
)


def candidate(
    candidate_id: str,
    fitness: float,
    actions: tuple[str, ...] | None = None,
    *,
    dataset_id: str = "probe-suite-v1",
    probes: tuple[str, ...] = ("early", "mid", "late"),
    status: str = "complete",
) -> Candidate:
    item = Candidate(
        id=candidate_id,
        status="evaluated",
        game_eval_result={"game_performance": fitness},
    )
    if actions is not None or status != "unavailable":
        action_values = actions or ()
        object.__setattr__(item, "semantic_signature", {
            "status": status,
            "dataset_id": dataset_id,
            "probe_ids": list(probes),
            "action_hashes": list(action_values),
            "global_hash": f"global-{candidate_id}",
        })
    return item


class SingleObjectiveSelectionTests(unittest.TestCase):
    def test_parent_uses_inclusive_top_tolerance_tier(self) -> None:
        population = [
            candidate("maximum", 10.0, ("a", "a", "a")),
            candidate("boundary", 9.0, ("b", "b", "b")),
            candidate("outside", 8.999999, ("c", "c", "c")),
        ]

        selected_ids = {
            select_parent(
                population,
                random.Random(seed),
                selection_mode=GAME_PERFORMANCE_SELECTION,
            ).id
            for seed in range(40)
        }

        self.assertEqual(selected_ids, {"maximum", "boundary"})

    def test_parent_reference_prefers_maximum_compatible_distance(self) -> None:
        reference = candidate("reference", 10.0, ("a", "a", "a"))
        population = [
            reference,
            candidate("same", 10.0, ("a", "a", "a")),
            candidate("partial", 9.5, ("a", "b", "a")),
            candidate("different", 9.0, ("b", "b", "b")),
        ]

        chosen = select_parent(
            population,
            random.Random(7),
            selection_mode=GAME_PERFORMANCE_SELECTION,
            semantic_reference=reference,
        )

        self.assertEqual(chosen.id, "different")

    def test_parent_missing_or_incompatible_signature_is_fallback(self) -> None:
        reference = candidate("reference", 5.0, ("a", "a", "a"))
        compatible = candidate("compatible", 5.0, ("a", "a", "a"))
        incompatible = candidate(
            "incompatible",
            5.0,
            ("b", "b", "b"),
            dataset_id="other-suite",
        )
        missing = candidate("missing", 5.0, None, status="unavailable")

        chosen = select_parent(
            [compatible, incompatible, missing],
            random.Random(1),
            selection_mode=GAME_PERFORMANCE_SELECTION,
            semantic_reference=reference,
        )

        self.assertEqual(chosen.id, "compatible")

    def test_survivor_tiers_are_anchored_and_do_not_chain(self) -> None:
        population = [
            candidate("maximum", 10.0, None, status="unavailable"),
            candidate("within", 9.4, None, status="unavailable"),
            candidate("chained-only", 8.8, None, status="unavailable"),
        ]

        selected = select_next_generation(
            population,
            [],
            population_size=2,
            rng=random.Random(3),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual([item.id for item in selected], ["maximum", "within"])

    def test_survivor_selection_rejects_an_all_failed_pool(self) -> None:
        failed = [
            Candidate(
                id="failed-parent",
                status="failed",
                failure_stage="runtime",
                failure_reason="runtime exception",
                game_eval_result={"game_performance": -1000.0},
            ),
            Candidate(
                id="failed-child",
                status="failed",
                failure_stage="runtime",
                failure_reason="runtime exception",
                game_eval_result={"game_performance": -1000.0},
            ),
        ]

        with self.assertRaisesRegex(ValueError, "every parent and offspring"):
            select_next_generation(
                failed,
                [],
                population_size=1,
                rng=random.Random(3),
                selection_mode=GAME_PERFORMANCE_SELECTION,
            )

    def test_failed_offspring_cannot_replace_valid_parents(self) -> None:
        parents = [
            candidate("parent-a", 10.0, ("a", "a", "a")),
            candidate("parent-b", 9.0, ("b", "b", "b")),
        ]
        failed_offspring = [
            Candidate(
                id="failed-child-a",
                status="failed",
                failure_stage="runtime",
                failure_reason="runtime exception",
                game_eval_result={"game_performance": -1000.0},
            ),
            Candidate(
                id="failed-child-b",
                status="failed",
                failure_stage="runtime",
                failure_reason="runtime exception",
                game_eval_result={"game_performance": -1000.0},
            ),
        ]

        selected = select_next_generation(
            parents,
            failed_offspring,
            population_size=2,
            rng=random.Random(3),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual({item.id for item in selected}, {"parent-a", "parent-b"})

    def test_survivor_keeps_better_tier_then_uses_boundary_novelty(self) -> None:
        best = candidate("best", 12.0, ("a", "a", "a"))
        same = candidate("same", 10.0, ("a", "a", "a"))
        partial = candidate("partial", 9.5, ("a", "b", "a"))
        different = candidate("different", 9.0, ("b", "b", "b"))

        selected = select_next_generation(
            [best, same],
            [partial, different],
            population_size=2,
            rng=random.Random(9),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual([item.id for item in selected], ["best", "different"])

    def test_boundary_selection_is_farthest_first(self) -> None:
        population = [
            candidate("same-a", 4.0, ("a", "a", "a")),
            candidate("same-b", 4.0, ("a", "a", "a")),
            candidate("different", 4.0, ("b", "b", "b")),
        ]

        selected = select_next_generation(
            population,
            [],
            population_size=2,
            rng=random.Random(2),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertIn("different", {item.id for item in selected})
        self.assertEqual(len({item.id for item in selected}), 2)

    def test_complete_summaries_seed_before_missing_fallback(self) -> None:
        population = [
            candidate("known-a", 4.0, ("a", "a", "a")),
            candidate("known-b", 4.0, ("b", "b", "b")),
            candidate("missing", 4.0, None, status="unavailable"),
        ]

        selected = select_next_generation(
            population,
            [],
            population_size=2,
            rng=random.Random(8),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual({item.id for item in selected}, {"known-a", "known-b"})

    def test_invalid_complete_summary_is_treated_as_fallback(self) -> None:
        valid = candidate("valid", 4.0, ("a", "a", "a"))
        invalid = candidate("invalid", 4.0, ("b",), probes=("early", "mid"))

        selected = select_next_generation(
            [valid, invalid],
            [],
            population_size=1,
            rng=random.Random(4),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual(selected[0].id, "valid")

    def test_scalar_survivors_remain_unique_across_parent_and_offspring_pool(self) -> None:
        duplicate = candidate("duplicate", 4.0, None, status="unavailable")
        other = candidate("other", 3.0, None, status="unavailable")

        selected = select_next_generation(
            [duplicate],
            [duplicate, other],
            population_size=2,
            rng=random.Random(1),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual({item.id for item in selected}, {"duplicate", "other"})

    def test_scalar_selection_is_seed_reproducible(self) -> None:
        population = [
            candidate("a", 4.0, ("a", "a", "a")),
            candidate("b", 4.0, ("b", "b", "b")),
            candidate("c", 4.0, ("c", "c", "c")),
        ]

        first = select_next_generation(
            population,
            [],
            population_size=2,
            rng=random.Random(17),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )
        second = select_next_generation(
            population,
            [],
            population_size=2,
            rng=random.Random(17),
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual([item.id for item in first], [item.id for item in second])

    def test_scalar_population_signature_tracks_fitness_and_semantics_not_ids(self) -> None:
        first = [candidate("first", 4.0, ("a", "a", "a"))]
        equivalent = [candidate("first", 4.0, ("a", "a", "a"))]
        object.__setattr__(equivalent[0], "id", "equivalent")
        changed = [candidate("changed", 4.0, ("b", "b", "b"))]

        first_signature = population_signature(
            first,
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )
        equivalent_signature = population_signature(
            equivalent,
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )
        changed_signature = population_signature(
            changed,
            selection_mode=GAME_PERFORMANCE_SELECTION,
        )

        self.assertEqual(first_signature, equivalent_signature)
        self.assertNotEqual(first_signature, changed_signature)

    def test_scalar_selection_rejects_missing_or_nonfinite_fitness(self) -> None:
        missing = Candidate(id="missing", game_eval_result={})
        infinite = Candidate(id="infinite", game_eval_result={"game_performance": float("inf")})

        for item in (missing, infinite):
            with self.subTest(item=item.id):
                with self.assertRaisesRegex(ValueError, "game_performance"):
                    select_parent(
                        [item],
                        random.Random(1),
                        selection_mode=GAME_PERFORMANCE_SELECTION,
                    )


if __name__ == "__main__":
    unittest.main()
