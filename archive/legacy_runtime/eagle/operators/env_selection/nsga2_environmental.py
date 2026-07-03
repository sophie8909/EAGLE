"""NSGA-II environmental replacement plugin."""

from __future__ import annotations

from eagle.operators.base import BaseReplacement


class NSGA2EnvironmentalSelection(BaseReplacement):
    """Select survivors using non-dominated sorting and crowding distance."""

    name = "nsga2_environmental"

    def __call__(self, ea, population, offspring):
        """Return the next NSGA-II population."""
        combined_population = population + offspring
        fronts = ea.fast_non_dominated_sort(combined_population)

        next_generation = []
        target_size = ea.config.population_size

        for front in fronts:
            ea.calculate_crowding_distance(front)
            if len(next_generation) + len(front) <= target_size:
                next_generation.extend(front)
                continue

            remaining_slots = target_size - len(next_generation)
            sorted_front = sorted(
                front,
                key=lambda ind: getattr(ind, "crowding_distance", 0.0),
                reverse=True,
            )
            next_generation.extend(sorted_front[:remaining_slots])
            break

        return next_generation
