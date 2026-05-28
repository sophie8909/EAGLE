"""Focused helper classes for MicroRTS gameplay evaluation."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from eagle.config import EAConfig
from eagle.envs.microrts.runner import (
    run_java_agent_game,
    run_prompt_based_game,
)
from eagle.surrogate.java.eagle_java_compiler import compile_eagle_java_agent
from eagle.surrogate.java.eagle_java_renderer import render_eagle_java_from_prompt
from eagle.surrogate.compiler.eagle_policy_spec import compile_prompt_to_eagle_policy_spec
from eagle.surrogate.eval.eagle_policy_renderer import render_eagle_policy_agent
from eagle.envs.microrts.compiler import compile_microrts
from eagle.core.result import EvaluationResult
from eagle.eval.base import BaseEvaluator, EvaluationContext
from eagle.utils.component_pool import ComponentPool
from eagle.utils.token_count import count_prompt_tokens

LOGGER = logging.getLogger(__name__)
MICRORTS_JAVA_FAILURE_TYPE = "microrts_java_process_failed"


class PromptRenderer:
    """Render component-index individuals into exact evaluator prompts."""

    def __init__(self, component_pool: ComponentPool, config: EAConfig) -> None:
        """Create a prompt renderer.

        Args:
            component_pool: Component pool containing all prompt candidates.
            config: Runtime config. `include_strategy_identity_in_prompt` controls
                whether the identity component is included.
        """
        self.component_pool = component_pool
        self.config = config

    def render(self, individual: Any) -> str:
        """Render one individual's component indices into prompt text.

        Args:
            individual: Object with `component_indices`.

        Returns:
            Newline-joined prompt text used by gameplay and surrogate evaluators.
        """
        prompt_lines = self.component_pool.render_prompt_lines(
            individual.component_indices,
            include_identity_component=self.config.include_strategy_identity_in_prompt,
            selected_training_examples=getattr(individual, "training_examples", None),
            use_few_shot_examples=getattr(self.config, "use_few_shot_examples", True),
            min_examples=getattr(self.config, "min_examples", 0),
            max_examples=getattr(self.config, "max_examples", 3),
        )
        return "\n".join(prompt_lines)


class GameplayAggregator:
    """Normalize raw match scores and aggregate opponent results."""

    @staticmethod
    def aggregate_raw_eval_result(eval_result: dict[str, Any]) -> dict[str, Any]:
        """Add top-level raw metrics averaged across opponent match results.

        Args:
            eval_result: Evaluator payload containing a `scores` list. Each score may
                include `match_score`, `parsed_summary`, and timeout metadata.

        Returns:
            The same payload with averaged metrics used by objective plugins.
        """
        scores = list(eval_result.get("scores") or [])
        if not scores:
            eval_result.update(
                {
                    "resource_diff": 0.0,
                    "ally_units": 0.0,
                    "enemy_units": 0.0,
                    "winner": 0.0,
                    "game_ticks": 0.0,
                    "timeout": False,
                }
            )
            return eval_result

        resource_total = 0.0
        win_total = 0.0
        tick_total = 0.0
        ally_total = 0.0
        enemy_total = 0.0
        timeout = False
        for score in scores:
            match_score = dict(score.get("match_score") or {})
            resource_total += float(match_score.get("raw_resource_advantage_score", 0.0))
            win_total += float(match_score.get("win_score", 0.0))
            timeout = timeout or bool(score.get("timeout", False))
            summary = dict(score.get("parsed_summary") or {})
            resource_history = list(summary.get("resource_history") or [])
            if resource_history:
                tick_total += float(resource_history[-1].get("time", 0.0))
            feature_history = list(summary.get("feature_history") or [])
            if feature_history:
                final_features = dict(feature_history[-1])
                ally_total += sum(float(value) for value in dict(final_features.get("ally") or {}).values())
                enemy_total += sum(float(value) for value in dict(final_features.get("enemy") or {}).values())

        count = float(len(scores))
        eval_result.update(
            {
                "resource_diff": resource_total / count,
                "ally_units": ally_total / count,
                "enemy_units": enemy_total / count,
                "winner": win_total / count,
                "game_ticks": tick_total / count,
                "timeout": timeout,
            }
        )
        return eval_result

    @staticmethod
    def normalize_match_score(match_score: Any) -> dict[str, float]:
        """Normalize match-score payloads into named scalar scores."""
        if isinstance(match_score, dict):
            return {
                "win_score": float(match_score.get("win_score", 0.0)),
                "raw_resource_advantage_score": float(match_score.get("raw_resource_advantage_score", 0.0)),
            }
        if isinstance(match_score, (list, tuple)):
            win_score = float(match_score[0]) if len(match_score) > 0 else 0.0
            raw_resource_score = float(match_score[1]) if len(match_score) > 1 else 0.0
            return {
                "win_score": win_score,
                "raw_resource_advantage_score": raw_resource_score,
            }
        return {
            "win_score": 0.0,
            "raw_resource_advantage_score": 0.0,
        }

    @staticmethod
    def raw_resource_advantage_score(match_score: dict[str, Any] | None) -> float:
        """Extract the raw resource advantage scalar from a match score."""
        if not isinstance(match_score, dict):
            return 0.0
        return float(match_score.get("raw_resource_advantage_score", 0.0))

    @staticmethod
    def round_surrogate_score(round_eval_result: dict[str, Any]) -> float:
        """Extract a scalar score from a round-evaluator result."""
        for key in ("fitness", "round_score", "raw_resource_advantage_score", "score"):
            value = round_eval_result.get(key)
            if isinstance(value, dict):
                value = next(iter(value.values()), 0.0)
            elif isinstance(value, (list, tuple)):
                value = value[0] if value else 0.0
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0


class RoundSurrogateEvaluator(BaseEvaluator):
    """Run the local round evaluator and adapt it to match-score shape."""

    def __init__(
        self,
        component_pool: ComponentPool,
        config: EAConfig,
        runtime_logs_dir: str | Path | None,
    ) -> None:
        """Create a round surrogate helper.

        Args:
            component_pool: Component pool used by the round evaluator.
            config: Active EA config.
            runtime_logs_dir: Optional per-run log directory for round artifacts.
        """
        self.component_pool = component_pool
        self.config = config
        self.runtime_logs_dir = runtime_logs_dir

    def evaluate(
        self,
        individual: Any,
        context: EvaluationContext | None = None,
        *,
        prompt: str | None = None,
        opponent: str | None = None,
        generation: int | None = None,
    ) -> EvaluationResult:
        """Evaluate one candidate without launching Java gameplay.

        Args:
            individual: Individual to evaluate.
            prompt: Already rendered prompt text.
            opponent: Optional opponent metadata. Round mode does not use it.
            generation: Current generation for logs and state sampling.

        Returns:
            Match-score shaped payload compatible with gameplay aggregation.
        """
        from .round_evaluator import Evaluator as RoundEvaluator

        if context is not None:
            generation = context.generation if generation is None else generation
            if context.opponents and opponent is None:
                opponent = context.opponents[0]
        rendered_prompt = prompt if prompt is not None else getattr(individual, "rendered_prompt", "")
        round_evaluator = RoundEvaluator(
            self.component_pool,
            self.config,
            runtime_logs_dir=self.runtime_logs_dir,
        )
        round_eval_result = round_evaluator.evaluate(individual, generation=generation)
        round_metrics = dict(round_eval_result)
        round_score = GameplayAggregator.round_surrogate_score(round_metrics)
        return EvaluationResult(metrics={
            "prompt": rendered_prompt,
            "prompt_token_count": count_prompt_tokens(rendered_prompt)[0],
            "match_score": {
                "win_score": 0.0,
                "raw_resource_advantage_score": round_score,
            },
            "simulation_meta": {
                "winner": None,
                "timeout": False,
                "round_eval_result": round_metrics,
                "opponent": opponent,
            },
            "stats": {},
            "evaluation_mode": "round",
        })


class JavaMatchEvaluator:
    """Prepare and launch Java-backed MicroRTS matches."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: EAConfig,
        runtime_logs_dir: str | Path | None,
    ) -> None:
        """Create a Java match helper.

        Args:
            repo_root: EAGLE repository root.
            config: Active runtime config passed to Java launch helpers.
            runtime_logs_dir: Optional per-run log directory for match artifacts.
        """
        self.repo_root = repo_root
        self.config = config
        self.runtime_logs_dir = runtime_logs_dir

    def prepare_policy_agent(self, prompt: str) -> None:
        """Render and compile the reusable `eaglePolicy` Java agent."""
        eagle_policy_spec = compile_prompt_to_eagle_policy_spec(prompt)[1]
        render_eagle_policy_agent(self.repo_root, prompt, eagle_policy_spec)
        compile_microrts(self.repo_root)

    def prepare_generated_java_agent(self, prompt: str) -> None:
        """Render and compile the generated `eagleJava` Java agent."""
        cache_root = self.repo_root / "logs" / "eagle_java"
        java_code = render_eagle_java_from_prompt(prompt)
        compile_eagle_java_agent(java_code, str(cache_root))

    def run_prompt_match(
        self,
        prompt: str,
        opponent: str | None,
        *,
        llm_interval: int | None,
        test: bool,
        generation: int | None,
        individual_id: Any | None,
        llm_call_limit: int | None = None,
        llm_model: str | None = None,
        llm_base_url: str | None = None,
        llm_strict_errors: bool = False,
        interval_mode: str | None = None,
        map_location: str | None = None,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        """Run one prompt-driven EAGLE Java match."""
        return self._with_llm_interval(
            llm_interval,
            lambda: run_prompt_based_game(
                project_root=self.repo_root,
                config=self.config,
                prompt=prompt,
                opponent=opponent,
                test=test,
                runtime_logs_dir=self.runtime_logs_dir,
                generation=generation,
                individual_id=individual_id,
                llm_call_limit=llm_call_limit,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                llm_strict_errors=llm_strict_errors,
                interval_mode=interval_mode,
                map_location=map_location,
            ),
            opponent=opponent,
            generation=generation,
            individual_id=individual_id,
        )

    def run_java_match(
        self,
        prompt: str,
        opponent: str | None,
        *,
        ai1_class: str,
        llm_interval: int | None,
        test: bool,
        log_prefix: str,
        compile_first: bool,
        generation: int | None,
        individual_id: Any | None,
        llm_call_limit: int | None = None,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        """Run one prepared Java-agent match."""
        return self._with_llm_interval(
            llm_interval,
            lambda: run_java_agent_game(
                project_root=self.repo_root,
                config=self.config,
                ai1_class=ai1_class,
                opponent=opponent,
                prompt=prompt,
                compile_first=compile_first,
                log_prefix=log_prefix if not test else f"{log_prefix.replace('run_', 'run_test_', 1)}",
                runtime_logs_dir=self.runtime_logs_dir,
                record_trace=True,
                generation=generation,
                individual_id=individual_id,
                llm_call_limit=llm_call_limit,
            ),
            opponent=opponent,
            generation=generation,
            individual_id=individual_id,
        )

    def _with_llm_interval(
        self,
        llm_interval: int | None,
        callback: Any,
        *,
        opponent: str | None,
        generation: int | None,
        individual_id: Any | None,
    ) -> Any:
        """Temporarily override the active Java LLM interval while running a match."""
        original_interval = getattr(self.config, "_active_llm_interval", None)
        if llm_interval is not None:
            self.config.set_active_llm_interval(int(llm_interval))
        try:
            try:
                match_score, simulation_meta = callback()
            except RuntimeError as exc:
                if not _is_microrts_java_process_failure(exc):
                    raise
                match_score, simulation_meta = _failed_gameplay_result(
                    config=self.config,
                    opponent=opponent,
                    error=exc,
                    individual_id=individual_id,
                    generation=generation,
                )
            return GameplayAggregator.normalize_match_score(match_score), simulation_meta
        finally:
            self.config.set_active_llm_interval(original_interval)


def _failed_gameplay_result(
    *,
    config: Any,
    opponent: str | None,
    error: RuntimeError,
    individual_id: Any | None,
    generation: int | None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Convert one known MicroRTS Java failure into a failed match result."""
    details = _microrts_failure_details(error)
    simulation_meta = {
        "failed": True,
        "failure_type": MICRORTS_JAVA_FAILURE_TYPE,
        "error": str(error),
        "log_path": details.get("log_path"),
        "exit_code": details.get("exit_code"),
        "opponent": opponent,
        "winner": -1,
        "result": "failed",
        "status": "failed",
        "timeout": False,
        "parsed_log": {},
    }
    LOGGER.warning(
        "MicroRTS Java process failed; marking match failed "
        "individual_id=%s generation=%s opponent=%s log_path=%s exit_code=%s",
        individual_id,
        generation,
        opponent,
        simulation_meta["log_path"],
        simulation_meta["exit_code"],
    )
    return _failed_match_score(config), simulation_meta


def _failed_match_score(config: Any) -> dict[str, float]:
    """Return a conservative worst-case score for a failed gameplay match."""
    penalty = abs(float(getattr(config, "win_bonus", 100.0) or 100.0))
    return {
        "win_score": -1.0,
        "raw_resource_advantage_score": -penalty,
    }


def _is_microrts_java_process_failure(error: RuntimeError) -> bool:
    """Return whether a RuntimeError is the expected Java-process failure."""
    return "MicroRTS Java process failed" in str(error)


def _microrts_failure_details(error: RuntimeError) -> dict[str, Any]:
    """Extract structured metadata from the Java-process failure message."""
    text = str(error)
    exit_code_match = re.search(r"\bexit_code\s*=\s*(-?\d+)", text)
    log_path_match = re.search(r"\blog_path\s*=\s*(.+)", text)
    return {
        "exit_code": int(exit_code_match.group(1)) if exit_code_match else None,
        "log_path": log_path_match.group(1).strip() if log_path_match else None,
    }
