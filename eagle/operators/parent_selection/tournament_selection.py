"""Generic tournament parent-selection plugin."""

from __future__ import annotations

import random

from eagle.operators.base import BaseParentSelection


class TournamentParentSelection(BaseParentSelection):
    """Select parents by lexicographic fitness tournament."""

    name = "tournament"

    def __call__(self, ea, count: int = 1):
        """Return one parent or a tuple of parents."""
        selected = tuple(self._pick_one(ea) for _ in range(count))
        return selected[0] if count == 1 else selected

    def _pick_one(self, ea):
        """Run one tournament using the configured tournament size."""
        tournament_size = min(ea.config.tournament_size, len(ea.population))
        candidates = random.sample(ea.population, tournament_size)
        return max(candidates, key=lambda ind: ind.fitness if ind.fitness is not None else [0.0, 0.0])
