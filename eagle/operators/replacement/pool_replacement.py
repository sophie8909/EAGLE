"""Generic pool replacement plugin."""

from __future__ import annotations

from eagle.operators.base import BaseReplacement


class PoolReplacement(BaseReplacement):
    """Keep the lexicographically best individuals from parents plus offspring."""

    name = "pool_replacement"

    def __call__(self, ea, population, offspring):
        """Return the next population with the configured population size."""
        combined_population = population + offspring
        ranked = sorted(
            combined_population,
            key=lambda ind: ind.fitness if ind.fitness is not None else [],
            reverse=True,
        )
        return ranked[: ea.config.population_size]
