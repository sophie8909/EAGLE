"""Shared reflection contracts."""

from __future__ import annotations

from typing import Any, Protocol


class ReflectionContextProvider(Protocol):
    """Build application-specific context for a generic reflection operator."""

    def select_target(self, individual: Any, component_pool: Any) -> str | None:
        """Choose the component that should be reflected."""

    def build_instruction(
        self,
        *,
        individual: Any,
        component_pool: Any,
        target: str,
        current_text: str,
    ) -> str:
        """Build the application-specific rewrite instruction."""
