"""
Record fitness evaluation results and related metadata for each evaluated individual in a structured format (e.g., JSONL) for later analysis and visualization.
"""

import json
from pathlib import Path
from typing import Any

from .config import EAConfig

class FitnessRecorder:
    def __init__(self, log_folder: Path, config: EAConfig):
        self.log_path = log_folder / "fitness_records.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.records = []
        self.history_records_path =  "fitness_history.jsonl"
        self.history = []  
        self.config = config
        self.init_from_history()
    
    def init_from_history(self) -> None:
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
        self.history.append(record)
        with Path(self.history_records_path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_to_history_entry(self, record: dict[str, Any]):
        # only keep prompt hash and fitness score for history record to save space.
        prompt_hash = hash(json.dumps(record["prompt"], sort_keys=True))
        history_record = {
            "prompt_hash": prompt_hash,
            "fitness_score": record["fitness_score"],
            "max_run_time_sec": self.config.run_time_per_game_sec,
            "opponent": record.get("opponent"),
        }
        return history_record

    def find_matching_history(self, prompt: dict[str, Any], opponent: str | None) -> list[dict[str, Any]]:
        # find similar prompt in history based on prompt hash. return the fitness score if found.
        prompt_hash = hash(json.dumps(prompt, sort_keys=True))
        similar_records = []
        for record in self.history:
            if (
                "prompt_hash" in record
                and record["prompt_hash"] == prompt_hash
                and record["max_run_time_sec"] >= self.config.run_time_per_game_sec
                and record.get("opponent") == opponent
            ):
                similar_records.append(record)
        return similar_records

    def record_fitness(self, record: dict[str, Any]):
        # Append the fitness evaluation record to a JSONL file for later analysis
        # Each record should include the individual's component configuration, fitness score, and any relevant metadata (
        # e.g., opponent faced, generation number, evaluation time)
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
        
        self.records = self.records[-50:]  # Keep only the last 50 records
        
        with self.log_path.open("w", encoding="utf-8") as f:
            f.write("\n".join([json.dumps(r) for r in self.records]))

        self.add_history_record(self.record_to_history_entry(record))

