"""MicroRTS bindings for generic component-evolution algorithms."""

from __future__ import annotations

import math
import random
from typing import Any

from eagle.config import clone_config
from eagle.core.result import ensure_evaluation_result
from eagle.core.registry import ALGORITHMS, EVALUATORS
from eagle.objectives.aggressiveness.runtime import maybe_add_aggressiveness_metrics
from eagle.evolution.component.ga import GA
from eagle.evolution.component.nsga2 import NSGA2
from eagle.utils.token_count import count_prompt_tokens

from .full_game_evaluator import FullGameEvaluator
from .round_evaluator import Evaluator as RoundEvaluator


EVALUATORS.register("round", RoundEvaluator)
EVALUATORS.register("gameplay", FullGameEvaluator)


def add_prompt_metrics(
    eval_result: dict[str, Any],
    individual: Any,
    config: Any,
    *,
    rendered_prompt: str | None = None,
) -> dict[str, Any]:
    """Add static rendered-prompt metrics required by objective aggregation."""
    if "prompt_token_count" in eval_result:
        return eval_result
    prompt = str(eval_result.get("prompt") or rendered_prompt or getattr(individual, "rendered_prompt", "") or "")
    if not prompt:
        raise ValueError(
            "Cannot compute prompt_token_count because the rendered static prompt is missing "
            f"for individual {getattr(individual, 'id', None)}."
        )
    eval_result.setdefault("prompt", prompt)
    eval_result["prompt_token_count"] = count_prompt_tokens(prompt)[0]
    return eval_result


@ALGORITHMS.register("ga")
class MicroRTSGA(GA):
    """Single-objective component GA bound to full MicroRTS gameplay."""

    evaluator_factory = FullGameEvaluator


@ALGORITHMS.register("nsga2")
class MicroRTSNSGA2(NSGA2):
    """NSGA-II component evolution bound to full MicroRTS gameplay."""

    evaluator_factory = FullGameEvaluator


@ALGORITHMS.register("nsga2_surrogate")
class MicroRTSNSGA2Surrogate(NSGA2):
    """NSGA-II component evolution that evaluates candidates through surrogate scoring."""

    evaluator_factory = FullGameEvaluator

    def _evaluate_initial_population(self, evaluator):
        """Score the initial population with surrogate metrics only."""
        self._evaluate_surrogate_batch(self.population, generation=-1, label="Initial Population")
        print("[Initial Population] complete", flush=True)
        self.print_population_snapshot("initial population")
        self._log_initial_population_snapshot()

    def _evaluate_offspring(self, evaluator, offspring, generation: int) -> None:
        """Score offspring through surrogate evaluation and update mutation feedback."""
        self._evaluate_surrogate_batch(
            offspring,
            generation=generation,
            label=f"Generation {generation + 1}",
        )
        for child in offspring:
            print(
                f"[Generation {generation + 1}] surrogate result "
                f"id={child.id} fitness={getattr(child, 'fitness', None)}",
                flush=True,
            )
            self._update_mutation_component_feedback(child)

    def _evaluate_surrogate_batch(self, individuals, *, generation: int | None, label: str) -> None:
        """Evaluate one generation's NSGA-II surrogate candidates sequentially."""
        candidates = list(individuals)
        if not candidates:
            return
        prompt_groups = self._group_individuals_by_prompt(candidates)
        leaders = [group[0] for group in prompt_groups]
        duplicate_count = len(candidates) - len(leaders)
        print(
            "[Individual Eval Queue] "
            f"label={label} surrogate generation={generation} "
            f"individuals={len(candidates)} unique_prompts={len(leaders)} "
            f"prompt_cache_hits={duplicate_count}",
            flush=True,
        )
        for index, group in enumerate(prompt_groups, start=1):
            individual = group[0]
            print(
                f"[{label}] surrogate prompt {index}/{len(leaders)} "
                f"leader_id={individual.id} shared_by={len(group)}",
                flush=True,
            )
            evaluator = self.build_evaluator(config_override=clone_config(self.config))
            eval_result = self._evaluate_surrogate_individual(evaluator, individual, generation=generation)
            self._apply_prompt_cache_followers(group, individual, eval_result)

    def _evaluate_surrogate_individual(self, evaluator, individual, *, generation: int | None):
        """Run one surrogate evaluation and store aggregate-ready NSGA-II fitness."""
        eval_result = ensure_evaluation_result(evaluator.surrogate(
            individual,
            generation=generation,
            opponents=self.evaluation_context.get("opponents") or None,
        ))
        add_prompt_metrics(
            eval_result,
            individual,
            self.config,
            rendered_prompt=self._render_prompt_cache_key(individual),
        )
        maybe_add_aggressiveness_metrics(
            eval_result,
            individual=individual,
            config=self.config,
            run_dir=self.current_log_dir,
            generation=generation,
        )
        print(
            "[DEBUG] surrogate eval_result metrics before aggregation "
            f"individual={getattr(individual, 'id', None)} "
            f"prompt_token_count={eval_result.get('prompt_token_count')}",
            flush=True,
        )
        fitness = float(eval_result.get("resource_diff", 0.0))
        eval_result.fitness = {"resource_advantage": fitness}
        eval_result["fitness"] = fitness
        individual.fitness = fitness
        individual.rendered_prompt = eval_result.get("prompt", getattr(individual, "rendered_prompt", ""))
        individual.evaluation_mode = "surrogate"
        individual.surrogate_score = fitness
        individual.last_surrogate_evaluation = {"fitness": eval_result["fitness"], "eval_result": dict(eval_result)}
        return eval_result


