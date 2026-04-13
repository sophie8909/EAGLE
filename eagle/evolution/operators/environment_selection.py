"""Environment selection methods for the genetic algorithm."""

from __future__ import annotations
from ...utils.individual import Individual
from ...utils.fitness_utils import fitness_key

class EnvironmentSelection:
    """Legacy survivor-selection helpers for the single-objective GA path."""

    @staticmethod
    def sort_by_fitness(population: list[Individual]) -> list[Individual]:
        """Sort individuals by the project's lexicographic fitness key."""
        sorted_population = sorted(population, key=lambda ind: fitness_key(ind.fitness), reverse=True)
        return sorted_population

    @staticmethod
    def elitism_selection(current_population: list[Individual], new_population: list[Individual], population_size: int) -> list[Individual]:
        """Keep the best `population_size` individuals from parents plus offspring."""
        combined_population = current_population + new_population
        combined_population = EnvironmentSelection.sort_by_fitness(combined_population)
        selected_population = combined_population[:population_size]
        return selected_population


