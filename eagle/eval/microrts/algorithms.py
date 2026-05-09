"""MicroRTS bindings for generic component-evolution algorithms."""

from __future__ import annotations

from eagle.core.registry import ALGORITHMS, EVALUATORS
from eagle.evolution.component.ga import GA
from eagle.evolution.component.nsga2 import NSGA2
from eagle.reflection.microrts.round_reflection import RoundReflection

from .full_game_evaluator import FullGameEvaluator
from .round_evaluator import Evaluator as RoundEvaluator


EVALUATORS.register("round", RoundEvaluator)
EVALUATORS.register("gameplay", FullGameEvaluator)


@ALGORITHMS.register("round_ga")
class MicroRTSRoundGA(GA):
    """Single-objective component GA bound to the MicroRTS round evaluator."""

    evaluator_factory = RoundEvaluator
    reflection_operator = RoundReflection


@ALGORITHMS.register("round_nsga2")
class MicroRTSRoundNSGA2(NSGA2):
    """NSGA-II component evolution bound to the MicroRTS round evaluator."""

    evaluator_factory = RoundEvaluator
    reflection_operator = RoundReflection