@ALGORITHMS.register("ga_surrogate")
class MicroRTSGASurrogate(GA):
    """GA that ranks mostly by surrogate scores and refreshes elites with gameplay."""

    evaluator_factory = FullGameEvaluator

    def __init__(self, config, component_pool, evaluation_context=None):
        super().__init__(config, component_pool, evaluation_context)
        self.gameplay_elite_archive = []

    def _fitness0(self, individual) -> float:
        """Rank GA surrogate candidates by gameplay scores when refreshed."""
        if hasattr(individual, "gameplay_score"):
            return float(getattr(individual, "gameplay_score"))
        if hasattr(individual, "surrogate_score"):
            return float(getattr(individual, "surrogate_score"))
        return super()._fitness0(individual)

    def select_parent(self):
        """Sample parents from gameplay elites at the configured archive rate."""
        if self.gameplay_elite_archive and random.random() < float(self.config.archive_parent_ratio):
            return random.choice(self.gameplay_elite_archive)
        return super().select_parent()

    def _evaluate_initial_population(self, evaluator):
        """Seed surrogate scores, then force one gameplay refresh for the archive."""
        self._evaluate_surrogate_batch(self.population, generation=-1, label="Initial Population")
        self._refresh_gameplay_archive(evaluator, self.population, generation=-1, force=True)
        print("[Initial Population] complete", flush=True)
        self.print_population_snapshot("initial population")
        self._log_initial_population_snapshot()

    def _evaluate_offspring(self, evaluator, offspring, generation: int) -> None:
        """Score offspring with the surrogate and periodically refresh gameplay elites."""
        self._evaluate_surrogate_batch(
            offspring,
            generation=generation,
            label=f"Generation {generation + 1}",
        )
        for child in offspring:
            print(
                f"[Generation {generation + 1}] surrogate result "
                f"id={child.id} surrogate_score={getattr(child, 'surrogate_score', None)}",
                flush=True,
            )
            self._update_mutation_component_feedback(child)
        if self._is_gameplay_refresh_generation(generation):
            self._refresh_gameplay_archive(evaluator, offspring, generation=generation)

    def _evaluate_surrogate_batch(self, individuals, *, generation: int | None, label: str) -> None:
        """Evaluate one generation's surrogate candidates sequentially."""
        candidates = list(individuals)
        if not candidates:
            return
        prompt_groups = self._group_individuals_by_prompt(candidates)
        leaders = [group[0] for group in prompt_groups]
        duplicate_count = len(candidates) - len(leaders)
        print(
            "[Individual Eval Queue] "
            f"label={label} surrogate generation={generation} "
            f"individuals={len(candidates)} unique_prompts={len(leaders)} "
            f"prompt_cache_hits={duplicate_count}",
            flush=True,
        )
        for index, group in enumerate(prompt_groups, start=1):
            individual = group[0]
            print(
                f"[{label}] surrogate prompt {index}/{len(leaders)} "
                f"leader_id={individual.id} shared_by={len(group)}",
                flush=True,
            )
            evaluator = self.build_evaluator(config_override=clone_config(self.config))
            eval_result = self._evaluate_surrogate_individual(evaluator, individual, generation=generation)
            self._apply_prompt_cache_followers(group, individual, eval_result)

    def _is_gameplay_refresh_generation(self, generation: int) -> bool:
        """Return whether this generation should spend budget on real gameplay."""
        interval = max(1, int(self.config.gameplay_refresh_interval))
        return (int(generation) + 1) % interval == 0

    def _evaluate_surrogate_individual(self, evaluator, individual, *, generation: int | None):
        """Run one surrogate evaluation and keep the scalar score for GA ranking."""
        eval_result = ensure_evaluation_result(evaluator.surrogate(
            individual,
            generation=generation,
            opponents=self.evaluation_context.get("opponents") or None,
        ))
        add_prompt_metrics(
            eval_result,
            individual,
            self.config,
            rendered_prompt=self._render_prompt_cache_key(individual),
        )
        maybe_add_aggressiveness_metrics(
            eval_result,
            individual=individual,
            config=self.config,
            run_dir=self.current_log_dir,
            generation=generation,
        )
        print(
            "[DEBUG] surrogate eval_result metrics before aggregation "
            f"individual={getattr(individual, 'id', None)} "
            f"prompt_token_count={eval_result.get('prompt_token_count')}",
            flush=True,
        )
        fitness = float(eval_result.get("resource_diff", 0.0))
        eval_result.fitness = {"resource_advantage": fitness}
        eval_result["fitness"] = fitness
        individual.fitness = fitness
        individual.rendered_prompt = eval_result.get("prompt", getattr(individual, "rendered_prompt", ""))
        individual.evaluation_mode = "surrogate"
        individual.surrogate_score = super()._fitness0(individual)
        individual.last_surrogate_evaluation = {"fitness": eval_result["fitness"], "eval_result": dict(eval_result)}
        return eval_result

    def _refresh_gameplay_archive(self, evaluator, candidates, *, generation: int | None, force: bool = False) -> None:
        """Evaluate top surrogate candidates with gameplay and refresh the elite archive."""
        selected = self._top_surrogate_candidates(list(candidates), force=force)
        if not selected:
            return
        print(
            f"[GA Surrogate] gameplay refresh generation={generation} candidates={len(selected)}",
            flush=True,
        )
        self._evaluate_individual_batch(
            selected,
            generation=generation,
            stage="gameplay_refresh",
            label=f"GA Surrogate gameplay refresh {generation}",
        )
        for individual in selected:
            individual.gameplay_score = super()._fitness0(individual)
            individual.evaluation_mode = "gameplay"
            self._update_gameplay_archive(individual)

    def _top_surrogate_candidates(self, candidates, *, force: bool = False):
        """Return the surrogate-ranked subset that should receive gameplay evaluation."""
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
        """Keep one best-by-gameplay archive used for later parent sampling."""
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

    def _checkpoint_extra_state(self) -> dict:
        """Persist gameplay archive membership for interrupted ga_surrogate runs."""
        return {
            "gameplay_elite_archive_ids": [
                getattr(individual, "id", None)
                for individual in self.gameplay_elite_archive
                if getattr(individual, "id", None) is not None
            ]
        }

    def _restore_checkpoint_extra_state(self, state: dict) -> None:
        """Restore gameplay archive members from checkpointed population records."""
        archive_ids = set(state.get("gameplay_elite_archive_ids") or [])
        by_id = {getattr(individual, "id", None): individual for individual in self.population}
        self.gameplay_elite_archive = [
            by_id[individual_id]
            for individual_id in archive_ids
            if individual_id in by_id and hasattr(by_id[individual_id], "gameplay_score")
        ]
        if not self.gameplay_elite_archive:
            self.gameplay_elite_archive = [
                individual for individual in self.population if hasattr(individual, "gameplay_score")
            ]
        self.gameplay_elite_archive = sorted(
            self.gameplay_elite_archive,
            key=lambda item: float(getattr(item, "gameplay_score", float("-inf"))),
            reverse=True,
        )[: max(1, self.config.population_size)]

    def _log_generation(self, generation, offspring, generation_context, log_dir) -> None:
        best_individual = (
            max(self.gameplay_elite_archive, key=lambda ind: float(getattr(ind, "gameplay_score", float("-inf"))))
            if self.gameplay_elite_archive
            else max(self.population, key=self._fitness0)
        )
        self.log_single_objective_generation(log_dir, generation, best_individual)
        self.save_component_pool(log_dir)
        self.current_generation = generation

