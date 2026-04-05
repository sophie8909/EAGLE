"""Environment selection methods for the genetic algorithm."""

from __future__ import annotations
from .individual import Individual
from .fitness_utils import fitness_key

class EnvironmentSelection:
    @staticmethod
    def sort_by_fitness(population: list[Individual]) -> list[Individual]:
        # Sort the population based on fitness values in descending order
        sorted_population = sorted(population, key=lambda ind: fitness_key(ind.fitness), reverse=True)
        return sorted_population

    @staticmethod
    def elitism_selection(current_population: list[Individual], new_population: list[Individual], population_size: int) -> list[Individual]:
        # Combine current and new populations, sort by fitness, and select the top individuals
        combined_population = current_population + new_population
        # Assuming we have a way to evaluate fitness for each individual, we would sort them here
        combined_population = EnvironmentSelection.sort_by_fitness(combined_population)
        # For demonstration, we'll just return the first 'population_size' individuals
        selected_population = combined_population[:population_size]
        return selected_population
