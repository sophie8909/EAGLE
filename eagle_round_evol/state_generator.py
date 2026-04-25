# state_generator.py

import random


# MAP_SIZES = [4, 8, 10, 12, 16, 24]
MAP_SIZES = [16]

UNIT_STATS = {
    "Worker": {"HP": 1},
    "Light": {"HP": 4},
    "Heavy": {"HP": 8},
    "Ranged": {"HP": 3},
    "Base": {"HP": 10},
    "Barracks": {"HP": 5},
}

UNIT_TYPES = list(UNIT_STATS.keys())
ATTR_ORDER = ["resources", "current_action", "HP"]


class StateGenerator:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def generate(self) -> dict:
        size = self.rng.choice(MAP_SIZES)

        r = self.rng.randint(1, 3)
        e = self.rng.randint(1, 5)
        a = self.rng.randint(1, 3)

        used_positions = set()
        features = []
        resource_positions = []

        for _ in range(r):
            x, y = self._random_position(used_positions, size)
            resource_positions.append((x, y))
            features.append({
                "position": [x, y],
                "owner": "Neutral",
                "kind": "Resource Node",
                "attrs": {
                    "resources": self.rng.randint(1, 20),
                },
            })

        enemy_units = [
            self._random_unit("Enemy", used_positions, resource_positions, [], size)
            for _ in range(e)
        ]
        enemy_positions = [tuple(u["position"]) for u in enemy_units]

        ally_units = [
            self._random_unit("Ally", used_positions, resource_positions, enemy_positions, size)
            for _ in range(a)
        ]
        ally_positions = [tuple(u["position"]) for u in ally_units]

        for u in enemy_units:
            self._update_action(u, resource_positions, ally_positions, size)

        features.extend(enemy_units)
        features.extend(ally_units)

        return {
            "map_width": size,
            "map_height": size,
            "turn": self.rng.randint(0, 5000),
            "max_turns": 5000,
            "max_actions": a,
            "features": features,
        }

    def generate_text(self) -> str:
        return self.format(self.generate())

    def format(self, state: dict) -> str:
        lines = [
            f"Map size: {state['map_width']}x{state['map_height']}",
            f"Turn: {state['turn']}/{state['max_turns']}",
            f"Max actions: {state['max_actions']}",
            "",
            "Feature locations:",
        ]

        for f in self._sort(state["features"]):
            x, y = f["position"]
            attr = self._fmt_attrs(f["attrs"])
            lines.append(f"({x}, {y}) {f['owner']} {f['kind']} {{{attr}}}")

        return "\n".join(lines)

    def _random_position(self, used: set[tuple[int, int]], size: int) -> tuple[int, int]:
        while True:
            pos = (
                self.rng.randint(0, size - 1),
                self.rng.randint(0, size - 1),
            )
            if pos not in used:
                used.add(pos)
                return pos

    def _move(self) -> str:
        return "moving to (0,0)"

    def _harvest(self, resources: list[tuple[int, int]]) -> str:
        x, y = self.rng.choice(resources)
        return f"harvesting from ({x},{y})"

    def _attack(self, targets: list[tuple[int, int]]) -> str:
        x, y = self.rng.choice(targets)
        return f"attacking location ({x},{y})"

    def _random_unit(
        self,
        owner: str,
        used: set[tuple[int, int]],
        resources: list[tuple[int, int]],
        targets: list[tuple[int, int]],
        size: int,
    ) -> dict:
        unit_type = self.rng.choice(UNIT_TYPES)
        x, y = self._random_position(used, size)

        return {
            "position": [x, y],
            "owner": owner,
            "kind": f"{unit_type} Unit",
            "attrs": {
                "current_action": self._choose_action(unit_type, resources, targets),
                "HP": UNIT_STATS[unit_type]["HP"],
                **({"resources": self.rng.randint(0, 20)} if unit_type == "Base" else {}),
            },
        }

    def _update_action(
        self,
        unit: dict,
        resources: list[tuple[int, int]],
        targets: list[tuple[int, int]],
        size: int,
    ) -> None:
        unit_type = unit["kind"].replace(" Unit", "")
        unit["attrs"]["current_action"] = self._choose_action(unit_type, resources, targets)

    def _choose_action(
        self,
        unit_type: str,
        resources: list[tuple[int, int]],
        targets: list[tuple[int, int]],
    ) -> str:
        roll = self.rng.random()

        if unit_type == "Worker":
            if resources and roll < 0.35:
                return self._harvest(resources)
            if targets and roll < 0.55:
                return self._attack(targets)
            if roll < 0.80:
                return self._move()
            return "idling"

        if unit_type in ["Light", "Heavy", "Ranged"]:
            if targets and roll < 0.60:
                return self._attack(targets)
            if roll < 0.85:
                return self._move()
            return "idling"

        if unit_type in ["Base", "Barracks"]:
            return "producing unit at (0,0)" if roll < 0.50 else "idling"

        return "idling"

    def _sort(self, features: list[dict]) -> list[dict]:
        def key(f: dict) -> tuple[int, int, int]:
            owner_priority = {
                "Neutral": 0,
                "Ally": 1,
                "Enemy": 2,
            }[f["owner"]]

            x, y = f["position"]
            return owner_priority, x, y

        return sorted(features, key=key)

    def _fmt_attrs(self, attrs: dict) -> str:
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


if __name__ == "__main__":
    generator = StateGenerator(seed=0)
    print(generator.generate_text())