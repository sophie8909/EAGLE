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

    This variant keeps NSGA-II's Pareto ranking and crowding-distance logic,
    but performs variation and replacement one child at a time.
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

    def _generate_single_offspring(
        self,
        generation: int,
        generation_stats: dict[str, float],
    ) -> Individual:
        """Generate exactly one offspring."""
        # Steady-state step A: select two parents from the current population.
        with timer("parent_selection_time", generation_stats):
            parent1, parent2 = self.select_parents()

        child_stats: dict[str, float] = {}
        # Steady-state step B: create exactly one child via crossover + mutation.
        with timer("offspring_generation_time", generation_stats):
            with timer("crossover_time", child_stats):
                child = self.crossover(parent1, parent2)
            with timer("mutation_time", child_stats):
                child = self.mutate(child)

        child.operator_profile = {
            "crossover_time": child_stats.get("crossover_time", 0.0),
            "mutation_time": child_stats.get("mutation_time", 0.0),
            "EA_operator_time": child_stats.get("crossover_time", 0.0)
            + child_stats.get("mutation_time", 0.0),
            "ea_llm_call_time": getattr(child, "ea_llm_call_time", 0.0),
        }

        return child

    def run(self) -> list[Individual]:
        """
        Main steady-state NSGA-II optimization loop.

        One outer generation is treated as a block of steady-state updates.
        Inside that block, the algorithm repeatedly:
        1. selects parents,
        2. generates one child,
        3. runs real evaluation on that child,
        4. immediately inserts it into the population.
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
        start_generation = checkpoint.get("generation", 0) + (
            1 if checkpoint.get("phase") == "generation_complete" else 0
        )

        for generation in range(start_generation, self.config.num_generations):
            # Phase 1: one outer "generation" in steady-state mode is a block of
            # repeated single-child birth/evaluation/replacement updates.
            generation_stats: dict[str, float] = {}
            offspring: List[Individual] = []
            start_birth_index = 0

            # Phase 1a: resume from the middle of the steady-state birth loop.
            if checkpoint.get("generation") == generation and checkpoint.get("phase") == "generation_step":
                offspring = self.deserialize_population(checkpoint.get("offspring"))
                start_birth_index = checkpoint.get("meta", {}).get(
                    "completed_births",
                    len(offspring),
                )

            for birth_index in range(start_birth_index, self.config.population_size):
                # Step 1: generate exactly one offspring from the current population.
                child = self._generate_single_offspring(generation, generation_stats)

                # Step 2: steady-state mode uses full real evaluation for every child.
                with timer("offspring_evaluation_time", generation_stats):
                    self.real_evaluation(
                        child,
                        random.choice(self.opponent_list),
                        generation=generation,
                    )

                offspring.append(child)

                # Step 3: immediate steady-state replacement.
                # Unlike generational NSGA-II, this happens after every child.
                with timer("survivor_selection_time", generation_stats):
                    self.population = self._select_steady_state_survivors(self.population, child)

                # Checkpoint meaning:
                # - phase="generation_step" means we are inside the current
                #   steady-state birth loop
                # - offspring stores all children already created in this block
                # - completed_births tells us which birth index to resume from
                self.save_checkpoint(
                    self.build_checkpoint_state(
                        phase="generation_step",
                        generation=generation,
                        offspring=offspring,
                        meta={
                            "completed_births": birth_index + 1,
                        },
                    )
                )

            # Phase 2: after all steady-state updates in this outer generation,
            # rebuild Pareto fronts only for logging / convergence checking.
            pareto_fronts = self._assign_rank_and_crowding(self.population)
            self._log_generation(generation, generation_stats, offspring, pareto_fronts, log_dir)

            # Phase 3: mark this outer generation as fully completed.
            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_complete",
                    generation=generation,
                    meta={"completed_generation": generation},
                )
            )

            # Phase 4: simple convergence check on the current first Pareto front.
            if self._has_converged(pareto_fronts, last_5_front_signatures):
                break

            checkpoint = self.build_checkpoint_state(
                phase="generation_complete",
                generation=generation,
                meta={"completed_generation": generation},
            )

        return self.population
