"""
NSGA-II implementation for multi-objective optimization of prompt components.
"""

from __future__ import annotations

import math
import random
from typing import List, Tuple

from .basic_ea import EA
from ..tools.component_pool import ComponentPool
from ..tools.individual import Individual
from ..config import EAConfig
from ..tools.profiler import build_base_record, timer, write_jsonl


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

    def _sort_by_game_round_score(self, population: List[Individual]) -> List[Individual]:
        """Order offspring by the surrogate game-round objective before real evaluation."""
        # Before real evaluation, game_round surrogate information lives in the
        # second objective, so we rank offspring directly by that signal first.
        return sorted(
            population,
            key=lambda ind: (
                ind.fitness[1] if ind.fitness and len(ind.fitness) > 1 else float("-inf"),
                ind.fitness[0] if ind.fitness and len(ind.fitness) > 0 else float("-inf"),
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

    def _evaluate_initial_population(self) -> None:
        """Run full evaluation on the initial population before evolutionary steps."""
        with timer("initial_population_evaluation_time", {}):
            for index, individual in enumerate(self.population):
                self.real_evaluation(individual, random.choice(self.opponent_list), generation=-1)
                # Checkpoint meaning:
                # - phase="initial_population" means generation -1 is still
                #   being evaluated
                # - evaluated_initial_count tells resume() how many individuals
                #   were already fully real-evaluated
                self.save_checkpoint(
                    self.build_checkpoint_state(
                        phase="initial_population",
                        generation=-1,
                        meta={"evaluated_initial_count": index + 1},
                    )
                )

    def _generate_offspring(self, generation: int, generation_stats: dict[str, float]) -> List[Individual]:
        """Create and surrogate-evaluate one full offspring population."""
        offspring: List[Individual] = []

        # Generational phase A: build the entire offspring population first.
        while len(offspring) < self.config.population_size:
            with timer("parent_selection_time", generation_stats):
                parent1, parent2 = self.select_parents()

            child_stats: dict[str, float] = {}
            # Step A1: create one child from the current parent population.
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

            # Step A2: every child gets surrogate evaluation before any real eval.
            with timer("offspring_evaluation_time", generation_stats):
                self.surrogate_evaluation(child, generation=generation)
            offspring.append(child)

            # Checkpoint meaning:
            # - phase="generation_surrogate" means this generation is still in
            #   the batch-offspring construction stage
            # - offspring stores the children already surrogate-evaluated
            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_surrogate",
                    generation=generation,
                    offspring=offspring,
                    meta={"evaluated_offspring_count": len(offspring)},
                )
            )

        return offspring[: self.config.population_size]

    def _resume_offspring_generation(
        self,
        generation: int,
        generation_stats: dict[str, float],
        offspring: List[Individual],
    ) -> List[Individual]:
        """Continue offspring generation from a partially completed checkpoint."""
        # Resume point for phase="generation_surrogate".
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

            with timer("offspring_evaluation_time", generation_stats):
                self.surrogate_evaluation(child, generation=generation)
            offspring.append(child)

            # Keep the same checkpoint contract as _generate_offspring().
            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_surrogate",
                    generation=generation,
                    offspring=offspring,
                    meta={"evaluated_offspring_count": len(offspring)},
                )
            )
        return offspring[: self.config.population_size]

    def _rank_offspring_for_real_evaluation(self, offspring: List[Individual]) -> List[Individual]:
        """Rank offspring by surrogate game-round score for the real-eval budget."""
        return self._sort_by_game_round_score(offspring)

    def _real_evaluate_ranked_offspring(
        self,
        candidate_order: List[Individual],
        generation: int,
        generation_stats: dict[str, float],
        start_index: int = 0,
    ) -> None:
        """Spend the configured real-evaluation budget on the best-ranked offspring."""
        with timer("offspring_evaluation_time", generation_stats):
            real_eval_budget = self.config.real_eval_count(self.config.population_size)

            # Generational phase B: after all offspring exist, real-evaluate only
            # the top-ranked children under the configured budget.
            for index, child in enumerate(candidate_order):
                if index < start_index:
                    continue
                if index >= real_eval_budget:
                    break
                self.real_evaluation(child, random.choice(self.opponent_list), generation=generation)

                # Checkpoint meaning:
                # - phase="generation_real_eval" means offspring generation is
                #   done, but budgeted real evaluation is still in progress
                # - candidate_order_ids freezes the ranking order for resume()
                # - next_real_eval_index tells resume() which ranked child is next
                self.save_checkpoint(
                    self.build_checkpoint_state(
                        phase="generation_real_eval",
                        generation=generation,
                        offspring=candidate_order,
                        meta={
                            "candidate_order_ids": [ind.id for ind in candidate_order],
                            "next_real_eval_index": index + 1,
                            "real_eval_budget": real_eval_budget,
                        },
                    )
                )

    def _build_generation_record(
        self,
        generation: int,
        generation_stats: dict[str, float],
        offspring: List[Individual],
        log_dir: str,
    ) -> dict:
        """Build one generation-level profiling record for JSONL logging."""
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
                "population_real_history_reuse_initial_count": sum(
                    1
                    for ind in self.population
                    if getattr(ind, "evaluation_mode", None) == "real_history_reuse_initial"
                ),
                "offspring_real_history_reuse_initial_count": sum(
                    1
                    for ind in offspring
                    if getattr(ind, "evaluation_mode", None) == "real_history_reuse_initial"
                ),
                "log_dir": log_dir,
            }
        )
        return generation_record

    def _log_generation(
        self,
        generation: int,
        generation_stats: dict[str, float],
        offspring: List[Individual],
        pareto_fronts: List[List[Individual]],
        log_dir: str,
    ) -> None:
        """Write generation profiles, Pareto-front snapshots, and the component pool."""
        generation_record = self._build_generation_record(
            generation=generation,
            generation_stats=generation_stats,
            offspring=offspring,
            log_dir=log_dir,
        )
        write_jsonl(generation_record, self.get_generation_profile_log_path())
        self.log_multi_objective_generation(log_dir, generation, pareto_fronts)
        self.save_component_pool(log_dir)
        self.current_generation = generation

    def _has_converged(
        self,
        pareto_fronts: List[List[Individual]],
        last_5_front_signatures: List[List[Tuple]],
    ) -> bool:
        """Detect simple convergence by checking whether the first front has stabilized."""
        if not pareto_fronts:
            return False

        current_signature = self._front_signature(pareto_fronts[0])
        last_5_front_signatures.append(current_signature)

        if len(last_5_front_signatures) > 5:
            last_5_front_signatures.pop(0)

        return (
            len(last_5_front_signatures) == 5
            and all(sig == last_5_front_signatures[0] for sig in last_5_front_signatures)
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
        checkpoint = self.load_checkpoint()

        # Phase 0: restore runtime state if a checkpoint exists.
        if checkpoint:
            self.population = self.deserialize_population(checkpoint.get("population"))
            self.current_generation = checkpoint.get("generation", 0)

            # Phase 0a: recover an interrupted initial-population evaluation.
            if checkpoint.get("phase") == "initial_population":
                start_initial = checkpoint.get("meta", {}).get("evaluated_initial_count", 0)
                with timer("initial_population_evaluation_time", {}):
                    for index in range(start_initial, len(self.population)):
                        individual = self.population[index]
                        self.real_evaluation(individual, random.choice(self.opponent_list), generation=-1)
                        self.save_checkpoint(
                            self.build_checkpoint_state(
                                phase="initial_population",
                                generation=-1,
                                meta={"evaluated_initial_count": index + 1},
                            )
                        )
                checkpoint = self.build_checkpoint_state(
                    phase="generation_complete",
                    generation=-1,
                    meta={"completed_generation": -1},
                )
                self.save_checkpoint(checkpoint)
        else:
            # Phase 0b: fresh run; fully evaluate generation -1 before evolution starts.
            self._evaluate_initial_population()
            checkpoint = self.build_checkpoint_state(
                phase="generation_complete",
                generation=-1,
                meta={"completed_generation": -1},
            )
            self.save_checkpoint(checkpoint)

        last_5_front_signatures: List[List[Tuple]] = []

        start_generation = checkpoint.get("generation", 0) + (1 if checkpoint.get("phase") == "generation_complete" else 0)

        for generation in range(start_generation, self.config.num_generations):
            # Phase 1: build or resume the full surrogate-evaluated offspring batch.
            generation_stats: dict[str, float] = {}
            if checkpoint.get("generation") == generation and checkpoint.get("phase") in {"generation_surrogate", "generation_real_eval"}:
                offspring = self.deserialize_population(checkpoint.get("offspring"))
                offspring = self._resume_offspring_generation(generation, generation_stats, offspring)
            else:
                offspring = self._generate_offspring(generation, generation_stats)

            # Phase 2: rank offspring for budgeted real evaluation.
            candidate_order = self._rank_offspring_for_real_evaluation(offspring)
            checkpoint_candidate_ids = checkpoint.get("meta", {}).get("candidate_order_ids", []) if checkpoint.get("generation") == generation else []
            if checkpoint_candidate_ids:
                child_by_id = {child.id: child for child in offspring}
                candidate_order = [child_by_id[ind_id] for ind_id in checkpoint_candidate_ids if ind_id in child_by_id]
                remaining_children = [child for child in offspring if child.id not in checkpoint_candidate_ids]
                candidate_order.extend(remaining_children)

            # Phase 3: resume or execute the budgeted real-evaluation pass.
            start_real_eval_index = checkpoint.get("meta", {}).get("next_real_eval_index", 0) if checkpoint.get("generation") == generation else 0
            self._real_evaluate_ranked_offspring(candidate_order, generation, generation_stats, start_index=start_real_eval_index)

            # Phase 4: combine parent population and completed offspring batch.
            # Pareto fronts here are computed on the union, before survivor truncation.
            combined_population = self.population + offspring
            pareto_fronts = self._assign_rank_and_crowding(combined_population)

            # Phase 5: one environmental-selection step creates the next generation.
            with timer("survivor_selection_time", generation_stats):
                self.population = self.select_next_generation(self.population, offspring)

            self._log_generation(generation, generation_stats, offspring, pareto_fronts, log_dir)

            # Phase 6: mark the full generation as completed.
            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_complete",
                    generation=generation,
                    meta={"completed_generation": generation},
                )
            )

            # Phase 7: simple convergence check on the current first Pareto front.
            if self._has_converged(pareto_fronts, last_5_front_signatures):
                break

            checkpoint = self.build_checkpoint_state(
                phase="generation_complete",
                generation=generation,
                meta={"completed_generation": generation},
            )

        return self.population
