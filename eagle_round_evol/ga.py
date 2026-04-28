"""
Single-objective GA implementation for round-level prompt evolution.
"""

from __future__ import annotations

import random
from typing import List

from eagle.config import EAConfig
from eagle.utils.component_pool import ComponentPool

from .basic_ea import EA
from .evaluator import Evaluator
from .individual import Individual
from .mutation import Mutation


def _normalize_single_objective_fitness(fitness) -> list[float]:
    """Normalize any fitness payload into a fixed-width single-objective vector."""
    if fitness is None:
        return [0.0]
    if isinstance(fitness, (int, float)):
        return [float(fitness)]
    try:
        iterable = list(fitness)
    except TypeError:
        return [0.0]
    if not iterable:
        return [0.0]
    try:
        return [float(iterable[0])]
    except (TypeError, ValueError):
        return [0.0]


class GA(EA):
    """Single-objective GA using score-only selection and survival."""

    def __init__(
        self,
        config: EAConfig,
        component_pool: ComponentPool,
        opponent_list: List[str],
    ):
        super().__init__(config, component_pool, opponent_list)

    def _fitness0(self, individual: Individual) -> float:
        return _normalize_single_objective_fitness(individual.fitness)[0]

    def _better_parent(self, ind1: Individual, ind2: Individual) -> Individual:
        """Binary tournament winner by fitness[0], ties broken randomly."""
        f1 = self._fitness0(ind1)
        f2 = self._fitness0(ind2)
        if f1 > f2:
            return ind1
        if f2 > f1:
            return ind2
        return random.choice([ind1, ind2])

    def select_parent(self) -> Individual:
        """Select one parent by binary tournament on fitness[0]."""
        if len(self.population) < 2:
            raise ValueError("GA requires at least two individuals for parent selection.")
        a, b = random.sample(self.population, 2)
        return self._better_parent(a, b)

    def select_parents(self) -> List[Individual]:
        """Select two parents by independent binary tournaments on fitness[0]."""
        if len(self.population) < 2:
            raise ValueError("GA requires at least two individuals for parent selection.")
        return self.select_parent(), self.select_parent()

    def select_next_generation(
        self,
        population: List[Individual],
        offspring: List[Individual],
    ) -> List[Individual]:
        """Select survivors by fitness[0] descending from parents+offspring."""
        combined_population = population + offspring
        ranked = sorted(combined_population, key=self._fitness0, reverse=True)
        return ranked[: self.config.population_size]

    def _sample_reproduction_operator(self) -> str:
        """Sample crossover, mutation, or reflection from config weights."""
        weights = self.config.reproduction_operator_weights()
        if not weights:
            return "mutation"
        operators = list(weights.keys())
        probabilities = [weights[operator] for operator in operators]
        return random.choices(operators, weights=probabilities, k=1)[0]

    def _generate_offspring(self, generation: int) -> List[Individual]:
        """Create one full offspring population without evaluating it yet."""
        offspring: List[Individual] = []
        target_count = self.config.population_size

        while len(offspring) < target_count:
            operator = self._sample_reproduction_operator()
            if operator == "crossover":
                parent1, parent2 = self.select_parents()
                child = self.crossover(parent1, parent2)
            elif operator == "mutation":
                parent = self.select_parent()
                print(f"[Generation {generation + 1}] selected parent for mutation: id={parent.id} {parent}", flush=True)
                child = self.mutate(parent)
                setattr(child, "_mutation_parent_fitness0", self._fitness0(parent))
                print(f"[Generation {generation + 1}] created child from mutation: id={child.id} {child}", flush=True)
            elif operator == "reflection":
                child = self.reflect(self.select_parent())
            else:
                raise ValueError(f"Unsupported reproduction operator: {operator}")

            setattr(child, "_reproduction_operator", operator)
            offspring.append(child)
            print(
                f"[Generation {generation + 1}] generated offspring "
                f"{len(offspring)}/{target_count} via {operator}",
                flush=True,
            )

        return offspring[:target_count]

    def _update_mutation_component_feedback(self, child: Individual) -> None:
        """Feed mutation-mode success/failure back to adaptive roulette."""
        if getattr(child, "_reproduction_operator", None) != "mutation":
            return

        metadata = dict(getattr(child, "mutation_metadata", {}) or {})
        mutation_mode = metadata.get("mutation_mode")
        parent_fitness0 = getattr(child, "_mutation_parent_fitness0", None)
        if parent_fitness0 is None:
            return

        improved = self._fitness0(child) > float(parent_fitness0)
        Mutation.update_mutation_component_feedback(mutation_mode, improved)

    def run(self) -> list:
        """Main single-objective GA loop."""
        log_dir = self.create_log_folder()
        evaluator = Evaluator(self.component_pool, self.config)

        self._evaluate_initial_population(evaluator)

        for generation in range(self.config.num_generations):
            print(
                f"[Generation {generation + 1}/{self.config.num_generations}] start",
                flush=True,
            )

            offspring = self._generate_offspring(generation)
            print(
                f"[Generation {generation + 1}] generated offspring ready: {len(offspring)}",
                flush=True,
            )

            for index, child in enumerate(offspring):
                print(
                    f"[Generation {generation + 1}] round evaluation "
                    f"{index + 1}/{len(offspring)} id={child.id}",
                    flush=True,
                )
                evaluator.evaluate(child, generation=generation)
                print(
                    f"[Generation {generation + 1}] round result "
                    f"id={child.id} fitness={child.fitness}",
                    flush=True,
                )
                self._update_mutation_component_feedback(child)

            print(
                f"[Generation {generation + 1}] selecting survivors",
                flush=True,
            )
            self.population = self.select_next_generation(self.population, offspring)

            best_individual = max(self.population, key=self._fitness0)
            self.log_single_objective_generation(log_dir, generation, best_individual)
            self.save_component_pool(log_dir)
            self.current_generation = generation
            self.print_population_snapshot(f"generation {generation + 1} survivors")
            print(
                f"[Generation {generation + 1}] logged",
                flush=True,
            )

        return self.population
