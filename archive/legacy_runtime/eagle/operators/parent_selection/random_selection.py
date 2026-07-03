"""Random parent-selection plugin."""

from __future__ import annotations

import random

from eagle.operators.base import BaseParentSelection


class RandomParentSelection(BaseParentSelection):
    """Select parents uniformly at random from the current population."""

    name = "random"

    def __call__(self, ea, count: int = 1):
        """Return one parent or a tuple of parents."""
        selected = tuple(random.choice(ea.population) for _ in range(count))
        return selected[0] if count == 1 else selected
