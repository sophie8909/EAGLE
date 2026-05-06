"""Prompt rendering helpers for the MicroRTS domain."""

from __future__ import annotations

from typing import Any

from ...config import EAConfig
from ...utils.component_pool import ComponentPool


class MicroRTSPromptRenderer:
    """Render MicroRTS component-index genomes into prompt text."""

    def __init__(self, component_pool: ComponentPool, config: EAConfig | None = None):
        """Store renderer dependencies."""
        self.component_pool = component_pool
        self.config = config or EAConfig()

    def render(self, individual: Any) -> str:
        """Render an individual into a prompt string."""
        genome = getattr(individual, "genome", None)
        indices = genome if isinstance(genome, dict) else getattr(individual, "component_indices", {})
        prompt_lines = self.component_pool.render_prompt_lines(
            indices,
            include_identity_component=self.config.include_strategy_identity_in_prompt,
        )
        prompt = "\n".join(prompt_lines)
        if hasattr(individual, "rendered_prompt"):
            individual.rendered_prompt = prompt
        return prompt
