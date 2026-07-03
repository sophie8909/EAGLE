"""GA single-objective parent-selection plugin."""

from __future__ import annotations

import random

from eagle.operators.base import BaseParentSelection


class GAFitnessTournamentSelection(BaseParentSelection):
    """Select parents by binary tournament on fitness[0]."""

    name = "ga_fitness_tournament"

    def __call__(self, ea, count: int = 1):
        """Return one parent or a tuple of parents."""
        selected = tuple(self._pick_one(ea) for _ in range(count))
        return selected[0] if count == 1 else selected

    def _pick_one(self, ea):
        """Run one binary tournament using GA's current fitness comparison."""
        if len(ea.population) < 2:
            raise ValueError("GA requires at least two individuals for parent selection.")
        a, b = random.sample(ea.population, 2)
        return ea._better_parent(a, b)
