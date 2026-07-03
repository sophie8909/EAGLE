"""GA single-objective replacement plugin."""

from __future__ import annotations

from eagle.operators.base import BaseReplacement


class GAFitnessElitism(BaseReplacement):
    """Keep the best individuals by GA fitness[0]."""

    name = "ga_fitness_elitism"

    def __call__(self, ea, population, offspring):
        """Return the next GA population."""
        combined_population = population + offspring
        ranked = sorted(combined_population, key=ea._fitness0, reverse=True)
        return ranked[: ea.config.population_size]
