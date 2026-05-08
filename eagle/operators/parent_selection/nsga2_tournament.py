"""NSGA-II parent-selection plugin."""

from __future__ import annotations

import random

from eagle.operators.base import BaseParentSelection


class NSGA2TournamentSelection(BaseParentSelection):
    """Select parents by NSGA-II rank, crowding distance, and dominance."""

    name = "nsga2_tournament"

    def __call__(self, ea, count: int = 1):
        """Return one parent or a tuple of parents."""
        if len(ea.population) < 2:
            raise ValueError("NSGA-II requires at least two individuals for parent selection.")
        ea._assign_rank_and_crowding(ea.population)
        selected = tuple(self._pick_one(ea) for _ in range(count))
        return selected[0] if count == 1 else selected

    def _pick_one(self, ea):
        """Run one binary tournament under the current NSGA-II ranking state."""
        a, b = random.sample(ea.population, 2)
        return ea._better_parent(a, b)
