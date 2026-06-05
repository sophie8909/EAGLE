"""Registry adapter for MicroRTS round-level reflection."""

from __future__ import annotations

from typing import Any

from eagle.operators.base import BaseReflection
from eagle.reflection.microrts.round_reflection import RoundReflection


class RoundReflectionOperator(BaseReflection):
    """Apply the existing MicroRTS round reflection implementation."""

    name = "round_reflection"

    def __call__(self, individual: Any, component_pool: Any, config: Any) -> Any:
        """Reflect one individual through the existing round-reflection logic."""
        return RoundReflection.reflect_individual(individual, component_pool, config)
