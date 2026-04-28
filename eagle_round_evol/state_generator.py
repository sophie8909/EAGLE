# state_generator.py

import random
from typing import Any


MAP_SIZE = 16

ATTR_ORDER = ["resources", "current_action", "HP"]

HP = {
    "Worker Unit": 1,
    "Light Unit": 4,
    "Heavy Unit": 8,
    "Ranged Unit": 3,
    "Base Unit": 10,
    "Barracks Unit": 5,
}


class StateGenerator:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    # =========================================================
    # Public API
    # =========================================================

    def generate(self) -> dict[str, Any]:
        scenario = self.rng.choices(
            [
                "start",
                "two_workers_no_barracks",
                "many_workers_no_barracks",
                "enemy_barracks",
                "ally_barracks",
                "midgame",
            ],
            weights=[1, 3, 2, 2, 2, 1],
        )[0]

        return getattr(self, f"_scenario_{scenario}")()

    def generate_text(self) -> str:
        return self.format(self.generate())

    def format(self, state: dict[str, Any]) -> str:
        lines = [
            f"Map size: {state['map_width']}x{state['map_height']}",
            f"Turn: {state['turn']}/{state['max_turns']}",
            f"Max actions: {state['max_actions']}",
            "",
            "Feature locations:",
        ]

        for f in state["features"]:
            x, y = f["position"]
            attr = self._fmt_attrs(f["attrs"])
            lines.append(f"({x}, {y}) {f['owner']} {f['kind']} {{{attr}}}")

        return "\n".join(lines)

    # =========================================================
    # Scenario Builders
    # =========================================================

    def _base_layout(self):
        """Generate anchor positions (base-centered layout)."""

        base_x = self.rng.randint(3, MAP_SIZE - 4)
        base_y = self.rng.randint(3, MAP_SIZE - 4)

        enemy_x = base_x + self.rng.choice([-6, 6])
        enemy_y = base_y + self.rng.choice([-6, 6])

        enemy_x = max(0, min(MAP_SIZE - 1, enemy_x))
        enemy_y = max(0, min(MAP_SIZE - 1, enemy_y))

        return (base_x, base_y), (enemy_x, enemy_y)

    def _scenario_start(self):
        base, enemy = self._base_layout()

        return self._build_state(
            turn=self.rng.randint(0, 40),
            features=[
                self._resource_near(base),
                self._resource_far(),
                self._base("Ally", base, self.rng.randint(2, 4)),
                self._base("Enemy", enemy, 4),
                self._worker("Ally", self._near(base), "idling"),
            ],
        )

    def _scenario_two_workers_no_barracks(self):
        base, enemy = self._base_layout()

        return self._build_state(
            turn=self.rng.randint(40, 150),
            features=[
                self._resource_near(base),
                self._resource_far(),
                self._base("Ally", base, self.rng.randint(2, 7)),
                self._base("Enemy", enemy, 4),
                self._worker("Ally", self._near(base), self._maybe_harvest()),
                self._worker("Ally", self._near(base), self._maybe_move()),
            ],
        )

    def _scenario_many_workers_no_barracks(self):
        base, enemy = self._base_layout()

        workers = [
            self._worker("Ally", self._near(base), self._maybe_harvest())
            for _ in range(5)
        ]

        return self._build_state(
            turn=self.rng.randint(80, 200),
            features=[
                self._resource_near(base),
                self._resource_far(),
                self._base("Ally", base, self.rng.randint(4, 8)),
                self._base("Enemy", enemy, 4),
                *workers,
            ],
        )

    def _scenario_enemy_barracks(self):
        base, enemy = self._base_layout()

        return self._build_state(
            turn=self.rng.randint(100, 250),
            features=[
                self._resource_near(base),
                self._resource_far(),
                self._base("Ally", base, self.rng.randint(4, 8)),
                self._base("Enemy", enemy, 4),
                self._barracks("Enemy", self._near(enemy)),
                self._worker("Ally", self._near(base), "idling"),
                self._worker("Ally", self._near(base), self._maybe_move()),
            ],
        )

    def _scenario_ally_barracks(self):
        base, enemy = self._base_layout()

        return self._build_state(
            turn=self.rng.randint(150, 300),
            features=[
                self._resource_near(base),
                self._resource_far(),
                self._base("Ally", base, self.rng.randint(2, 6)),
                self._barracks("Ally", self._near(base)),
                self._base("Enemy", enemy, 4),
                self._worker("Ally", self._near(base), self._maybe_harvest()),
                self._worker("Ally", self._near(base), "idling"),
            ],
        )

    def _scenario_midgame(self):
        base, enemy = self._base_layout()

        return self._build_state(
            turn=self.rng.randint(250, 700),
            features=[
                self._resource_near(base),
                self._resource_far(),
                self._base("Ally", base, self.rng.randint(3, 8)),
                self._barracks("Ally", self._near(base)),
                self._base("Enemy", enemy, 4),
                self._worker("Ally", self._near(base), self._maybe_harvest()),
                self._worker("Ally", self._near(base), self._maybe_harvest()),
                self._unit("Ally", "Light Unit", self._near(base), "idling"),
                self._unit("Ally", "Light Unit", self._near(base), f"attacking location {enemy}"),
                self._unit("Enemy", "Worker Unit", self._near(enemy), "idling"),
            ],
        )

    # =========================================================
    # Helpers
    # =========================================================

    def _build_state(self, turn: int, features: list[dict]) -> dict:
        return {
            "map_width": MAP_SIZE,
            "map_height": MAP_SIZE,
            "turn": turn,
            "max_turns": 5000,
            "max_actions": min(6, len([f for f in features if f["owner"] == "Ally"])),
            "features": features,
        }

    def _near(self, pos):
        x, y = pos
        return (
            max(0, min(MAP_SIZE - 1, x + self.rng.randint(-2, 2))),
            max(0, min(MAP_SIZE - 1, y + self.rng.randint(-2, 2))),
        )

    def _resource_near(self, base):
        return {
            "position": list(self._near(base)),
            "owner": "Neutral",
            "kind": "Resource Node",
            "attrs": {"resources": self.rng.randint(8, 20)},
        }

    def _resource_far(self):
        return {
            "position": [self.rng.randint(0, 15), self.rng.randint(0, 15)],
            "owner": "Neutral",
            "kind": "Resource Node",
            "attrs": {"resources": self.rng.randint(8, 20)},
        }

    def _base(self, owner, pos, resources):
        return {
            "position": list(pos),
            "owner": owner,
            "kind": "Base Unit",
            "attrs": {
                "resources": resources,
                "current_action": self.rng.choice(["idling", "producing unit at (0,0)"]),
                "HP": HP["Base Unit"],
            },
        }

    def _barracks(self, owner, pos):
        return {
            "position": list(pos),
            "owner": owner,
            "kind": "Barracks Unit",
            "attrs": {
                "current_action": self.rng.choice(["idling", "producing unit at (0,0)"]),
                "HP": HP["Barracks Unit"],
            },
        }

    def _worker(self, owner, pos, action):
        return self._unit(owner, "Worker Unit", pos, action)

    def _unit(self, owner, kind, pos, action):
        return {
            "position": list(pos),
            "owner": owner,
            "kind": kind,
            "attrs": {
                "current_action": action,
                "HP": HP[kind],
            },
        }

    def _maybe_harvest(self):
        return self.rng.choice([
            "idling",
            "harvesting from (0,0)",
            "moving to (0,0)",
        ])

    def _maybe_move(self):
        return self.rng.choice([
            "idling",
            "moving to (0,0)",
        ])

    def _fmt_attrs(self, attrs):
        out = []
        for key in ATTR_ORDER:
            if key not in attrs:
                continue
            v = attrs[key]
            if isinstance(v, str):
                out.append(f'{key}="{v}"')
            else:
                out.append(f"{key}={v}")
        return ", ".join(out)


if __name__ == "__main__":
    g = StateGenerator(seed=0)
    for _ in range(5):
        print(g.generate_text())
        print("\n" + "-" * 60 + "\n")