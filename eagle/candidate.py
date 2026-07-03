"""Candidate prompt representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class Candidate:
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    generation: int = 0
    parent_ids: tuple[str, ...] = ()
    prompt: str = ""
    generated_source_path: str | None = None
    fitness: float | None = None
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_updates(self, **updates: Any) -> "Candidate":
        payload = asdict(self)
        payload.update(updates)
        payload["parent_ids"] = tuple(payload.get("parent_ids") or ())
        return Candidate(**payload)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_ids"] = list(self.parent_ids)
        return payload
