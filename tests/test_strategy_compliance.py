from __future__ import annotations

import unittest

from eagle.strategy_compliance import validate_strategy_prompt_contract


class StrategyComplianceTests(unittest.TestCase):
    def test_accepts_current_state_and_legal_action_policy(self) -> None:
        validate_strategy_prompt_contract(
            "An idle Base trains a Worker into a free adjacent cell when resources are at least 1. "
            "One idle Worker carrying a resource returns it to a friendly Base. "
            "Each other idle Worker targets the nearest current enemy Base, "
            "moves toward it, and attacks when in range."
        )

    def test_rejects_closed_world_history_and_future_prediction(self) -> None:
        for policy in (
            "If the enemy Base is destroyed, return all Workers home.",
            "Attack an enemy that would destroy the Base before the next production cycle.",
            "Move toward enemy territory when the opponent economy stagnates.",
            "If the stockpile has not increased for 500 cycles, build a Barracks.",
            "Have an idle Worker move toward the nearest enemy structure encountered.",
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                ValueError, "closed-world MicroRTS contract"
            ):
                validate_strategy_prompt_contract(policy)

    def test_rejects_illegal_production_relations_and_costs(self) -> None:
        for policy in (
            "Assign an idle Worker to train a Worker.",
            "Have an idle Worker build a Light unit into a free adjacent cell.",
            "An idle Barracks trains a Worker.",
            "A Base produces a Heavy unit.",
            "If resources >= 1, have a Worker build a Base.",
            "If resources >= 2, have a Worker build a Barracks.",
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                ValueError, "closed-world MicroRTS contract"
            ):
                validate_strategy_prompt_contract(policy)

    def test_rejects_impossible_absent_actor_fallback(self) -> None:
        with self.assertRaisesRegex(ValueError, "no Worker exists"):
            validate_strategy_prompt_contract(
                "If no Workers remain, assign an idle Worker to build a Barracks."
            )

    def test_accepts_complete_production_and_construction_prerequisites(self) -> None:
        validate_strategy_prompt_contract(
            "An idle Base trains a Worker into a free adjacent cell when stockpile >= 1. "
            "An idle Barracks trains a Heavy into a free adjacent cell when stockpile >= 2. "
            "An idle Worker builds a Barracks on a legal free cell when stockpile >= 5."
        )
        validate_strategy_prompt_contract(
            "Idle Bases train Workers into free adjacent cells when stockpile >= 1."
        )
        validate_strategy_prompt_contract(
            "An idle Base trains a Worker into a free adjacent cell when stockpile is ≥ 1."
        )
        validate_strategy_prompt_contract(
            "If no enemy units exist within range 1, have that idle Worker move toward "
            "the nearest enemy unit within range 3 if it exists."
        )
        validate_strategy_prompt_contract(
            "1. **Threat Response:** If an enemy Worker exists within distance 1, "
            "have an idle Worker target and attack it."
        )
        validate_strategy_prompt_contract(
            "**Barracks Build:** If no enemy Workers exist, have an idle Worker build "
            "a Barracks on a legal free adjacent cell when stockpile at least 5."
        )
        validate_strategy_prompt_contract(
            "If a friendly Base is idle, the stockpile is at least 10, a free cell "
            "adjacent to that Base exists, and a free cell adjacent to an idle Worker "
            "exists, have that Worker build a Barracks on that free cell adjacent to itself."
        )

    def test_rejects_missing_action_prerequisites(self) -> None:
        for policy, expected in (
            ("A Base trains a Worker when stockpile >= 1.", "free adjacent cell"),
            ("An idle Barracks trains a Light when stockpile >= 2.", "free adjacent cell"),
            ("Build a Base when stockpile >= 10.", "existing Worker"),
            ("Assign a Worker to attack the nearest enemy.", "idle friendly actor"),
            ("An idle Worker returns to a friendly Base.", "currently carrying"),
            (
                "If a friendly Base is idle and a free adjacent cell exists, have a "
                "Worker build a Barracks on that cell when stockpile >= 5.",
                "idle Worker",
            ),
            (
                "If a friendly Worker is idle and a free cell adjacent to a Base exists, "
                "have that Worker build a Barracks on that cell when stockpile >= 5.",
                "adjacent to the acting Worker",
            ),
            (
                "If a friendly Worker is idle and a free cell adjacent to a friendly Base "
                "exists, have that Worker build a Base on that cell when stockpile >= 10.",
                "adjacent to the acting Worker",
            ),
            (
                "Have an idle Worker carrying no resource harvest a Resource.",
                "reachable Resource",
            ),
            (
                "If a reachable Resource exists, have an idle Worker harvest it.",
                "carrying no resource",
            ),
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, expected):
                validate_strategy_prompt_contract(policy)

    def test_rejects_invalid_resource_return_semantics(self) -> None:
        for policy, expected in (
            (
                "If a friendly Base exists, have an idle Worker carrying no resource "
                "return to the nearest friendly Base.",
                "currently carrying",
            ),
            (
                "If an idle Worker carries a resource and no friendly Base exists, "
                "have that Worker return the resource to the nearest friendly Worker.",
                "friendly Base",
            ),
            (
                "If an idle Worker carries a resource and a friendly Base exists, "
                "have that Worker return to the friendly Base and target an enemy unit.",
                "one action at a time",
            ),
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, expected):
                validate_strategy_prompt_contract(policy)

    def test_accepts_reachable_friendly_base_as_return_target(self) -> None:
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle, carries 1 resource, and a reachable friendly "
            "Base exists, have that Worker return the resource to the nearest reachable "
            "friendly Base."
        )

    def test_rejects_incorrect_combat_ranges(self) -> None:
        for policy in (
            "If a friendly Heavy is idle and an enemy is within range 3, have it attack.",
            "If a friendly Light or Heavy unit is idle and an enemy unit exists within "
            "range 1 or 3 respectively, have that unit target the enemy.",
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                ValueError, "Light and Heavy attack at range 1"
            ):
                validate_strategy_prompt_contract(policy)

    def test_rejects_attack_range_of_non_attacking_building(self) -> None:
        with self.assertRaisesRegex(ValueError, "have no attack range"):
            validate_strategy_prompt_contract(
                "If an enemy unit is within the attack range of a friendly Base, "
                "have an idle Worker target and attack that enemy."
            )

    def test_rejects_friendly_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "never a friendly entity"):
            validate_strategy_prompt_contract(
                "If a friendly Light is idle and a friendly Barracks exists, have that "
                "Light target the nearest friendly Barracks and move toward it."
            )

    def test_rejects_resource_as_combat_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a combat target"):
            validate_strategy_prompt_contract(
                "If a friendly Worker is idle and a Resource exists, have that Worker "
                "target the nearest Resource and move toward it."
            )

    def test_rejects_reused_actor_without_idle_guard(self) -> None:
        with self.assertRaisesRegex(ValueError, "idle friendly actor"):
            validate_strategy_prompt_contract(
                "If an enemy unit exists, have that Worker target the nearest enemy unit."
            )

    def test_rejects_nearest_target_without_existence_guard(self) -> None:
        for policy in (
            "If no enemy Workers exist within range 1, have an idle Worker target "
            "the nearest enemy Base within range 1.",
            "If no enemy Base exists within range 1, have an idle Worker attack "
            "the nearest enemy unit within range 1.",
            "If an idle Worker and a free adjacent cell exist, have that Worker build "
            "a Base on the cell closest to the nearest enemy unit.",
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                ValueError, "requires a current-state condition"
            ):
                validate_strategy_prompt_contract(policy)

    def test_accepts_nearest_target_with_matching_existence_guard(self) -> None:
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle and an enemy Base exists, have that Worker "
            "move toward the nearest enemy Base."
        )
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle and the count of enemy Workers is at least 2, "
            "have that Worker target the nearest enemy Worker."
        )
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle, have that Worker move toward the nearest "
            "enemy Base if exists, or the center of the map."
        )
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle, no enemy unit within range 1 exists, and an "
            "enemy building exists, have that Worker move toward the nearest enemy building."
        )
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle, an enemy Light exists within range 1, and no "
            "enemy Ranged exists within range 3, have that Worker attack the enemy Light."
        )

    def test_accepts_ranged_and_shorter_conservative_ranges(self) -> None:
        validate_strategy_prompt_contract(
            "If a friendly Ranged unit is idle and an enemy unit exists within range 3, "
            "have that Ranged unit target and attack that enemy."
        )
        validate_strategy_prompt_contract(
            "If a friendly Heavy is idle and an enemy unit exists within range 1, "
            "have that Heavy target and attack that enemy."
        )
        validate_strategy_prompt_contract(
            "If a friendly Light is idle and an enemy Ranged exists within range 3, "
            "have that Light target the nearest enemy Ranged within range 3, move toward "
            "it, and attack it when within range 1."
        )
        validate_strategy_prompt_contract(
            "If a friendly Light is idle and an enemy Ranged unit exists within range 3 "
            "but not within range 1, have that Light target the nearest enemy Ranged "
            "unit and move toward it until within range 1, then attack."
        )
        validate_strategy_prompt_contract(
            "If a friendly Ranged unit is idle and an enemy Worker exists within range 3, "
            "have that Ranged unit attack the enemy Worker."
        )
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle, an enemy Base exists, and the distance to "
            "that Base is ≤ 1, have that Worker attack the enemy Base."
        )
        validate_strategy_prompt_contract(
            "If a friendly Ranged is idle, an enemy Base exists, and the distance to "
            "that Base is ≤ 3, have that Ranged attack the enemy Base."
        )
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle and an enemy Base exists, have that Worker "
            "target the Base, move toward it, and attack when within range 1."
        )

    def test_rejects_attack_without_actor_range_or_movement(self) -> None:
        for policy in (
            "If a friendly Worker is idle and an enemy Base exists, have that Worker "
            "target and attack the nearest enemy Base.",
            "If a friendly Worker is idle and an enemy Ranged exists within range 3, "
            "have that Worker attack the nearest enemy Ranged.",
            "If a friendly Worker is idle and an enemy Ranged exists within range 3, "
            "have that Worker move toward the enemy Ranged and attack it when within range 3.",
            "If a friendly Worker is idle, an enemy Ranged exists, and the distance to "
            "that Ranged is ≤ 3, have that Worker attack the enemy Ranged.",
            "If a friendly Worker is idle and an enemy unit exists within range 1 of a "
            "friendly Base, have that Worker attack the nearest enemy unit.",
            "If a friendly Light/Heavy/Ranged unit is idle and an enemy unit exists within "
            "range 1 or 3 respectively, have that unit attack the enemy unit.",
            "If a friendly Light/Heavy/Ranged unit is idle and an enemy unit exists within "
            "distance 1 or 3 respectively, have that unit attack the enemy unit.",
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                ValueError, "attack range|range 1|split mixed actor"
            ):
                validate_strategy_prompt_contract(policy)

    def test_ignores_negative_range_guard_when_validating_attack_range(self) -> None:
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle, an enemy Base exists within range 1, and no "
            "enemy Ranged unit exists within range 3, have that Worker attack the enemy Base."
        )
        validate_strategy_prompt_contract(
            "If a friendly Worker is idle, no enemy Base exists and an enemy unit exists "
            "within attack range, have that Worker attack the enemy unit."
        )

    def test_rejects_unobservable_action_state_and_api_language(self) -> None:
        for policy in (
            "If an enemy Worker is attacking the Base, assign an idle Worker to attack it.",
            "If no Worker is currently harvesting, assign an idle Worker to harvest a Resource.",
            "If Base.getHitPoints() <= 2, assign an idle Worker to move.",
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                ValueError, "closed-world MicroRTS contract"
            ):
                validate_strategy_prompt_contract(policy)

    def test_rejects_contradictory_or_vague_rules(self) -> None:
        for policy in (
            "If resources < 5 and resources >= 5, assign an idle Worker to harvest a Resource.",
            "An idle Base trains a Worker whenever resources allow.",
            "If no enemy units or buildings exist, move toward the nearest enemy Base.",
            "If no enemy Base or unit exists, have an idle Worker target the nearest enemy unit.",
            "If no enemy entity exists, have an idle Worker move toward the nearest enemy Base position.",
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                ValueError, "closed-world MicroRTS contract"
            ):
                validate_strategy_prompt_contract(policy)

    def test_rejects_same_target_inside_and_outside_same_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "both within and outside range 1"):
            validate_strategy_prompt_contract(
                "If a friendly Worker is idle, an enemy Light exists within range 1 "
                "of that Worker, and an enemy Light exists outside range 1 of that "
                "Worker, have that Worker target the nearest enemy Light and move toward it."
            )

    def test_rejects_more_than_ten_numbered_rules(self) -> None:
        policy = "\n".join(
            f"{index}. Leave an idle friendly Worker idle."
            for index in range(1, 12)
        )
        with self.assertRaisesRegex(ValueError, "at most 10"):
            validate_strategy_prompt_contract(policy)


if __name__ == "__main__":
    unittest.main()
