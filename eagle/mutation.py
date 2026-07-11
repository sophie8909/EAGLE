"""Prompt mutation operators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .candidate import Candidate, MODULE_NAMES
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
    def generate(self, prompt: str) -> str:
        """Return text for one mutation prompt."""


class RuleBasedMutationBackend:
    """Small local fallback so mutation remains runnable without a separate LLM backend."""

    def generate(self, prompt: str) -> str:
        if "Analyze this strategy's result." in prompt:
            return (
                "The strategy likely needs clearer economy and spending priorities. "
                "Preserve any stable defensive behavior, then focus the next generation on one concrete improvement."
            )
        if "Rewrite exactly one complete Java method for this module." in prompt:
            return section_between(prompt, 'Current function body:\n', '\n\nReflection:')
        if "Analyze why this code-generation instruction produced this result." in prompt:
            return (
                "The instruction likely needs stricter Java correctness constraints. "
                "Preserve working scaffold rules and add one concrete guard against the observed failure."
            )
        if "Rewrite exactly one complete Java method for this module." in prompt:
            return section_between(prompt, 'Current function body:\n', '\n\nReflection:')
        return prompt.strip()


class Mutation:
    """Apply one configured mutation method."""

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        method: str = "strategy_reflection",
        backend: MutationBackend | None = None,
    ) -> None:
        self.config = config
        self.method = method
        self.backend = backend or RuleBasedMutationBackend()

    def mutate(self, candidate: Candidate, context: MutationContext) -> Candidate:
        if self.method == "strategy_reflection":
            return self._strategy_reflection(candidate, context)
        if self.method == "code_generation_reflection":
            return self._code_generation_reflection(candidate, context)
        raise ValueError(f"Unknown mutation method: {self.method}")

    def _strategy_reflection(self, candidate: Candidate, context: MutationContext) -> Candidate:
        # Strategy reflection improves what the agent should do using game outcome feedback.
        module_name = context.target_module or strategy_module_for_index(context.index)
        reflection_prompt = build_strategy_reflection_prompt(candidate, context, module_name)
        reflection = self.backend.generate(reflection_prompt)
        rewrite_prompt = build_strategy_rewrite_prompt(candidate, reflection, self.config.mutation_suffix, module_name)
        revised_body = self.backend.generate(rewrite_prompt)
        module_bodies = dict(candidate.module_bodies)
        module_bodies[module_name] = normalize_prompt(
            revised_body,
            max_chars=self.config.max_prompt_chars,
            max_lines=self.config.max_prompt_lines,
        )
        return self._copy_candidate(
            candidate,
            context=context,
            module_prompts=candidate.module_prompts,
            module_bodies=module_bodies,
            previous_code=candidate.previous_code,
            generation_prompt=candidate.generation_prompt,
            reflection=reflection,
            rewrite=revised_body,
            module_name=module_name,
        )

    def _code_generation_reflection(self, candidate: Candidate, context: MutationContext) -> Candidate:
        # Code-generation reflection improves how code should be generated from the strategy context.
        module_name = context.target_module or code_module_from_error(context.error_message)
        reflection_prompt = build_code_reflection_prompt(candidate, context, module_name)
        reflection = self.backend.generate(reflection_prompt)
        rewrite_prompt = build_code_rewrite_prompt(candidate, reflection, self.config.mutation_suffix, module_name)
        revised_body = self.backend.generate(rewrite_prompt)
        module_bodies = dict(candidate.module_bodies)
        module_bodies[module_name] = revised_body.strip()
        return self._copy_candidate(
            candidate,
            context=context,
            module_prompts=candidate.module_prompts,
            module_bodies=module_bodies,
            previous_code=candidate.previous_code,
            generation_prompt=candidate.generation_prompt,
            reflection=reflection,
            rewrite=revised_body,
            module_name=module_name,
        )

    def _copy_candidate(
        self,
        candidate: Candidate,
        *,
        context: MutationContext,
        module_prompts: dict[str, str],
        module_bodies: dict[str, str],
        previous_code: str,
        generation_prompt: str,
        reflection: str,
        rewrite: str,
        module_name: str,
    ) -> Candidate:
        operator = candidate.metadata.get("operator", "mutation")
        if operator == "crossover":
            operator = "crossover+mutation"
        elif operator == "seed_mutation":
            operator = "seed_mutation"
        else:
            operator = "mutation"
        return Candidate(
            generation=context.generation,
            parent_ids=candidate.parent_ids or (candidate.id,),
            strategy_prompt=module_prompts["controller"],
            previous_code=previous_code,
            generation_prompt=generation_prompt,
            module_prompts=module_prompts,
            module_bodies=module_bodies,
            metadata={
                **candidate.metadata,
                "operator": operator,
                "mutation_method": self.method,
                "mutation_module": module_name,
                "mutation_reflection": reflection,
                "mutation_rewrite": rewrite,
            },
        )


def build_strategy_reflection_prompt(candidate: Candidate, context: MutationContext, module_name: str) -> str:
    return f"""Current module:
{module_name}

