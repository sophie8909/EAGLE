"""MicroRTS bindings for generic component-evolution algorithms."""

from __future__ import annotations

import math
import random

from eagle.core.registry import ALGORITHMS, EVALUATORS
from eagle.objectives.aggregation import aggregate_fitness
from eagle.evolution.component.ga import GA
from eagle.evolution.component.nsga2 import NSGA2
from eagle.reflection.microrts.round_reflection import RoundReflection

from .full_game_evaluator import FullGameEvaluator
from .round_evaluator import Evaluator as RoundEvaluator


EVALUATORS.register("round", RoundEvaluator)
EVALUATORS.register("gameplay", FullGameEvaluator)


@ALGORITHMS.register("ga")
class MicroRTSGA(GA):
    """Single-objective component GA bound to full MicroRTS gameplay."""

    evaluator_factory = FullGameEvaluator
    reflection_operator = RoundReflection


@ALGORITHMS.register("nsga2")
class MicroRTSNSGA2(NSGA2):
    """NSGA-II component evolution bound to full MicroRTS gameplay."""

    evaluator_factory = FullGameEvaluator
    reflection_operator = RoundReflection


@ALGORITHMS.register("ga_surrogate")
class MicroRTSGASurrogate(GA):
    """GA that ranks mostly by surrogate scores and refreshes elites with gameplay."""

    evaluator_factory = FullGameEvaluator
    reflection_operator = RoundReflection

    def __init__(self, config, component_pool, opponent_list):
        super().__init__(config, component_pool, opponent_list)
        self.gameplay_elite_archive = []

    def _fitness0(self, individual) -> float:
        if hasattr(individual, "gameplay_score"):
            return float(getattr(individual, "gameplay_score"))
        if hasattr(individual, "surrogate_score"):
            return float(getattr(individual, "surrogate_score"))
        return super()._fitness0(individual)

    def select_parent(self):
        if self.gameplay_elite_archive and random.random() < float(self.config.archive_parent_ratio):
            return random.choice(self.gameplay_elite_archive)
        return super().select_parent()

    def _evaluate_initial_population(self, evaluator):
        for index, individual in enumerate(self.population):
            print(
                f"[Initial Population] surrogate evaluation {index + 1}/{len(self.population)}",
                flush=True,
            )
            self._evaluate_surrogate_individual(evaluator, individual, generation=-1)
        self._refresh_gameplay_archive(evaluator, self.population, generation=-1, force=True)
        print("[Initial Population] complete", flush=True)
        self.print_population_snapshot("initial population")
        self._log_initial_population_snapshot()

    def _evaluate_offspring(self, evaluator, offspring, generation: int) -> None:
        for index, child in enumerate(offspring):
            print(
                f"[Generation {generation + 1}] surrogate evaluation "
                f"{index + 1}/{len(offspring)} id={child.id}",
                flush=True,
            )
            self._evaluate_surrogate_individual(evaluator, child, generation=generation)
            print(
                f"[Generation {generation + 1}] surrogate result "
                f"id={child.id} surrogate_score={getattr(child, 'surrogate_score', None)}",
                flush=True,
            )
            self._update_mutation_component_feedback(child)
        if self._is_gameplay_refresh_generation(generation):
            self._refresh_gameplay_archive(evaluator, offspring, generation=generation)

    def _is_gameplay_refresh_generation(self, generation: int) -> bool:
        interval = max(1, int(self.config.gameplay_refresh_interval))
        return (int(generation) + 1) % interval == 0

    def _evaluate_surrogate_individual(self, evaluator, individual, *, generation: int | None) -> None:
        eval_result = evaluator.surrogate(
            individual,
            generation=generation,
            opponents=self.opponent_list or None,
        )
        fitness = aggregate_fitness(eval_result, self.config)
        individual.fitness = fitness
        individual.rendered_prompt = eval_result.get("prompt", getattr(individual, "rendered_prompt", ""))
        individual.evaluation_mode = "surrogate"
        individual.surrogate_score = super()._fitness0(individual)
        individual.last_surrogate_evaluation = {"eval_result": dict(eval_result)}

    def _refresh_gameplay_archive(self, evaluator, candidates, *, generation: int | None, force: bool = False) -> None:
        selected = self._top_surrogate_candidates(list(candidates), force=force)
        if not selected:
            return
        print(
            f"[GA Surrogate] gameplay refresh generation={generation} candidates={len(selected)}",
            flush=True,
        )
        for individual in selected:
            self._evaluate_individual(evaluator, individual, generation=generation)
            individual.gameplay_score = super()._fitness0(individual)
            individual.evaluation_mode = "gameplay"
            self._update_gameplay_archive(individual)

    def _top_surrogate_candidates(self, candidates, *, force: bool = False):
        if not candidates:
            return []
        ratio = 1.0 if force else float(self.config.surrogate_top_ratio)
        count = max(1, int(math.ceil(len(candidates) * ratio)))
        return sorted(
            candidates,
            key=lambda individual: float(getattr(individual, "surrogate_score", GA._fitness0(self, individual))),
            reverse=True,
        )[:count]

    def _update_gameplay_archive(self, individual) -> None:
        if not hasattr(individual, "gameplay_score"):
            return
        by_id = {existing.id: existing for existing in self.gameplay_elite_archive}
        by_id[individual.id] = individual
        archive = sorted(
            by_id.values(),
            key=lambda item: float(getattr(item, "gameplay_score", float("-inf"))),
            reverse=True,
        )
        self.gameplay_elite_archive = archive[: max(1, self.config.population_size)]

    def _log_generation(self, generation, offspring, generation_context, log_dir) -> None:
        best_individual = (
            max(self.gameplay_elite_archive, key=lambda ind: float(getattr(ind, "gameplay_score", float("-inf"))))
            if self.gameplay_elite_archive
            else max(self.population, key=self._fitness0)
        )
        self.log_single_objective_generation(log_dir, generation, best_individual)
        self.save_component_pool(log_dir)
        self.current_generation = generation
