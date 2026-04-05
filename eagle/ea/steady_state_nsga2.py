"""
Steady-State NSGA-II implementation for multi-objective optimization.
"""

from __future__ import annotations

import random
from typing import List, Tuple

from .component_pool import ComponentPool
from .config import EAConfig
from .individual import Individual
from .nsga2 import NSGA2
from .profiler import timer


class SteadyStateNSGA2(NSGA2):
    """
    Steady-State NSGA-II.

    The variation and ranking logic stay aligned with the existing NSGA-II
    implementation, but survivor selection happens after each offspring is
    considered instead of after replacing the whole generation at once.
    """

    def __init__(
        self,
        config: EAConfig,
        component_pool: ComponentPool,
        opponent_list: List[str],
    ):
        super().__init__(config, component_pool, opponent_list)

    def _select_steady_state_survivors(
        self,
        population: List[Individual],
        child: Individual,
    ) -> List[Individual]:
        """Insert one child and immediately trim back to population size."""
        return self.select_next_generation(population, [child])

    def _steady_state_replace(
        self,
        candidate_order: List[Individual],
        generation: int,
        generation_stats: dict[str, float],
        start_index: int = 0,
    ) -> None:
        """Apply steady-state replacement one offspring at a time."""
        for index, child in enumerate(candidate_order):
            if index < start_index:
                continue

            with timer("survivor_selection_time", generation_stats):
                self.population = self._select_steady_state_survivors(self.population, child)

            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_replace",
                    generation=generation,
                    offspring=candidate_order,
                    meta={
                        "candidate_order_ids": [ind.id for ind in candidate_order],
                        "next_replace_index": index + 1,
                    },
                )
            )

    def run(self) -> list[Individual]:
        """
        Main steady-state NSGA-II optimization loop.

        Workflow:
        1. Evaluate the initial population.
        2. Generate one batch of offspring using NSGA-II parent selection.
        3. Surrogate-evaluate the batch and spend the configured real-eval budget.
        4. Insert offspring one by one with immediate NSGA-II survivor selection.
        5. Log Pareto fronts of the current population after each generation.
        """
        log_dir = self.create_log_folder()
        checkpoint = self.load_checkpoint()

        if checkpoint:
            self.population = self.deserialize_population(checkpoint.get("population"))
            self.current_generation = checkpoint.get("generation", 0)
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
            self._evaluate_initial_population()
            checkpoint = self.build_checkpoint_state(
                phase="generation_complete",
                generation=-1,
                meta={"completed_generation": -1},
            )
            self.save_checkpoint(checkpoint)

        last_5_front_signatures: List[List[Tuple]] = []
        start_generation = checkpoint.get("generation", 0) + (
            1 if checkpoint.get("phase") == "generation_complete" else 0
        )

        for generation in range(start_generation, self.config.num_generations):
            generation_stats: dict[str, float] = {}
            same_generation_checkpoint = checkpoint.get("generation") == generation
            checkpoint_phase = checkpoint.get("phase")

            if same_generation_checkpoint and checkpoint_phase in {
                "generation_surrogate",
                "generation_real_eval",
                "generation_replace",
            }:
                offspring = self.deserialize_population(checkpoint.get("offspring"))
                offspring = self._resume_offspring_generation(generation, generation_stats, offspring)
            else:
                offspring = self._generate_offspring(generation, generation_stats)

            candidate_order = self._rank_offspring_for_real_evaluation(offspring)
            checkpoint_candidate_ids = (
                checkpoint.get("meta", {}).get("candidate_order_ids", [])
                if same_generation_checkpoint
                else []
            )
            if checkpoint_candidate_ids:
                child_by_id = {child.id: child for child in offspring}
                candidate_order = [
                    child_by_id[ind_id] for ind_id in checkpoint_candidate_ids if ind_id in child_by_id
                ]
                remaining_children = [
                    child for child in offspring if child.id not in checkpoint_candidate_ids
                ]
                candidate_order.extend(remaining_children)

            start_real_eval_index = (
                checkpoint.get("meta", {}).get("next_real_eval_index", 0)
                if same_generation_checkpoint
                else 0
            )
            if checkpoint_phase == "generation_replace":
                start_real_eval_index = self.config.real_eval_count(self.config.population_size)

            self._real_evaluate_ranked_offspring(
                candidate_order,
                generation,
                generation_stats,
                start_index=start_real_eval_index,
            )

            start_replace_index = (
                checkpoint.get("meta", {}).get("next_replace_index", 0)
                if same_generation_checkpoint and checkpoint_phase == "generation_replace"
                else 0
            )
            self._steady_state_replace(
                candidate_order,
                generation,
                generation_stats,
                start_index=start_replace_index,
            )

            pareto_fronts = self._assign_rank_and_crowding(self.population)
            self._log_generation(generation, generation_stats, candidate_order, pareto_fronts, log_dir)
            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_complete",
                    generation=generation,
                    meta={"completed_generation": generation},
                )
            )

            if self._has_converged(pareto_fronts, last_5_front_signatures):
                break

            checkpoint = self.build_checkpoint_state(
                phase="generation_complete",
                generation=generation,
                meta={"completed_generation": generation},
            )

        return self.population
