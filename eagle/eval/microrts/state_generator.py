"""Random MicroRTS state snippets for prompt training examples."""

from __future__ import annotations

import random
from typing import Any


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
    """Generate legal-looking static MicroRTS feature-state text."""

    def __init__(self, seed: int | None = None, map_size: int = 8) -> None:
        """Create one deterministic or random state generator."""
        self.rng = random.Random(seed)
        self.map_size = int(map_size)

    def generate(self) -> dict[str, Any]:
        """Generate one random MicroRTS state payload."""
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
        """Generate one random state and return prompt-ready text."""
        return self.format(self.generate())

    def format(self, state: dict[str, Any]) -> str:
        """Format one generated state using the prompt example schema."""
        lines = [
            f"Map size: {state['map_width']}x{state['map_height']}",
            f"Turn: {state['turn']}/{state['max_turns']}",
            f"Max actions: {state['max_actions']}",
            "",
            "Feature locations:",
        ]
        for feature in state["features"]:
            x, y = feature["position"]
            attr = self._fmt_attrs(feature["attrs"])
            lines.append(f"({x}, {y}) {feature['owner']} {feature['kind']} {{{attr}}}")
        return "\n".join(lines)

    def _base_layout(self) -> tuple[tuple[int, int], tuple[int, int]]:
        margin = 2 if self.map_size <= 8 else 3
        base_x = self.rng.randint(margin, self.map_size - margin - 1)
        base_y = self.rng.randint(margin, self.map_size - margin - 1)
        offset = max(3, self.map_size // 2)
        enemy_x = max(0, min(self.map_size - 1, base_x + self.rng.choice([-offset, offset])))
        enemy_y = max(0, min(self.map_size - 1, base_y + self.rng.choice([-offset, offset])))
        return (base_x, base_y), (enemy_x, enemy_y)

    def _scenario_start(self) -> dict[str, Any]:
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

    def _scenario_two_workers_no_barracks(self) -> dict[str, Any]:
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

    def _scenario_many_workers_no_barracks(self) -> dict[str, Any]:
        base, enemy = self._base_layout()
        workers = [self._worker("Ally", self._near(base), self._maybe_harvest()) for _ in range(5)]
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

    def _scenario_enemy_barracks(self) -> dict[str, Any]:
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

    def _scenario_ally_barracks(self) -> dict[str, Any]:
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

    def _scenario_midgame(self) -> dict[str, Any]:
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

    def _build_state(self, turn: int, features: list[dict[str, Any]]) -> dict[str, Any]:
        ally_count = len([feature for feature in features if feature["owner"] == "Ally"])
        return {
            "map_width": self.map_size,
            "map_height": self.map_size,
            "turn": turn,
            "max_turns": 5000,
            "max_actions": min(6, ally_count),
            "features": features,
        }

    def _near(self, pos: tuple[int, int]) -> tuple[int, int]:
        x, y = pos
        return (
            max(0, min(self.map_size - 1, x + self.rng.randint(-2, 2))),
            max(0, min(self.map_size - 1, y + self.rng.randint(-2, 2))),
        )

    def _resource_near(self, base: tuple[int, int]) -> dict[str, Any]:
        return {
            "position": list(self._near(base)),
            "owner": "Neutral",
            "kind": "Resource Node",
            "attrs": {"resources": self.rng.randint(8, 20)},
        }

    def _resource_far(self) -> dict[str, Any]:
        return {
            "position": [self.rng.randint(0, self.map_size - 1), self.rng.randint(0, self.map_size - 1)],
            "owner": "Neutral",
            "kind": "Resource Node",
            "attrs": {"resources": self.rng.randint(8, 20)},
        }

    def _base(self, owner: str, pos: tuple[int, int], resources: int) -> dict[str, Any]:
        return {
            "position": list(pos),
            "owner": owner,
            "kind": "Base Unit",
            "attrs": {
                "resources": resources,
                "current_action": self._maybe_train_or_produce(pos),
                "HP": HP["Base Unit"],
            },
        }

    def _barracks(self, owner: str, pos: tuple[int, int]) -> dict[str, Any]:
        return {
            "position": list(pos),
            "owner": owner,
            "kind": "Barracks Unit",
            "attrs": {
                "current_action": self._maybe_train_or_produce(pos),
                "HP": HP["Barracks Unit"],
            },
        }

    def _worker(self, owner: str, pos: tuple[int, int], action: str) -> dict[str, Any]:
        return self._unit(owner, "Worker Unit", pos, action)

    def _unit(self, owner: str, kind: str, pos: tuple[int, int], action: str) -> dict[str, Any]:
        return {
            "position": list(pos),
            "owner": owner,
            "kind": kind,
            "attrs": {
                "current_action": action,
                "HP": HP[kind],
            },
        }

    def _maybe_harvest(self) -> str:
        return self.rng.choice(
            [
                "idling",
                "harvesting right from adjacent_cell=(0,0)",
                "moving right toward next_cell=(0,0)",
                "building Barracks at (0,0)",
            ]
        )

    def _maybe_move(self) -> str:
        return self.rng.choice(["idling", "moving right toward next_cell=(0,0)"])

    def _maybe_train_or_produce(self, pos: tuple[int, int]) -> str:
        x, y = pos
        adjacent = (min(self.map_size - 1, x + 1), y)
        return self.rng.choice(
            [
                "idling",
                "training Worker",
                f"producing Worker right at adjacent_cell={self._fmt_pos(adjacent)}",
            ]
        )

    def _fmt_pos(self, pos: tuple[int, int]) -> str:
        return f"({pos[0]},{pos[1]})"

    def _fmt_attrs(self, attrs: dict[str, Any]) -> str:
        out = []
        for key in ATTR_ORDER:
            if key not in attrs:
                continue
            value = attrs[key]
            if isinstance(value, str):
                out.append(f'{key}="{value}"')
            else:
                out.append(f"{key}={value}")
        return ", ".join(out)
