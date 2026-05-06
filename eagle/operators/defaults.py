"""Register built-in component operators."""

from __future__ import annotations

from ..core.registry import (
    CROSSOVER_OPERATORS,
    ENVIRONMENTAL_SELECTION,
    MUTATION_OPERATORS,
    PARENT_SELECTION,
)
from ..evolution.component.environment_selection import EnvironmentSelection
from ..evolution.component.parent_selection import ParentSelection
from ..operators.component.crossover import Crossover as ComponentCrossover
from ..operators.component.mutation import Mutation as ComponentMutation


def register_default_operators() -> None:
    """Populate registries with the built-in operator functions."""
    CROSSOVER_OPERATORS.register("uniform", ComponentCrossover.uniform_crossover)
    CROSSOVER_OPERATORS.register("component_uniform", ComponentCrossover.uniform_crossover)
    MUTATION_OPERATORS.register("component_mutation", ComponentMutation.mutate_individual)
    MUTATION_OPERATORS.register("component_strategy_mutation", ComponentMutation.mutate_individual)
    MUTATION_OPERATORS.register("component_bitmask_flip", ComponentMutation.apply_enabled_bit_flip)
    PARENT_SELECTION.register("random", ParentSelection.random_selection)
    PARENT_SELECTION.register("tournament", ParentSelection.tournament_selection)
    ENVIRONMENTAL_SELECTION.register("elitism", EnvironmentSelection.elitism_selection)
