"""Candidate prompt representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class CandidatePrompt:
    """A prompt evolved by EAGLE to generate one Java MicroRTS agent."""

    text: str
    candidate_id: str = field(default_factory=lambda: uuid4().hex[:12])
    parent_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_text(self, text: str, *, metadata: dict[str, Any] | None = None) -> "CandidatePrompt":
        return CandidatePrompt(
            text=text,
            parent_ids=(self.candidate_id,),
            metadata=metadata or {},
        )

