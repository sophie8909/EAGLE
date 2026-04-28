"""
NSGA-II implementation for multi-objective optimization of prompt components.
"""

from __future__ import annotations

from inspect import signature
import math
import random
from typing import List, Tuple

from eagle.config import EAConfig
from eagle.utils.component_pool import ComponentPool

from .basic_ea import EA
from .evaluator import Evaluator
from .individual import Individual


def _normalize_two_objective_fitness(fitness) -> list[float]:
    """Normalize any fitness payload into a fixed-width two-objective vector."""
    if fitness is None:
        return [0.0, 0.0]
    if isinstance(fitness, (int, float)):
        return [float(fitness), 0.0]
    values: list[float] = []
    try:
        iterable = list(fitness)
    except TypeError:
        return [0.0, 0.0]
    for value in iterable[:2]:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            values.append(0.0)
    while len(values) < 2:
        values.append(0.0)
    return values


class NSGA2(EA):
    """
    NSGA-II algorithm for multi-objective evolutionary optimization.

    This implementation assumes:
    1. Every individual has a `fitness` attribute that is a sequence of objective values.
    2. Larger fitness values are better for every objective.
       If one or more objectives are minimization objectives in your project,
       you should convert them before storing them in `individual.fitness`,
       or modify `dominates()` accordingly.
    """

    def __init__(
        self,
        config: EAConfig,
        component_pool: ComponentPool,
        opponent_list: List[str],
    ):
        """Initialize NSGA-II using the shared EA base implementation."""
        super().__init__(config, component_pool, opponent_list)

    def _assign_rank_and_crowding(self, population: List[Individual]) -> List[List[Individual]]:
        """Compute Pareto fronts and annotate individuals with rank/crowding."""
        fronts = self.fast_non_dominated_sort(population)
        for rank, front in enumerate(fronts):
            self.calculate_crowding_distance(front)
            for ind in front:
                setattr(ind, "pareto_rank", rank)
        return fronts

    def _sort_by_round_fitness(self, population: List[Individual]) -> List[Individual]:
        """Order offspring by round legality first, then strategy alignment."""
        return sorted(
            population,
            key=lambda ind: (
                ind.fitness[0] if ind.fitness and len(ind.fitness) > 0 else float("-inf"),
                ind.fitness[1] if ind.fitness and len(ind.fitness) > 1 else float("-inf"),
            ),
            reverse=True,
        )

    def _better_parent(self, ind1: Individual, ind2: Individual) -> Individual:
        """Break tournament ties using rank, crowding distance, then dominance."""
        rank1 = getattr(ind1, "pareto_rank", float("inf"))
        rank2 = getattr(ind2, "pareto_rank", float("inf"))
        if rank1 != rank2:
            return ind1 if rank1 < rank2 else ind2

        crowd1 = getattr(ind1, "crowding_distance", 0.0)
        crowd2 = getattr(ind2, "crowding_distance", 0.0)
        if crowd1 != crowd2:
            return ind1 if crowd1 > crowd2 else ind2

        if self.dominates(ind1, ind2):
            return ind1
        if self.dominates(ind2, ind1):
            return ind2
        return random.choice([ind1, ind2])

    def select_parents(self) -> List[Individual]:
        """Sample two parents with NSGA-II's tournament selection policy."""
        if len(self.population) < 2:
            raise ValueError("NSGA-II requires at least two individuals for parent selection.")

        self._assign_rank_and_crowding(self.population)

        def _pick_one() -> Individual:
            """Run one binary tournament under the current NSGA-II ranking state."""
            a, b = random.sample(self.population, 2)
            return self._better_parent(a, b)

        return _pick_one(), _pick_one()

    def select_parent(self) -> Individual:
        """Sample one parent with NSGA-II's tournament selection policy."""
        if len(self.population) < 2:
            raise ValueError("NSGA-II requires at least two individuals for parent selection.")

        self._assign_rank_and_crowding(self.population)
        a, b = random.sample(self.population, 2)
        return self._better_parent(a, b)

    def dominates(self, ind1: Individual, ind2: Individual) -> bool:
        """
        Return True if ind1 Pareto-dominates ind2.

        For maximization problems, ind1 dominates ind2 if:
        - ind1 is no worse than ind2 in all objectives, and
        - ind1 is strictly better than ind2 in at least one objective.
        """
        if ind1.fitness is None or ind2.fitness is None:
            raise ValueError("Both individuals must be evaluated before dominance comparison.")

        better_in_at_least_one = False
        fitness1 = _normalize_two_objective_fitness(ind1.fitness)
        fitness2 = _normalize_two_objective_fitness(ind2.fitness)

        for f1, f2 in zip(fitness1, fitness2):
            if f1 < f2:
                return False
            if f1 > f2:
                better_in_at_least_one = True

        return better_in_at_least_one

    def fast_non_dominated_sort(self, population: List[Individual]) -> List[List[Individual]]:
        """
        Sort the population into Pareto fronts using the NSGA-II fast non-dominated sorting algorithm.

        Returns:
            A list of fronts, where each front is a list of individuals.
            Front 0 is the best non-dominated front.
        """
        if not population:
            return []

        population_size = len(population)
        domination_count = [0] * population_size
        dominated_solutions = [[] for _ in range(population_size)]
        fronts: List[List[Individual]] = []

        # Compute pairwise domination relationships.
        for i in range(population_size):
            for j in range(i + 1, population_size):
                if self.dominates(population[i], population[j]):
                    dominated_solutions[i].append(j)
                    domination_count[j] += 1
                elif self.dominates(population[j], population[i]):
                    dominated_solutions[j].append(i)
                    domination_count[i] += 1

        # The first front contains all non-dominated individuals.
        current_front_indices = [i for i in range(population_size) if domination_count[i] == 0]
        if current_front_indices:
            fronts.append([population[i] for i in current_front_indices])

        # Iteratively construct the remaining fronts.
        while current_front_indices:
            next_front_indices = []

            for i in current_front_indices:
                for j in dominated_solutions[i]:
                    domination_count[j] -= 1
                    if domination_count[j] == 0:
                        next_front_indices.append(j)

            if next_front_indices:
                fronts.append([population[i] for i in next_front_indices])

            current_front_indices = next_front_indices

        return fronts

    def calculate_crowding_distance(self, front: List[Individual]) -> List[float]:
        """
        Calculate crowding distance for all individuals in one Pareto front.

        The crowding distance is a diversity estimate:
        - Larger distance means the individual lies in a less crowded region.
        - Boundary individuals are assigned infinity.

        This method also stores the result in each individual as `crowding_distance`
        for convenience during environmental selection.

        Returns:
            A list of crowding distances aligned with the order of `front`.
        """
        if not front:
            return []

        if len(front) == 1:
            setattr(front[0], "crowding_distance", float("inf"))
            return [float("inf")]

        if len(front) == 2:
            setattr(front[0], "crowding_distance", float("inf"))
            setattr(front[1], "crowding_distance", float("inf"))
            return [float("inf"), float("inf")]

        normalized_front = {ind: _normalize_two_objective_fitness(ind.fitness) for ind in front}
        num_objectives = len(next(iter(normalized_front.values())))
        distance_map = {ind: 0.0 for ind in front}

        # Compute distance objective by objective.
        for m in range(num_objectives):
            sorted_front = sorted(front, key=lambda ind: normalized_front[ind][m])

            # Boundary points are always preserved.
            distance_map[sorted_front[0]] = float("inf")
            distance_map[sorted_front[-1]] = float("inf")

            min_value = normalized_front[sorted_front[0]][m]
            max_value = normalized_front[sorted_front[-1]][m]
            denominator = max_value - min_value

            # If all individuals have the same value on this objective,
            # this objective contributes nothing to crowding distance.
            if denominator == 0:
                continue

            for i in range(1, len(sorted_front) - 1):
                # Keep infinity if the individual is already a boundary point
                # for another objective.
                if math.isinf(distance_map[sorted_front[i]]):
                    continue

                prev_value = normalized_front[sorted_front[i - 1]][m]
                next_value = normalized_front[sorted_front[i + 1]][m]

                distance_map[sorted_front[i]] += (next_value - prev_value) / denominator

        # Store the distances on the individuals.
        for ind in front:
            setattr(ind, "crowding_distance", distance_map[ind])

        # Return distances in the original front order.
        return [distance_map[ind] for ind in front]

    def select_next_generation(
        self,
        population: List[Individual],
        offspring: List[Individual],
    ) -> List[Individual]:
        """
        Select the next generation using NSGA-II environmental selection.

        Steps:
        1. Combine parent population and offspring.
        2. Perform non-dominated sorting.
        3. Add whole fronts until the next front would overflow the capacity.
        4. For the last accepted partial front, sort by crowding distance descending
           and keep the least crowded individuals.

        Args:
            population: Current parent population.
            offspring: Newly generated and evaluated offspring.

        Returns:
            The next generation with size `self.config.population_size`.
        """
        next_generation, _ = self._select_next_generation_with_fronts(population, offspring)
        return next_generation

    def _select_next_generation_with_fronts(
        self,
        population: List[Individual],
        offspring: List[Individual],
    ) -> tuple[List[Individual], List[List[Individual]]]:
        """
        Select the next generation and also return the resulting selected fronts.

        The returned fronts are already aligned with the survivor population, so
        callers that need fronts for logging or convergence checks can reuse them
        instead of sorting the survivor population again.
        """
        combined_population = population + offspring
        fronts = self.fast_non_dominated_sort(combined_population)

        next_generation: List[Individual] = []
        selected_fronts: List[List[Individual]] = []
        target_size = self.config.population_size

        for front in fronts:
            self.calculate_crowding_distance(front)

            # If the whole front fits, add all of it.
            if len(next_generation) + len(front) <= target_size:
                next_generation.extend(front)
                selected_fronts.append(list(front))
                continue

            # Otherwise, sort the front by crowding distance descending
            # and fill the remaining slots.
            remaining_slots = target_size - len(next_generation)
            sorted_front = sorted(
                front,
                key=lambda ind: getattr(ind, "crowding_distance", 0.0),
                reverse=True,
            )
            truncated_front = sorted_front[:remaining_slots]
            next_generation.extend(truncated_front)
            if truncated_front:
                selected_fronts.append(truncated_front)
            break

        return next_generation, selected_fronts

    def _front_signature(self, front: List[Individual]) -> List[Tuple]:
        """
        Create a comparable signature for a Pareto front.

        This is used for a simple convergence check across generations.
        We sort the components tuples so the order inside the front does not matter.
        """
        signature = []
        for ind in front:
            sig = tuple(sorted(ind.component_indices.items()))
            signature.append(sig)

        signature.sort()
        return signature

    
    def _generate_offspring(self, generation: int) -> List[Individual]:
        """Create one full offspring population without evaluating it yet."""
        offspring: List[Individual] = []
        target_count = self.config.population_size

        # Generational phase A: build the entire offspring population first.
        while len(offspring) < target_count:
            operator = self._sample_reproduction_operator()
            if operator == "crossover":
                parent1, parent2 = self.select_parents()
                child = self.crossover(parent1, parent2)
            elif operator == "mutation":
                parent = self.select_parent()
                print(f"[Generation {generation + 1}] selected parent for mutation: id={parent.id} {parent}", flush=True)
                child = self.mutate(parent)
                print(f"[Generation {generation + 1}] created child from mutation: id={child.id} {child}", flush=True)
            elif operator == "reflection":
                child = self.reflect(self.select_parent())
            else:
                raise ValueError(f"Unsupported reproduction operator: {operator}")

            offspring.append(child)
            print(
                f"[Generation {generation + 1}] generated offspring "
                f"{len(offspring)}/{target_count} via {operator}",
                flush=True,
            )

        return offspring[:target_count]

    def _sample_reproduction_operator(self) -> str:
        """Sample crossover, mutation, or round reflection from config weights."""
        weights = self.config.reproduction_operator_weights()
        if not weights:
            return "mutation"
        operators = list(weights.keys())
        probabilities = [weights[operator] for operator in operators]
        return random.choices(operators, weights=probabilities, k=1)[0]

    def _log_generation(
        self,
        generation: int,
        offspring: List[Individual],
        pareto_fronts: List[List[Individual]],
        log_dir: str,
    ) -> None:
        """Write Pareto-front snapshots and the component pool."""
        self.log_multi_objective_generation(log_dir, generation, pareto_fronts)
        self.save_component_pool(log_dir)
        self.current_generation = generation

    def _has_converged(
        self,
        pareto_fronts: List[List[Individual]],
        past_front_signatures: List[List[Tuple]],
    ) -> bool:
        """Detect simple convergence by checking whether the first front has stabilized."""
        if not pareto_fronts:
            return False

        current_signature = self._front_signature(pareto_fronts[0])
        past_front_signatures.append(current_signature)

        if len(past_front_signatures) > self.config.convergence_generations:
            past_front_signatures.pop(0)

        return (
            len(past_front_signatures) == self.config.convergence_generations
            and all(sig == past_front_signatures[0] for sig in past_front_signatures)
        )

    def run(self) -> list:
        """
        Main NSGA-II optimization loop.

        Workflow:
        1. Evaluate the initial population.
        2. Repeatedly generate offspring through selection, crossover, and mutation.
        3. Evaluate offspring.
        4. Perform environmental selection with non-dominated sorting and crowding distance.
        5. Log the Pareto fronts for each generation.
        6. Stop early if the best front remains unchanged for several generations.

        Returns:
            The final population.
        """
        log_dir = self.create_log_folder()
        evaluator = Evaluator(self.component_pool, self.config)

        self._evaluate_initial_population(evaluator)

        past_front_signatures: List[List[Tuple]] = []

        for generation in range(self.config.num_generations):
            print(
                f"[Generation {generation + 1}/{self.config.num_generations}] start",
                flush=True,
            )
            # Phase 1: build the full offspring batch.
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

            # Phase 2: combine parent population and completed offspring batch.
            # Pareto fronts here are computed on the union, before survivor truncation.
            combined_population = self.population + offspring
            pareto_fronts = self._assign_rank_and_crowding(combined_population)

            # Phase 3: one environmental-selection step creates the next generation.
            print(
                f"[Generation {generation + 1}] selecting survivors",
                flush=True,
            )
            self.population = self.select_next_generation(self.population, offspring)

            self._log_generation(generation, offspring, pareto_fronts, log_dir)
            self.print_population_snapshot(f"generation {generation + 1} survivors")
            print(
                f"[Generation {generation + 1}] logged",
                flush=True,
            )

            # Phase 4: simple convergence check on the current first Pareto front.
            if self._has_converged(pareto_fronts, past_front_signatures):
                print(
                    f"[Generation {generation + 1}] convergence reached; stopping early",
                    flush=True,
                )
                break

        return self.population
