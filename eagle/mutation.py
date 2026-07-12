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
    alignment_score: float | None = None
    alignment_reason: str = ""
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
        if "Rewrite the complete generation guidance" in prompt: return section_between(prompt, "Current generation guidance:\n", "\n\nPrevious complete function set:")
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
        operator="crossover+mutation" if candidate.metadata.get("operator")=="crossover" else "mutation"
        return Candidate(generation=context.generation,parent_ids=candidate.parent_ids or (candidate.id,),strategy_prompt=strategy_prompt,previous_code=candidate.previous_code,generation_prompt=generation_prompt,module_prompts=candidate.module_prompts,module_bodies=candidate.module_bodies,metadata={**candidate.metadata,"operator":operator,"mutation_method":self.method,"mutation_reflection":reflection,"mutation_rewrite":rewrite})

def build_strategy_reflection_prompt(candidate: Candidate, context: MutationContext) -> str:
    return f"""Current overall strategy:\n{candidate.strategy_prompt}\n\nPrevious complete function set:\n{candidate.module_bodies}\n\nEvaluation: game={context.game_performance}, resources={context.resource_breakdown or {}}, temporal={context.temporal_summary or {}}\nAnalyze this strategy's result. Reflect on the complete MicroRTS strategy, not one function."""
def build_strategy_rewrite_prompt(candidate: Candidate, reflection: str, suffix: str) -> str:
    return f"""Current overall strategy:\n{candidate.strategy_prompt}\n\nReflection:\n{reflection}\n\n{suffix}\n\nRewrite the overall strategy. Output only the revised strategy description."""
def build_code_reflection_prompt(candidate: Candidate, context: MutationContext) -> str:
    return f"""Current generation guidance:\n{candidate.generation_prompt}\n\nPrevious complete function set:\n{candidate.module_bodies}\n\nEvaluation: alignment={context.alignment_score}, compile={context.compile_success}, validation={context.validation_success}, runtime={context.runtime_success}, error={context.error_category}: {context.error_message}\nAnalyze why this code-generation instruction produced this result for the complete function set."""
def build_code_rewrite_prompt(candidate: Candidate, reflection: str, suffix: str) -> str:
    return f"""Current generation guidance:\n{candidate.generation_prompt}\n\nPrevious complete function set:\n{candidate.module_bodies}\n\nReflection:\n{reflection}\n\n{suffix}\n\nRewrite the complete generation guidance. The next request must regenerate all required function bodies together. Output only revised guidance."""
def section_between(text: str,start: str,end: str) -> str:
    if start not in text: return text.strip()
    value=text.split(start,1)[1]
    return value.split(end,1)[0].strip() if end in value else value.strip()
