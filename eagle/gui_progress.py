"""Read experiment progress from the CLI's existing console output."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig


_RUN = re.compile(r"^(?:(.+\.ya?ml): )?Run \[(\d+)/(\d+)\] random_seed=(-?\d+)\b", re.IGNORECASE)
_CONFIG = re.compile(r"^\[\d+/\d+\] (.+\.ya?ml)$", re.IGNORECASE)
_GENERATION = re.compile(r"^(?:Generation (\d+)(?:/(\d+))?:|\[gen (\d+)(?:\s|\]))")
_CROSS_GENERATION = re.compile(r"^starting generation=(\d+) candidate=\S+ \((\d+)/(\d+)\)$")


class ExperimentProgress:
    """Retain the active seed after its header scrolls out of the log tail."""

    def __init__(self, target: Path):
        self.target = target
        self.config_name: str | None = None
        self.offset = 0
        self.state: dict[str, int | str] = {"phase": "starting"}
        self._select_config("config.yaml")

    def _select_config(self, name: str) -> None:
        if name == self.config_name or Path(name).name != name:
            return
        self.config_name = name
        self.state = {"phase": "starting"}
        config_path = self.target / name
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return
        if not isinstance(config, dict):
            return
        default = ExperimentConfig.__dataclass_fields__["generations"].default
        total = config.get("generations", default)
        if type(total) is int and total >= 0:
            self.state["total_generations"] = total
        seeds = config.get("random_seeds")
        seed = config.get("random_seed", ExperimentConfig.__dataclass_fields__["random_seed"].default)
        if not (self.target / "manifest.json").is_file() and isinstance(seeds, list) and seeds:
            seed = seeds[0]
        if type(seed) is int:
            self.state["seed"] = seed

    def _observe(self, line: str) -> None:
        if config := _CONFIG.fullmatch(line):
            self._select_config(config[1])
        elif run := _RUN.match(line):
            if run[1]:
                self._select_config(run[1])
            total = self.state.get("total_generations")
            self.state = {"phase": "starting", "seed": int(run[4]), "run_number": int(run[2]), "run_total": int(run[3])}
            if total is not None:
                self.state["total_generations"] = total
        elif cross := _CROSS_GENERATION.fullmatch(line):
            self.state.update(phase="cross_generation", generation=int(cross[1]),
                              benchmark_number=int(cross[2]), benchmark_total=int(cross[3]))
        elif line.startswith("fixed_evaluation_summary="):
            if "benchmark_total" in self.state:
                self.state.update(phase="cross_generation", benchmark_complete=self.state["benchmark_total"])
        elif line.startswith(("Final test:", "final_test_summary=")):
            self.state["phase"] = "final_test"
        elif generation := _GENERATION.match(line):
            number = int(generation[1] or generation[3])
            if generation[2] is not None:
                self.state["total_generations"] = int(generation[2])
            complete = "checkpoint complete" in line or line.startswith(f"[gen {number}] diversity:")
            self.state.update(phase="initialization" if number == 0 else "evolution", generation=number,
                              completed_generation=number if complete else number - 1)

    def read(self, log: Path) -> dict[str, int | str]:
        if not log.is_file():
            return dict(self.state)
        with log.open("rb") as stream:
            stream.seek(self.offset)
            for line in stream:
                if not line.endswith(b"\n"):
                    break
                self.offset += len(line)
                self._observe(line.decode("utf-8", errors="replace").strip())
        return dict(self.state)
