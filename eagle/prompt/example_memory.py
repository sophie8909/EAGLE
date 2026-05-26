"""Runtime-managed prompt examples derived from observed actions."""

from __future__ import annotations

import json
import random
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from eagle.envs.microrts.parser import extract_opponent_action_examples_from_log


class ExampleMemory:
    """Bounded deduplicated memory of schema-valid action examples."""

    DEFAULT_MAX_EXAMPLES = 20
    REQUIRED_MOVE_FIELDS = ("raw_move", "unit_position", "unit_type", "action_type")

    def __init__(
        self,
        max_examples: int = DEFAULT_MAX_EXAMPLES,
        initial_examples: Iterable[dict[str, Any]] | None = None,
        pool_path: str | Path | None = None,
    ):
        """Create a bounded memory pool and optionally seed it with examples."""
        self.max_examples = min(self.DEFAULT_MAX_EXAMPLES, max(1, int(max_examples)))
        self.pool_path = Path(pool_path) if pool_path is not None else None
        self._examples_by_key: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
        self.load()
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
            self._discard_random_excess()
            if key in self._examples_by_key:
                added += 1
        if added:
            self.save()
        return added

    def add_generation_examples(self, examples: Iterable[dict[str, Any]], *, rng: Any = random) -> int:
        """Add one generation's valid examples using bounded replacement rules."""
        candidates = self._new_normalized_candidates(examples)
        if not candidates:
            return 0

        capacity = self.max_examples - len(self._examples_by_key)
        if capacity > 0:
            selected = self._prioritized_sample(candidates, capacity, rng=rng)
            replace_existing = False
        else:
            selected = self._prioritized_sample(candidates, 10, rng=rng)
            replace_existing = True

        added = 0
        inserted_keys: set[tuple[str, str, str]] = set()
        for example in selected:
            key = self.example_key(example)
            if key in self._examples_by_key:
                continue
            if replace_existing and self._examples_by_key:
                discard_candidates = [candidate_key for candidate_key in self._examples_by_key.keys() if candidate_key not in inserted_keys]
                discard_key = rng.choice(discard_candidates or list(self._examples_by_key.keys()))
                del self._examples_by_key[discard_key]
            self._examples_by_key[key] = example
            inserted_keys.add(key)
            added += 1

        if added:
            self.save()
        return added

    def _new_normalized_candidates(self, examples: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize and deduplicate candidates not already in the pool."""
        candidates_by_key: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
        existing = set(self._examples_by_key.keys())
        for example in examples:
            normalized = self.normalize_example(example)
            if normalized is None or normalized.get("validator_passed") is not True:
                continue
            key = self.example_key(normalized)
            if key in existing or key in candidates_by_key:
                continue
            candidates_by_key[key] = normalized
        return list(candidates_by_key.values())

    @staticmethod
    def _prioritized_sample(examples: list[dict[str, Any]], limit: int, *, rng: Any = random) -> list[dict[str, Any]]:
        """Sample candidates with real-eval examples taking priority."""
        limit = min(max(0, int(limit)), len(examples))
        if limit <= 0:
            return []
        real_eval = [example for example in examples if example.get("source") == "real_eval"]
        other = [example for example in examples if example.get("source") != "real_eval"]
        if len(real_eval) >= limit:
            return rng.sample(real_eval, limit)
        selected = list(real_eval)
        remaining = limit - len(selected)
        if remaining > 0:
            selected.extend(rng.sample(other, min(remaining, len(other))))
        return selected

    def _discard_random_excess(self) -> None:
        """Randomly discard examples until the pool is within its configured limit."""
        while len(self._examples_by_key) > self.max_examples:
            discard_key = random.choice(list(self._examples_by_key.keys()))
            del self._examples_by_key[discard_key]

    def add_from_game_log(self, log_path: str | Path | None) -> int:
        """Read one MicroRTS log and add opponent action examples from it."""
        return self.add_examples(self.examples_from_game_log(log_path))

    def examples_from_game_log(self, log_path: str | Path | None) -> list[dict[str, Any]]:
        """Read one MicroRTS log and return validated real-eval action examples."""
        if not log_path:
            return []
        path = Path(log_path)
        if not path.exists():
            return []
        examples: list[dict[str, Any]] = []
        for move in extract_opponent_action_examples_from_log(path):
            normalized = self.normalize_move(move)
            if normalized is None:
                continue
            examples.append(
                {
                    "name": self._move_name(normalized),
                    "content": self.render_content([normalized]),
                    "moves": [normalized],
                    "source": "real_eval",
                    "validator_passed": True,
                    "legality_level": "execution_log",
                }
            )
        return examples

    def add_from_round_evaluation(self, evaluation: dict[str, Any] | None) -> int:
        """Add examples from round-surrogate evaluation samples."""
        return self.add_examples(self.collect_from_round_evaluation(evaluation))

    def examples_from_round_evaluation(self, evaluation: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Build examples from round-surrogate evaluation samples without storing them."""
        examples, _ = self._examples_and_validation_logs_from_round_evaluation(evaluation)
        return examples

    def collect_from_round_evaluation(self, evaluation: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Build round examples and append validation logs for skipped responses."""
        examples, validation_logs = self._examples_and_validation_logs_from_round_evaluation(evaluation)
        self._append_validation_logs(validation_logs)
        return examples

    def _examples_and_validation_logs_from_round_evaluation(
        self,
        evaluation: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build validated round examples and skipped-response log records."""
        if not isinstance(evaluation, dict):
            return [], []
        samples = evaluation.get("samples")
        if not isinstance(samples, list):
            return [], []
        examples: list[dict[str, Any]] = []
        validation_logs: list[dict[str, Any]] = []
        generation = evaluation.get("generation")
        from eagle.eval.microrts.response_validator import validate_llm_response

        for sample in samples:
            if not isinstance(sample, dict):
                continue
            dynamic_prompt = str(sample.get("dynamic_prompt") or "").strip()
            response_text = self._round_sample_response_text(sample)
            validation = validate_llm_response(response_text, dynamic_prompt)
            sample_generation = sample.get("generation", generation)
            round_id = sample.get("round_id", sample.get("sample", sample.get("turn")))
            if validation.errors:
                validation_logs.append(
                    {
                        "source": "round",
                        "generation": sample_generation,
                        "round_id": round_id,
                        "turn": sample.get("turn"),
                        "validator_passed": validation.is_valid,
                        "legality_level": validation.legality_level,
                        "errors": list(validation.errors),
                    }
                )
            if not validation.valid_moves:
                continue
            normalized_moves = [move for move in (self.normalize_move(move) for move in validation.valid_moves) if move is not None]
            if not normalized_moves:
                continue
            parsed_response = validation.parsed_response if isinstance(validation.parsed_response, dict) else {}
            thinking = str(parsed_response.get("thinking") or "round_evaluation_example")
            payload = {
                "thinking": thinking,
                "moves": normalized_moves,
            }
            content: list[str] = []
            if dynamic_prompt:
                content.extend(["INPUT:", *dynamic_prompt.splitlines(), ""])
            content.extend(["OUTPUT:", *json.dumps(payload, ensure_ascii=False, indent=2).splitlines()])
            examples.append(
                {
                    "name": self._move_name(normalized_moves[0]),
                    "content": content,
                    "moves": normalized_moves,
                    "source": "round",
                    "generation": sample_generation,
                    "round_id": round_id,
                    "turn": sample.get("turn"),
                    "validator_passed": True,
                    "legality_level": validation.legality_level,
                }
            )
        return examples, validation_logs

    @staticmethod
    def _round_sample_response_text(sample: dict[str, Any]) -> str:
        raw_response = sample.get("raw_response")
        if isinstance(raw_response, str) and raw_response.strip():
            return raw_response
        parsed_response = sample.get("parsed_response")
        if isinstance(parsed_response, dict):
            return json.dumps(parsed_response, ensure_ascii=False)
        return ""

    def _append_validation_logs(self, records: list[dict[str, Any]]) -> None:
        """Append skipped/invalid response records next to the examples pool."""
        if not records or self.pool_path is None:
            return
        log_path = self.pool_path.with_name("examples_validation.jsonl")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            for record in records:
                payload = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **record,
                }
                stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def sample(self, max_examples: int) -> list[dict[str, Any]]:
        """Sample examples from the runtime JSONL-backed pool."""
        examples = self.examples
        limit = min(max(0, int(max_examples)), len(examples))
        if limit <= 0:
            return []
        return random.sample(examples, limit)

    def load(self) -> None:
        """Load examples from the JSONL pool file when it exists."""
        self.load_from_path(self.pool_path)

    def load_from_path(self, pool_path: str | Path | None, *, replace: bool = False) -> int:
        """Load examples from an explicit JSONL pool path."""
        if replace:
            self._examples_by_key.clear()
        if pool_path is None:
            return 0
        path = Path(pool_path)
        if not path.exists():
            return 0
        loaded: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    loaded.append(record)
        return self.add_examples(loaded)

    def set_pool_path(self, pool_path: str | Path, *, save: bool = True) -> None:
        """Point future writes at a runtime pool file."""
        self.pool_path = Path(pool_path)
        if save:
            self.save()

    def save(self) -> None:
        """Persist the bounded pool to JSONL outside component.json."""
        if self.pool_path is None:
            return
        self.pool_path.parent.mkdir(parents=True, exist_ok=True)
        with self.pool_path.open("w", encoding="utf-8") as stream:
            for example in self.examples:
                stream.write(json.dumps(example, ensure_ascii=False) + "\n")

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
        normalized = {
            "name": name,
            "content": [str(line) for line in content],
            "moves": normalized_moves,
        }
        for key in ("source", "generation", "round_id", "turn", "validator_passed", "legality_level"):
            if key in example:
                normalized[key] = example.get(key)
        return normalized

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
            "unit_position": [],
            "action_type": "",
        }
        unit_position = normalized.get("unit_position")
        position_key = ",".join(str(value) for value in unit_position) if isinstance(unit_position, list) else ""
        return (
            normalized["raw_move"].strip().lower(),
            position_key,
            normalized["action_type"].strip().lower(),
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
