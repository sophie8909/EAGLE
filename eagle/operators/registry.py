"""Plugin-style registry for evolutionary operators."""

from __future__ import annotations

from eagle.operators.base import (
    BaseCrossover,
    BaseMutation,
    BaseParentSelection,
    BaseReplacement,
)
from eagle.operators.crossover.uniform import UniformCrossover
from eagle.operators.mutation.bitmask_flip import BitmaskFlipMutation
from eagle.operators.mutation.component_strategy_mutation import ComponentStrategyMutation
from eagle.operators.parent_selection.ga_fitness_tournament import GAFitnessTournamentSelection
from eagle.operators.parent_selection.nsga2_tournament import NSGA2TournamentSelection
from eagle.operators.parent_selection.random_selection import RandomParentSelection
from eagle.operators.parent_selection.tournament_selection import TournamentParentSelection
from eagle.operators.replacement.ga_fitness_elitism import GAFitnessElitism
from eagle.operators.replacement.nsga2_environmental import NSGA2EnvironmentalSelection
from eagle.operators.replacement.pool_replacement import PoolReplacement


OPERATOR_REGISTRY: dict[str, dict[str, type]] = {
    "mutation": {
        "component_mutation": ComponentStrategyMutation,
        "component_strategy_mutation": ComponentStrategyMutation,
        "bitmask_flip": BitmaskFlipMutation,
    },
    "crossover": {
        "uniform": UniformCrossover,
        "component_uniform": UniformCrossover,
    },
    "parent_selection": {
        "random": RandomParentSelection,
        "tournament": TournamentParentSelection,
        "ga_fitness_tournament": GAFitnessTournamentSelection,
        "nsga2_tournament": NSGA2TournamentSelection,
    },
    "replacement": {
        "elitism": PoolReplacement,
        "pool_replacement": PoolReplacement,
        "ga_fitness_elitism": GAFitnessElitism,
        "nsga2_environmental": NSGA2EnvironmentalSelection,
    },
}

_EXPECTED_BASES = {
    "mutation": BaseMutation,
    "crossover": BaseCrossover,
    "parent_selection": BaseParentSelection,
    "replacement": BaseReplacement,
}


def _normalize_name(name: str) -> str:
    """Normalize config names without changing their public spelling rules."""
    return str(name).strip().lower().replace("-", "_")


def get_operator(
    operator_type: str,
    operator_name: str,
    config: dict | None = None,
):
    """Instantiate one registered operator by type and name."""
    normalized_type = _normalize_name(operator_type)
    if normalized_type not in OPERATOR_REGISTRY:
        known_types = ", ".join(sorted(OPERATOR_REGISTRY))
        raise ValueError(
            f"Unknown operator type {operator_type!r}. Known types: {known_types}."
        )

    normalized_name = _normalize_name(operator_name)
    operators = OPERATOR_REGISTRY[normalized_type]
    if normalized_name not in operators:
        known_names = ", ".join(sorted(operators))
        raise ValueError(
            f"Unknown {normalized_type} operator {operator_name!r}. "
            f"Known names: {known_names}."
        )

    operator_cls = operators[normalized_name]
    expected_base = _EXPECTED_BASES[normalized_type]
    if not issubclass(operator_cls, expected_base):
        raise ValueError(
            f"Registered {normalized_type} operator {normalized_name!r} "
            f"must inherit {expected_base.__name__}."
        )

    return operator_cls(config)
