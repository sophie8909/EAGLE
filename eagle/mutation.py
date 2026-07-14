"""Candidate-level strategy and code-generation reflection."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .candidate import Candidate
from .config import ExperimentConfig
from .offspring import normalize_prompt

@dataclass(frozen=True)
class MutationContext:
    generation: int
    index: int
    game_performance: float | None = None
    player_resource: float | None = None
    enemy_resource: float | None = None
    resource_breakdown: dict[str, object] | None = None
    performance_breakdown: dict[str, object] | None = None
    temporal_summary: dict[str, object] | None = None
    compilation_score: float | None = None
    compiler_errors: tuple[str, ...] = ()
    compiler_warnings: tuple[str, ...] = ()
    strategy_region_score: float | None = None
    strategy_region_validation: dict[str, object] | None = None
    static_quality_score: float | None = None
    static_metrics: dict[str, object] | None = None
    compile_success: bool | None = None
    validation_success: bool | None = None
    runtime_success: bool | None = None
    error_category: str = ""
    error_message: str = ""
    target_module: str | None = None

class MutationBackend(Protocol):
    def generate(self, prompt: str) -> str: ...

class RuleBasedMutationBackend:
    def generate(self, prompt: str) -> str:
        if "Rewrite the overall strategy" in prompt: return section_between(prompt, "Current overall strategy:\n", "\n\nReflection:")
        if "Rewrite the complete generation guidance" in prompt: return section_between(prompt, "Current generation guidance:\n", "\n\nPrevious complete Java agent:")
        return "Preserve coherent working behavior and make one focused candidate-level improvement."

class Mutation:
    def __init__(self, config: ExperimentConfig, *, method: str = "strategy_reflection", backend: MutationBackend | None = None) -> None:
        self.config=config; self.method=method; self.backend=backend or RuleBasedMutationBackend()
    def mutate(self, candidate: Candidate, context: MutationContext) -> Candidate:
        if self.method == "strategy_reflection": return self._strategy(candidate, context)
        if self.method == "code_generation_reflection": return self._code(candidate, context)
        raise ValueError(f"Unknown mutation method: {self.method}")
    def _strategy(self, candidate: Candidate, context: MutationContext) -> Candidate:
        reflection=self.backend.generate(build_strategy_reflection_prompt(candidate, context))
        rewrite=self.backend.generate(build_strategy_rewrite_prompt(candidate, reflection, self.config.mutation_suffix))
        return self._copy(candidate, context, strategy_prompt=normalize_prompt(rewrite,max_chars=self.config.max_prompt_chars,max_lines=self.config.max_prompt_lines), generation_prompt=candidate.generation_prompt, reflection=reflection, rewrite=rewrite)
    def _code(self, candidate: Candidate, context: MutationContext) -> Candidate:
        reflection=self.backend.generate(build_code_reflection_prompt(candidate, context))
        rewrite=self.backend.generate(build_code_rewrite_prompt(candidate, reflection, self.config.mutation_suffix))
        return self._copy(candidate, context, strategy_prompt=candidate.strategy_prompt, generation_prompt=normalize_prompt(rewrite,max_chars=self.config.max_prompt_chars,max_lines=self.config.max_prompt_lines), reflection=reflection, rewrite=rewrite)
    def _copy(self,candidate: Candidate,context: MutationContext,*,strategy_prompt: str,generation_prompt: str,reflection: str,rewrite: str) -> Candidate:
        operator = "crossover+mutation" if candidate.operator == "crossover" else "mutation"
        mutation_type = "strategy" if self.method == "strategy_reflection" else "code"
        direct_parent_id = candidate.parent_ids[0] if candidate.parent_ids else candidate.id
        strategy_parent_id = candidate.strategy_parent_id or direct_parent_id
        previous_code_parent_id = candidate.previous_code_parent_id or direct_parent_id
        generation_prompt_parent_id = candidate.generation_prompt_parent_id or direct_parent_id
        source_candidate_ids = candidate.resolved_source_candidate_ids() or (direct_parent_id,)
        return Candidate(
            generation=context.generation,
            parent_ids=candidate.parent_ids or (candidate.id,),
            strategy_prompt=strategy_prompt,
            previous_code=candidate.previous_code,
            generation_prompt=generation_prompt,
            operator=operator,
            mutation_type=mutation_type,
            strategy_parent_id=strategy_parent_id,
            previous_code_parent_id=previous_code_parent_id,
            generation_prompt_parent_id=generation_prompt_parent_id,
            source_candidate_ids=source_candidate_ids,
            metadata={
                **candidate.metadata,
                "mutation_method": self.method,
                "mutation_reflection": reflection,
                "mutation_rewrite": rewrite,
            },
        )

def build_strategy_reflection_prompt(candidate: Candidate, context: MutationContext) -> str:
    return f"""Current overall strategy:\n{candidate.strategy_prompt}\n\nPrevious complete Java agent:\n{candidate.previous_code}\n\nEvaluation: game={context.game_performance}, resources={context.resource_breakdown or {}}, temporal={context.temporal_summary or {}}\nAnalyze this strategy's result. Reflect on the complete MicroRTS strategy, not one function."""
def build_strategy_rewrite_prompt(candidate: Candidate, reflection: str, suffix: str) -> str:
    return f"""Current overall strategy:\n{candidate.strategy_prompt}\n\nReflection:\n{reflection}\n\n{suffix}\n\nRewrite the overall strategy. Output only the revised strategy description."""
def build_code_reflection_prompt(candidate: Candidate, context: MutationContext) -> str:
    return f"""Current generation guidance:\n{candidate.generation_prompt}\n\nPrevious complete Java agent:\n{candidate.previous_code}\n\nCompilation score: {context.compilation_score}\nCompiler errors: {list(context.compiler_errors)}\nCompiler warnings: {list(context.compiler_warnings)}\nStrategy region validity score: {context.strategy_region_score}/100\nStrategy region validation: {context.strategy_region_validation or {}}\nStatic quality score: {context.static_quality_score}/100\nObjective static metrics: {context.static_metrics or {}}\nRuntime success: {context.runtime_success}\nError: {context.error_category}: {context.error_message}\nAnalyze the complete agent and propose guidance for regenerating one entire compilable CandidateAgent.java file. The model output must be Java source, never JSON or a function-body map."""
def build_code_rewrite_prompt(candidate: Candidate, reflection: str, suffix: str) -> str:
    return f"""Current generation guidance:\n{candidate.generation_prompt}\n\nPrevious complete Java agent:\n{candidate.previous_code}\n\nReflection:\n{reflection}\n\n{suffix}\n\nRewrite the complete generation guidance. The next generation request must return one entire compilable CandidateAgent.java file, never JSON, a functions object, or partial method bodies. Output only revised guidance."""
def section_between(text: str,start: str,end: str) -> str:
    if start not in text: return text.strip()
    value=text.split(start,1)[1]
    return value.split(end,1)[0].strip() if end in value else value.strip()
