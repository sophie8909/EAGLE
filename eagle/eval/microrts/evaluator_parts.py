"""Focused helper classes for MicroRTS gameplay evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eagle.config import EAConfig
from eagle.envs.microrts.runner import (
    DEFAULT_LLM_CALL_LIMIT,
    run_java_agent_game,
    run_prompt_based_game,
)
from eagle.surrogate.java.eagle_java_compiler import compile_eagle_java_agent
from eagle.surrogate.java.eagle_java_renderer import render_eagle_java_from_prompt
from eagle.surrogate.compiler.eagle_policy_spec import compile_prompt_to_eagle_policy_spec
from eagle.surrogate.eval.eagle_policy_renderer import render_eagle_policy_agent
from eagle.envs.microrts.compiler import compile_microrts
from eagle.utils.component_pool import ComponentPool
from eagle.utils.token_count import count_prompt_tokens


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


class RoundSurrogateEvaluator:
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
        *,
        individual: Any,
        prompt: str,
        opponent: str | None,
        generation: int | None,
    ) -> dict[str, Any]:
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

        round_evaluator = RoundEvaluator(
            self.component_pool,
            self.config,
            runtime_logs_dir=self.runtime_logs_dir,
        )
        round_eval_result = round_evaluator.evaluate(individual, generation=generation)
        round_score = GameplayAggregator.round_surrogate_score(round_eval_result)
        return {
            "prompt": prompt,
            "prompt_token_count": count_prompt_tokens(prompt)[0],
            "match_score": {
                "win_score": 0.0,
                "raw_resource_advantage_score": round_score,
            },
            "simulation_meta": {
                "winner": None,
                "timeout": False,
                "round_eval_result": round_eval_result,
                "opponent": opponent,
            },
            "stats": {},
            "evaluation_mode": "round",
        }


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
        llm_call_limit: int | None | object = DEFAULT_LLM_CALL_LIMIT,
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
            ),
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
            ),
        )

    def _with_llm_interval(self, llm_interval: int | None, callback: Any) -> Any:
        """Temporarily override the active Java LLM interval while running a match."""
        original_interval = getattr(self.config, "_active_llm_interval", None)
        if llm_interval is not None:
            self.config.set_active_llm_interval(int(llm_interval))
        try:
            match_score, simulation_meta = callback()
            return GameplayAggregator.normalize_match_score(match_score), simulation_meta
        finally:
            self.config.set_active_llm_interval(original_interval)
