"""
NSGA-II implementation for multi-objective optimization of prompt components.
"""

from __future__ import annotations

import math
import random
from typing import List, Tuple

from .basic_ea import EA
from .component_pool import ComponentPool
from .individual import Individual
from .config import EAConfig
from .profiler import build_base_record, timer, write_jsonl


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
        super().__init__(config, component_pool, opponent_list)

    def _assign_rank_and_crowding(self, population: List[Individual]) -> List[List[Individual]]:
        fronts = self.fast_non_dominated_sort(population)
        for rank, front in enumerate(fronts):
            self.calculate_crowding_distance(front)
            for ind in front:
                setattr(ind, "pareto_rank", rank)
        return fronts

    def _sort_by_game_round_score(self, population: List[Individual]) -> List[Individual]:
        return sorted(
            population,
            key=lambda ind: (
                ind.fitness[2] if ind.fitness and len(ind.fitness) > 2 else float("-inf"),
                ind.fitness[0] if ind.fitness and len(ind.fitness) > 0 else float("-inf"),
                ind.fitness[1] if ind.fitness and len(ind.fitness) > 1 else float("-inf"),
            ),
            reverse=True,
        )

    def _better_parent(self, ind1: Individual, ind2: Individual) -> Individual:
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
        if len(self.population) < 2:
            raise ValueError("NSGA-II requires at least two individuals for parent selection.")

        self._assign_rank_and_crowding(self.population)

        def _pick_one() -> Individual:
            a, b = random.sample(self.population, 2)
            return self._better_parent(a, b)

        return _pick_one(), _pick_one()

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

        for f1, f2 in zip(ind1.fitness, ind2.fitness):
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

        num_objectives = len(front[0].fitness)
        distance_map = {ind: 0.0 for ind in front}

        # Compute distance objective by objective.
        for m in range(num_objectives):
            sorted_front = sorted(front, key=lambda ind: ind.fitness[m])

            # Boundary points are always preserved.
            distance_map[sorted_front[0]] = float("inf")
            distance_map[sorted_front[-1]] = float("inf")

            min_value = sorted_front[0].fitness[m]
            max_value = sorted_front[-1].fitness[m]
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

                prev_value = sorted_front[i - 1].fitness[m]
                next_value = sorted_front[i + 1].fitness[m]

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
        combined_population = population + offspring
        fronts = self.fast_non_dominated_sort(combined_population)

        next_generation: List[Individual] = []
        target_size = self.config.population_size

        for front in fronts:
            self.calculate_crowding_distance(front)

            # If the whole front fits, add all of it.
            if len(next_generation) + len(front) <= target_size:
                next_generation.extend(front)
                continue

            # Otherwise, sort the front by crowding distance descending
            # and fill the remaining slots.
            remaining_slots = target_size - len(next_generation)
            sorted_front = sorted(
                front,
                key=lambda ind: getattr(ind, "crowding_distance", 0.0),
                reverse=True,
            )
            next_generation.extend(sorted_front[:remaining_slots])
            break

        return next_generation

    def _front_signature(self, front: List[Individual]) -> List[Tuple]:
        """
        Create a comparable signature for a Pareto front.

        This is used for a simple convergence check across generations.
        We sort the components tuples so the order inside the front does not matter.
        """
        signature: List[Tuple] = []
        for ind in front:
            # Backward compatibility: older code may have `components`
            if hasattr(ind, "components"):
                sig = tuple((comp.name, comp.value) for comp in ind.components)
            else:
                strategy_items = tuple(sorted((ind.strategy or {}).items()))
                sig = (
                    ("game_rule", getattr(ind, "game_rule", 0)),
                    ("strategy", strategy_items),
                )
            signature.append(sig)

        signature.sort()
        return signature

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
        log_dir = self.log_folder()


        # Evaluate the initial population before evolution starts.
        with timer("initial_population_evaluation_time", {}):
            for individual in self.population:
                self.real_evaluation(individual, random.choice(self.opponent_list), generation=-1)

        last_5_front_signatures: List[List[Tuple]] = []

        for generation in range(self.config.num_generations):
            generation_stats: dict[str, float] = {}
            offspring: List[Individual] = []

            while len(offspring) < self.config.population_size:
                with timer("parent_selection_time", generation_stats):
                    parent1, parent2 = self.select_parents()

                child_stats: dict[str, float] = {}
                with timer("offspring_generation_time", generation_stats):
                    with timer("crossover_time", child_stats):
                        child = self.crossover(parent1, parent2)
                    with timer("mutation_time", child_stats):
                        child = self.mutate(child)

                child.operator_profile = {
                    "crossover_time": child_stats.get("crossover_time", 0.0),
                    "mutation_time": child_stats.get("mutation_time", 0.0),
                    "EA_operator_time": child_stats.get("crossover_time", 0.0) + child_stats.get("mutation_time", 0.0),
                    "ea_llm_call_time": getattr(child, "ea_llm_call_time", 0.0),
                }
                # surrogate evaluation for the child before adding it to the offspring list
                with timer("offspring_evaluation_time", generation_stats):
                    self.surrogate_evaluation(child, generation=generation)
                offspring.extend([child])

            # Trim offspring in case we produced one extra pair.
            offspring = offspring[: self.config.population_size]

            # Rank offspring only before real evaluation.
            candidate_order = self._sort_by_game_round_score(offspring)

            # Real evaluation for the highest ranked offspring only, to save time.
            with timer("offspring_evaluation_time", generation_stats):
                cnt = 0
                for child in candidate_order:
                    self.real_evaluation(child, random.choice(self.opponent_list), generation=generation)
                    cnt += 1
                    if cnt >= self.config.population_size * self.config.real_eval_rate:
                        break

            # Combine parents and offspring after real evaluation, then compute fronts.
            combined_population = self.population + offspring
            pareto_fronts = self._assign_rank_and_crowding(combined_population)

            # Environmental selection for the next generation.
            with timer("survivor_selection_time", generation_stats):
                self.population = self.select_next_generation(self.population, offspring)

            generation_record = build_base_record(
                generation=generation,
                individual_id=None,
                record_type="generation",
            )
            generation_record.update(
                {
                    "generation_time": (
                        generation_stats.get("parent_selection_time", 0.0)
                        + generation_stats.get("offspring_generation_time", 0.0)
                        + generation_stats.get("offspring_evaluation_time", 0.0)
                        + generation_stats.get("survivor_selection_time", 0.0)
                    ),
                    "parent_selection_time": generation_stats.get("parent_selection_time", 0.0),
                    "offspring_generation_time": generation_stats.get("offspring_generation_time", 0.0),
                    "offspring_evaluation_time": generation_stats.get("offspring_evaluation_time", 0.0),
                    "survivor_selection_time": generation_stats.get("survivor_selection_time", 0.0),
                    "population_size": len(self.population),
                    "offspring_count": len(offspring),
                    "log_dir": log_dir,
                }
            )
            write_jsonl(generation_record, self.get_generation_profile_log_path())

            # Log the current generation's Pareto fronts.
            self.log_mo_generation(log_dir, generation, pareto_fronts)
            self.save_components(log_dir)
            self.current_generation = generation
            # Simple convergence check:
            # stop if the first Pareto front stays identical for 5 generations.
            if pareto_fronts:
                current_signature = self._front_signature(pareto_fronts[0])
                last_5_front_signatures.append(current_signature)

                if len(last_5_front_signatures) > 5:
                    last_5_front_signatures.pop(0)

                if (
                    len(last_5_front_signatures) == 5
                    and all(sig == last_5_front_signatures[0] for sig in last_5_front_signatures)
                ):
                    break

        return self.population
