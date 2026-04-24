"""Persist per-match score records and prompt-keyed history for reuse."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import EAConfig
from ..envs.microrts.compiler import locate_microrts_root
from ..project import HISTORY_DIR, PROJECT_ROOT


class MatchScoreRecorder:
    """Keep recent match-score records on disk and a compact prompt-key history."""

    def __init__(self, log_folder: Path, config: EAConfig):
        self.log_path = log_folder / "match_score_records.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.records: list[dict[str, Any]] = []
        self.repo_root = PROJECT_ROOT
        self.history_records_path = str(HISTORY_DIR / "match_score_history.jsonl")
        self.history: list[dict[str, Any]] = []
        self.config = config
        self._load_existing_run_records()
        self.init_from_history()

    def _canonical_prompt_text(self, prompt: Any) -> str:
        if isinstance(prompt, str):
            return prompt
        return json.dumps(prompt, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _stable_prompt_digest(self, prompt: Any) -> str:
        prompt_text = self._canonical_prompt_text(prompt)
        return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

    def _read_properties_file(self) -> dict[str, str]:
        properties_path = locate_microrts_root(self.repo_root) / "resources" / "config.properties"
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
        properties = self._read_properties_file()
        return {
            "history_schema_version": 5,
            "opponent": opponent,
            "run_time_per_game_sec": int(self.config.run_time_per_game_sec),
            "resource_advantage_alpha": float(self.config.resource_advantage_alpha),
            "win_bonus": float(self.config.win_bonus),
            "resource_advantage_weights": dict(self.config.resource_advantage_weights),
            "map_location": properties.get("map_location"),
            "max_cycles": properties.get("max_cycles"),
            "eagle_llm_interval": int(self.config.active_llm_interval()),
            "ai1": properties.get("AI1"),
            "ai2": properties.get("AI2"),
        }

    def build_history_key(self, prompt: Any, opponent: str | None) -> dict[str, Any]:
        return {
            "prompt_digest": self._stable_prompt_digest(prompt),
            "context": self._history_key_context(opponent),
        }

    def _load_existing_run_records(self) -> None:
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
        path = Path(self.history_records_path)
        self.history = []
        if not path.exists():
            return

        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"Warning: invalid JSON at line {line_no} in {path}: {exc}")
                    continue
                if not isinstance(record, dict):
                    print(f"Warning: line {line_no} is not a JSON object in {path}")
                    continue
                self.history.append(record)

    def add_history_record(self, record: dict[str, Any]) -> None:
        self.history.append(record)
        with Path(self.history_records_path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_to_history_entry(self, record: dict[str, Any]) -> dict[str, Any]:
        history_key = self.build_history_key(record["prompt"], record.get("opponent"))
        return {
            "history_key": history_key,
            "match_score": dict(record["match_score"]),
            "evaluation_mode": record.get("evaluation_mode"),
            "opponent": record.get("opponent"),
            "game_time_sec": record.get("game_time_sec"),
            "benchmark_mode": record.get("benchmark_mode"),
            "log_path": record.get("log_path"),
            "winner": record.get("winner"),
            "timeout": record.get("timeout"),
            "llm_calls": record.get("llm_calls"),
            "parsed_summary": record.get("parsed_summary"),
            "stats": record.get("stats"),
            "llm_interval": record.get("llm_interval"),
            "run_time_per_game_sec": record.get("run_time_per_game_sec"),
            "runner_script": record.get("runner_script"),
            "ai1": record.get("ai1"),
            "ai2": record.get("ai2"),
        }

    def find_matching_history(self, prompt: Any, opponent: str | None) -> list[dict[str, Any]]:
        history_key = self.build_history_key(prompt, opponent)
        return [record for record in self.history if record.get("history_key") == history_key]

    def record_match_score(self, record: dict[str, Any]) -> None:
        if "match_score" not in record:
            raise KeyError("record_match_score requires 'match_score'")

        normalized_record = dict(record)
        normalized_record["match_score"] = dict(record["match_score"])
        self.records.append(normalized_record)
        self.records = self.records[-50:]

        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(normalized_record, ensure_ascii=False) + "\n")

        if normalized_record.get("evaluation_mode") == "real":
            self.add_history_record(self.record_to_history_entry(normalized_record))
