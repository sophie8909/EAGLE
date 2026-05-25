"""Runtime-managed prompt examples derived from observed actions."""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

from eagle.envs.microrts.parser import extract_opponent_action_examples_from_log


class ExampleMemory:
    """Bounded deduplicated memory of schema-valid action examples."""

    REQUIRED_MOVE_FIELDS = ("raw_move", "unit_position", "unit_type", "action_type")

    def __init__(self, max_examples: int = 32, initial_examples: Iterable[dict[str, Any]] | None = None):
        """Create a bounded memory pool and optionally seed it with examples."""
        self.max_examples = max(1, int(max_examples))
        self._examples_by_key: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
        if initial_examples:
            self.add_examples(initial_examples)

    @property
    def examples(self) -> list[dict[str, Any]]:
        """Return stored examples in insertion order."""
        return [dict(example) for example in self._examples_by_key.values()]

    def add_examples(self, examples: Iterable[dict[str, Any]]) -> int:
        """Normalize, deduplicate, and store examples."""
        added = 0
        for example in examples:
            normalized = self.normalize_example(example)
            if normalized is None:
                continue
            key = self.example_key(normalized)
            if key in self._examples_by_key:
                self._examples_by_key.move_to_end(key)
                continue
            self._examples_by_key[key] = normalized
            added += 1
            while len(self._examples_by_key) > self.max_examples:
                self._examples_by_key.popitem(last=False)
        return added

    def add_from_game_log(self, log_path: str | Path | None) -> int:
        """Read one MicroRTS log and add opponent action examples from it."""
        if not log_path:
            return 0
        path = Path(log_path)
        if not path.exists():
            return 0
        return self.add_examples(extract_opponent_action_examples_from_log(path))

    @classmethod
    def normalize_example(cls, example: dict[str, Any]) -> dict[str, Any] | None:
        """Return one prompt example whose moves follow the current JSON schema."""
        if not isinstance(example, dict):
            return None
        moves = example.get("moves")
        if not isinstance(moves, list):
            move = cls.normalize_move(example)
            if move is None:
                return None
            moves = [move]
        normalized_moves = [move for move in (cls.normalize_move(move) for move in moves) if move is not None]
        if not normalized_moves:
            return None

        primary = normalized_moves[0]
        name = str(example.get("name") or cls._move_name(primary))
        content = example.get("content")
        if not isinstance(content, list):
            content = cls.render_content(normalized_moves)
        return {
            "name": name,
            "content": [str(line) for line in content],
            "moves": normalized_moves,
        }

    @classmethod
    def normalize_move(cls, move: Any) -> dict[str, Any] | None:
        """Normalize one action object to required prompt move fields."""
        if not isinstance(move, dict):
            return None
        if isinstance(move.get("llm_move_raw"), dict):
            move = dict(move["llm_move_raw"])

        raw_move = str(move.get("raw_move") or "").strip()
        unit_type = str(move.get("unit_type") or "").strip().lower()
        action_type = str(move.get("action_type") or "").strip().lower()
        unit_position = move.get("unit_position")
        if not raw_move or not unit_type or not action_type:
            return None
        if (
            not isinstance(unit_position, list)
            or len(unit_position) != 2
            or not all(isinstance(value, int) for value in unit_position)
        ):
            return None
        return {
            "raw_move": raw_move,
            "unit_position": [int(unit_position[0]), int(unit_position[1])],
            "unit_type": unit_type,
            "action_type": action_type,
        }

    @classmethod
    def example_key(cls, example: dict[str, Any]) -> tuple[str, str, str]:
        """Build the normalized raw_move/action_type/unit_type dedupe key."""
        moves = example.get("moves")
        move = moves[0] if isinstance(moves, list) and moves else example
        normalized = cls.normalize_move(move) or {
            "raw_move": "",
            "unit_type": "",
            "action_type": "",
        }
        return (
            normalized["raw_move"].strip().lower(),
            normalized["action_type"].strip().lower(),
            normalized["unit_type"].strip().lower(),
        )

    @staticmethod
    def render_content(moves: list[dict[str, Any]]) -> list[str]:
        """Render schema-valid moves as a prompt training example."""
        payload = {
            "thinking": "opponent_action_memory",
            "moves": moves,
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        return ["OUTPUT:", *rendered.splitlines()]

    @staticmethod
    def _move_name(move: dict[str, Any]) -> str:
        raw_move = str(move.get("raw_move", "")).strip().lower()
        action_type = str(move.get("action_type", "")).strip().lower() or "action"
        slug = "".join(ch if ch.isalnum() else "_" for ch in raw_move).strip("_")
        return f"opponent_{action_type}_{slug[:48] or 'example'}"
