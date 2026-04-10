"""
Steady-State NSGA-II implementation for multi-objective optimization.
"""

from __future__ import annotations

import random
from typing import Any, List, Tuple

from ..tools.component_pool import ComponentPool
from ..config import EAConfig
from ..tools.individual import Individual
from ..operator.reflection import Reflection
from .nsga2 import NSGA2
from ..tools.profiler import timer


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
        """Initialize the steady-state NSGA-II variant with the shared runtime state."""
        super().__init__(config, component_pool, opponent_list)

    def _generate_single_offspring(
        self,
        generation_stats: dict[str, float],
    ) -> Individual:
        """Generate exactly one offspring through one sampled reproduction operator."""
        child_stats: dict[str, float] = {}
        with timer("offspring_generation_time", generation_stats):
            child = self.generate_candidate_child(generation_stats, child_stats)
        return child

    def sample_reproduction_operator(
        self,
        config: EAConfig,
        rng: random.Random,
    ) -> str:
        """Sample one reproduction operator from the validated config distribution."""
        weights = config.reproduction_operator_weights()
        if not weights:
            raise ValueError("No reproduction operators are enabled in reproduction_operator_probs.")
        operators = list(weights.keys())
        probabilities = [weights[operator] for operator in operators]
        return rng.choices(operators, weights=probabilities, k=1)[0]

    def generate_candidate_child(
        self,
        generation_stats: dict[str, float],
        child_stats: dict[str, float],
    ) -> Individual:
        """Sample one operator and generate exactly one candidate child."""
        operator = self.sample_reproduction_operator(self.config, random)
        return self.generate_child_with_operator(
            operator=operator,
            generation_stats=generation_stats,
            child_stats=child_stats,
        )

    def generate_child_with_operator(
        self,
        *,
        operator: str,
        generation_stats: dict[str, float],
        child_stats: dict[str, float],
    ) -> Individual:
        """Dispatch to the operator-specific child generator and attach metadata."""
        if operator == "crossover":
            child, metadata = self.generate_child_by_crossover(generation_stats, child_stats)
        elif operator == "mutation":
            child, metadata = self.generate_child_by_mutation(generation_stats, child_stats)
        elif operator == "reflection":
            child, metadata = self.generate_child_by_reflection(generation_stats, child_stats)
        else:
            raise ValueError(f"Unsupported reproduction operator: {operator!r}")

        child.operator_profile = {
            "operator_type": operator,
            "parent_ids": metadata.get("parent_ids", []),
            "crossover_mode": metadata.get("crossover_mode"),
            "mutation_mode": metadata.get("mutation_mode"),
            "reflection_context_used_fallback": metadata.get("reflection_context_used_fallback", False),
            "reflection_fell_back_to_mutation": metadata.get("reflection_fell_back_to_mutation", False),
            "rewritten_components": metadata.get("rewritten_components", []),
            "crossover_time": child_stats.get("crossover_time", 0.0),
            "mutation_time": child_stats.get("mutation_time", 0.0),
            "reflection_time": child_stats.get("reflection_time", 0.0),
            "EA_operator_time": child_stats.get("crossover_time", 0.0)
            + child_stats.get("mutation_time", 0.0)
            + child_stats.get("reflection_time", 0.0),
            "ea_llm_call_time": getattr(child, "ea_llm_call_time", 0.0),
        }
        return child

    def generate_child_by_crossover(
        self,
        generation_stats: dict[str, float],
        child_stats: dict[str, float],
    ) -> tuple[Individual, dict[str, Any]]:
        """Generate one child with the configured crossover operator."""
        with timer("parent_selection_time", generation_stats):
            parent1, parent2 = self.select_parents()
        with timer("crossover_time", child_stats):
            child = self.crossover(parent1, parent2)
        return child, {
            "parent_ids": [getattr(parent1, "id", None), getattr(parent2, "id", None)],
            "crossover_mode": self.config.crossover_mode,
        }

    def generate_child_by_mutation(
        self,
        generation_stats: dict[str, float],
        child_stats: dict[str, float],
        parent: Individual | None = None,
    ) -> tuple[Individual, dict[str, Any]]:
        """Generate one child with a standalone single-parent mutation operator."""
        selected_parent = parent
        if selected_parent is None:
            with timer("parent_selection_time", generation_stats):
                selected_parent = self.select_parent()

        with timer("mutation_time", child_stats):
            child = self.mutate(selected_parent)
        mutation_metadata = getattr(child, "mutation_metadata", {}) or {}
        return child, {
            "parent_ids": [getattr(selected_parent, "id", None)],
            "mutation_mode": mutation_metadata.get("mutation_mode"),
            "rewritten_components": mutation_metadata.get("changed_components", []),
        }

    def build_reflection_context(
        self,
        parent: Individual,
    ) -> dict[str, Any]:
        """Build one compact reflection context from the parent's last real evaluation."""
        last_real_evaluation = getattr(parent, "last_real_evaluation", None)
        if isinstance(last_real_evaluation, dict):
            reflection_context = last_real_evaluation.get("reflection_context")
            if isinstance(reflection_context, dict):
                return dict(reflection_context)

        fitness = parent.fitness if isinstance(parent.fitness, list) else None
        return Reflection.safe_fallback_context(fitness=fitness)

    def generate_child_by_reflection(
        self,
        generation_stats: dict[str, float],
        child_stats: dict[str, float],
    ) -> tuple[Individual, dict[str, Any]]:
        """Generate one child with the conservative feedback-guided reflection operator."""
        with timer("parent_selection_time", generation_stats):
            parent = self.select_parent()

        reflection_context = self.build_reflection_context(parent)
        if reflection_context.get("missing_data"):
            print(
                f"Reflection context missing for parent {getattr(parent, 'id', None)}; "
                "falling back to mutation."
            )
            child, metadata = self.generate_child_by_mutation(
                generation_stats,
                child_stats,
                parent=parent,
            )
            metadata["reflection_context_used_fallback"] = True
            metadata["reflection_fell_back_to_mutation"] = True
            return child, metadata

        with timer("reflection_time", child_stats):
            child, reflection_metadata = Reflection.apply_reflection(
                parent,
                self.component_pool,
                self.config,
                reflection_context,
            )

        return child, {
            "parent_ids": [getattr(parent, "id", None)],
            "rewritten_components": reflection_metadata.get("rewritten_components", []),
            "reflection_context_used_fallback": reflection_metadata.get(
                "reflection_context_used_fallback",
                False,
            ),
            "reflection_fell_back_to_mutation": False,
        }

    def _generate_candidate_offspring_batch(
        self,
        generation: int,
        generation_stats: dict[str, float],
        candidates: List[Individual] | None = None,
    ) -> List[Individual]:
        """
        Generate and surrogate-evaluate the candidate child batch for one
        steady-state generation.

        Checkpoint contract:
        - phase="generation_surrogate" means candidate generation is in progress
        - offspring stores all surrogate-evaluated candidate children so far
        """
        candidates = list(candidates or [])
        target_count = max(1, self.config.steady_state_surrogate_offspring_count)

        while len(candidates) < target_count:
            child = self._generate_single_offspring(generation_stats)
            with timer("offspring_evaluation_time", generation_stats):
                self.surrogate_evaluation(child, generation=generation)
            candidates.append(child)
            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_surrogate",
                    generation=generation,
                    offspring=candidates,
                    meta={"evaluated_candidate_count": len(candidates)},
                )
            )

        return candidates

    def _select_best_candidate_by_game_round(self, candidates: List[Individual]) -> Individual:
        """Pick the candidate with the highest surrogate game-round score."""
        if not candidates:
            raise ValueError("steady-state candidate batch cannot be empty")

        selection_metric = str(
            getattr(self.config, "steady_state_surrogate_selection_metric", "game_round_score")
        ).strip().lower()
        if selection_metric != "game_round_score":
            raise ValueError(
                "steady_state_surrogate_selection_metric currently only supports "
                "'game_round_score'"
            )

        return max(
            candidates,
            key=lambda ind: ind.fitness[1] if ind.fitness and len(ind.fitness) > 1 else float("-inf"),
        )

    def run(self) -> list[Individual]:
        """
        Main steady-state NSGA-II optimization loop.

        In steady-state mode, one generation means exactly one update:
        1. generates multiple candidate children,
        2. surrogate-evaluates them,
        3. picks the highest game-round-score candidate,
        4. runs real evaluation on that chosen child,
        5. immediately inserts it into the population.
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
            # Phase 1: one steady-state generation = one single-child update.
            generation_stats: dict[str, float] = {}
            same_generation_checkpoint = checkpoint.get("generation") == generation
            checkpoint_phase = checkpoint.get("phase")
            candidate_count_for_checkpoint = checkpoint.get("meta", {}).get("candidate_count", 1)

            if same_generation_checkpoint and checkpoint_phase == "generation_step":
                # Resume point: the child for this generation was already
                # generated, evaluated, and inserted into the population.
                offspring = self.deserialize_population(checkpoint.get("offspring"))
            elif same_generation_checkpoint and checkpoint_phase == "generation_real_eval":
                # Resume point: the best child was already chosen and fully
                # real-evaluated, but replacement/logging had not completed yet.
                offspring = self.deserialize_population(checkpoint.get("offspring"))
            else:
                if same_generation_checkpoint and checkpoint_phase == "generation_surrogate":
                    candidate_offspring = self.deserialize_population(checkpoint.get("offspring"))
                else:
                    candidate_offspring = []

                # Step 1: generate multiple candidates and use surrogate evaluation
                # to rank them by game_round_score.
                candidate_offspring = self._generate_candidate_offspring_batch(
                    generation,
                    generation_stats,
                    candidates=candidate_offspring,
                )
                candidate_count_for_checkpoint = len(candidate_offspring)
                child = self._select_best_candidate_by_game_round(candidate_offspring)
                offspring = [child]

                # Step 2: only the best surrogate candidate receives real evaluation.
                with timer("offspring_evaluation_time", generation_stats):
                    self.real_evaluation(
                        child,
                        random.choice(self.opponent_list),
                        generation=generation,
                    )

                # Checkpoint meaning:
                # - phase="generation_real_eval" means the chosen child already
                #   finished real evaluation
                # - resuming from here must not call real_evaluation again
                self.save_checkpoint(
                    self.build_checkpoint_state(
                        phase="generation_real_eval",
                        generation=generation,
                        population=self.population,
                        offspring=offspring,
                        meta={
                            "candidate_count": candidate_count_for_checkpoint,
                            "selected_child_id": getattr(child, "id", None),
                        },
                    )
                )

                # Step 3: immediate steady-state replacement.

            if not (same_generation_checkpoint and checkpoint_phase == "generation_step"):
                # Run NSGA-II environmental selection over parents + one child,
                # then keep only the survivor population.
                with timer("survivor_selection_time", generation_stats):
                    self.population = self.select_next_generation(self.population, offspring)

                # Checkpoint meaning:
                # - phase="generation_step" means the child for this generation
                #   was already generated/evaluated/inserted
                # - population is already the post-replacement survivor set
                # - offspring contains exactly the chosen child that survived
                #   the surrogate-candidate selection stage
                self.save_checkpoint(
                    self.build_checkpoint_state(
                        phase="generation_step",
                        generation=generation,
                        population=self.population,
                        offspring=offspring,
                        meta={
                            "completed_births": 1,
                            "candidate_count": candidate_count_for_checkpoint,
                        },
                    )
                )

            # Phase 2: build survivor fronts from the current population for
            # logging and convergence checks. On resume from generation_step,
            # this finishes the remainder of the generation without replaying
            # the same child update.
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
