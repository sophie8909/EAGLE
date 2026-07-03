"""Parent selection methods for the genetic algorithm."""

from __future__ import annotations


class ParentSelection:
    """Parent-selection helpers shared by component-evolution algorithms."""

    @staticmethod
    def tournament_selection(population: list, fitnesses: list, tournament_size: int) -> int:
        """Return the index of the best candidate from a random tournament sample."""
        import random
        tournament_indices = random.sample(range(len(population)), tournament_size)
        return max(tournament_indices, key=lambda idx: fitnesses[idx])
    
    @staticmethod
    def random_selection(population: list) -> int:
        """Return the index of a uniformly sampled parent."""
        import random
        return random.randint(0, len(population) - 1)