Current module prompt:
{candidate.module_prompts[module_name].rstrip()}

Current function body:
{candidate.module_bodies[module_name].rstrip()}

Evaluation:
- Game performance: {format_feedback(context.game_performance)}
- Player resources: {format_feedback(context.player_resource)}
- Enemy resources: {format_feedback(context.enemy_resource)}
- Resource breakdown: {context.resource_breakdown or {}}
- Performance breakdown: {context.performance_breakdown or {}}
- Temporal summary: {context.temporal_summary or {}}

Analyze this strategy's result.

Identify:
- What likely worked.
- What likely failed.
- The single most useful strategy change for the next generation.

Use the resource feedback directly:
- If enemy resources are higher, improve economy, expansion, harassment, or map control.
- If player resources are high but performance is poor, improve spending, unit production, or attack timing.
- If both sides have low resources, improve worker management and early economy.

Keep the analysis under 120 words.
Output only the analysis.
"""


def build_strategy_rewrite_prompt(candidate: Candidate, reflection: str, mutation_suffix: str, module_name: str) -> str:
    return f"""Current module:
{module_name}

Current function body:
{candidate.module_bodies[module_name].rstrip()}

Reflection:
{reflection.rstrip()}

{mutation_suffix}

Rewrite exactly one complete Java method for this module.

Requirements:
- Preserve behaviors that the reflection says likely worked.
- Apply the single most useful change from the reflection.
- Make only one or two focused changes.
- Keep it concise.
- Output exactly one complete Java method declaration.
- Do not add imports, fields, helpers, classes, markdown, or explanation.
- Do not include analysis, labels, markdown, or explanation.

Output only the revised complete Java method.
"""


def build_code_reflection_prompt(candidate: Candidate, context: MutationContext, module_name: str) -> str:
    return f"""Current module:
{module_name}

Current function body:
{candidate.module_bodies[module_name].rstrip()}

Evaluation:
- Alignment score: {format_feedback(context.alignment_score)}
- Java compile success: {context.compile_success}
- Java validation success: {context.validation_success}
- Runtime success: {context.runtime_success}
- Error category: {context.error_category or "none"}
- Error message: {context.error_message or "none"}

Analyze why this code-generation instruction produced this result.

Identify:
- What likely worked.
- What likely caused compile, validation, runtime, or alignment problems.
- The single most useful instruction change for the next generation.

Use the error message directly when available.
Focus on improving generated Java MicroRTS agent correctness and alignment.

Keep the analysis under 120 words.
Output only the analysis.
"""


def build_code_rewrite_prompt(candidate: Candidate, reflection: str, mutation_suffix: str, module_name: str) -> str:
    return f"""Current module:
{module_name}

Current function body:
{candidate.module_bodies[module_name].rstrip()}

Reflection:
{reflection.rstrip()}

{mutation_suffix}

Rewrite exactly one complete Java method for this module.

Requirements:
- Preserve constraints that likely worked.
- Apply the single most useful change from the reflection.
- Make only one or two focused changes.
- Keep it concise.
- Prefer concrete Java-generation constraints over vague advice.
- Output exactly one complete Java method declaration.
- Do not add imports, fields, helpers, classes, markdown, or explanation.
- Do not include analysis, labels, markdown, or explanation.

Output only the revised complete Java method.
"""


def format_feedback(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.3f}"


def section_between(text: str, start: str, end: str) -> str:
    if start not in text:
        return text.strip()
    value = text.split(start, 1)[1]
    if end in value:
        value = value.split(end, 1)[0]
    return value.strip()


def strategy_module_for_index(index: int) -> str:
    modules = ("controller", "economy", "combat", "expansion")
    return modules[index % len(modules)]


def code_module_from_error(error_message: str) -> str:
    lowered = error_message.lower()
    for module_name in MODULE_NAMES:
        if module_name.lower() in lowered:
            return module_name
    method_names = {
        "decide": "controller",
        "economy": "economy",
        "combat": "combat",
        "expansion": "expansion",
        "selecttarget": "target_selection",
        "findpath": "path_selection",
    }
    compact = lowered.replace("_", "").replace(" ", "")
    for method_name, module_name in method_names.items():
        if method_name in compact:
            return module_name
    return "controller"
