"""
Record fitness evaluation results and related metadata for each evaluated
individual in a structured format (e.g., JSONL) for later analysis and
visualization.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import EAConfig


class FitnessRecorder:
    """Keep recent evaluation records on disk and a compact prompt-key history."""

    def __init__(self, log_folder: Path, config: EAConfig):
        """Initialize per-run and cross-run history storage."""
        self.log_path = log_folder / "fitness_records.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.records = []
        self.repo_root = Path(__file__).resolve().parents[2]
        self.history_records_path = str(self.repo_root / "history" / "fitness_history.jsonl")
        self.history = []
        self.config = config
        self._load_existing_run_records()
        self.init_from_history()

    def _canonical_prompt_text(self, prompt: Any) -> str:
        """Serialize a prompt into a stable string before hashing."""
        if isinstance(prompt, str):
            return prompt
        return json.dumps(prompt, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _stable_prompt_digest(self, prompt: Any) -> str:
        """Return a cross-run-stable digest for one rendered prompt."""
        prompt_text = self._canonical_prompt_text(prompt)
        return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

    def _read_properties_file(self) -> dict[str, str]:
        """Load the MicroRTS properties file for runtime-context cache keys."""
        properties_path = self.repo_root / "resources" / "config.properties"
        properties: dict[str, str] = {}
        if not properties_path.exists():
            return properties

        with properties_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                properties[key.strip()] = value.strip()
        return properties

    def _history_key_context(self, opponent: str | None) -> dict[str, Any]:
        """Build the non-prompt context that must match for safe cache reuse."""
        properties = self._read_properties_file()
        return {
            "history_schema_version": 4,
            "opponent": opponent,
            "run_time_per_game_sec": int(self.config.run_time_per_game_sec),
            "resource_advantage_alpha": float(self.config.resource_advantage_alpha),
            "resource_advantage_weights": dict(self.config.resource_advantage_weights),
            "map_location": properties.get("map_location"),
            "max_cycles": properties.get("max_cycles"),
            "eagle_llm_interval": int(self.config.llm_interval),
            "ai1": properties.get("AI1"),
            "ai2": properties.get("AI2"),
        }

    def build_history_key(self, prompt: Any, opponent: str | None) -> dict[str, Any]:
        """Return the full stable cache key for one prompt/evaluation context."""
        return {
            "prompt_digest": self._stable_prompt_digest(prompt),
            "context": self._history_key_context(opponent),
        }

    def _load_existing_run_records(self) -> None:
        """Load existing per-run records so resumed runs keep recent context."""
        if not self.log_path.exists():
            return

        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.records.append(record)
        self.records = self.records[-50:]
    
    def init_from_history(self) -> None:
        """Load previously seen prompt keys so surrogate lookup can reuse them."""
        path = Path(self.history_records_path)
        self.history: list[dict[str, Any]] = []

        if not path.exists():
            return

        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"Warning: invalid JSON at line {line_no} in {path}: {e}")
                    continue

                if not isinstance(record, dict):
                    print(f"Warning: line {line_no} is not a JSON object in {path}")
                    continue

                self.history.append(record)
    
    def add_history_record(self, record: dict[str, Any]):
        """Append a compact history entry to the cross-run history file."""
        self.history.append(record)
        with Path(self.history_records_path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_to_history_entry(self, record: dict[str, Any]):
        """Reduce a full evaluation record to a compact deduplication entry."""
        history_key = self.build_history_key(record["prompt"], record.get("opponent"))
        history_record = {
            "history_key": history_key,
            "fitness_score": record["fitness_score"],
            "evaluation_mode": record.get("evaluation_mode"),
            "opponent": record.get("opponent"),
            "game_time_sec": record.get("game_time_sec"),
            "benchmark_mode": record.get("benchmark_mode"),
            "log_path": record.get("log_path"),
        }
        return history_record

    def find_matching_history(self, prompt: Any, opponent: str | None) -> list[dict[str, Any]]:
        """Return prior history rows for the same prompt/context combination."""
        history_key = self.build_history_key(prompt, opponent)
        similar_records = []
        for record in self.history:
            if record.get("history_key") == history_key:
                similar_records.append(record)
        return similar_records

    def record_fitness(self, record: dict[str, Any]):
        """Persist one evaluation record and update the compact history cache."""
        """Example record structure:
        {
            "individual_id": "ind-0",
            "generation": 1,
            "fitness_score": [0.8, 0.5, 0.3],
            "opponent": "SimpleBot",
            "evaluation_time": 12.5,
            "components": {
                "critical_rules": 2,
                "actions": 1,
                "json_schema": 0,
                "field_requirements": 3,
                "examples": 1,
                "role": 0,
                "strategy": {
                    "resource_gathering": 1,
                    "unit_production": 0,
                    "combat_strategy": 2
                    ...
                }
            }
        }
        """
        self.records.append(record)
        
        self.records = self.records[-50:]  # Keep only the most recent rows for local examples.
        
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        if record.get("evaluation_mode") == "real":
            self.add_history_record(self.record_to_history_entry(record))

