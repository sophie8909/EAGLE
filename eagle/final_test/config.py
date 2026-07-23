"""Independent, deterministic configuration for champion final tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from eagle.config import parse_minimal_yaml

from . import FINAL_TEST_SCHEMA_VERSION
from eagle.opponents import FINAL_TEST_ROSTER


@dataclass(frozen=True)
class FinalTestMap:
    path: str
    max_cycles: int

    @property
    def map_id(self) -> str:
        return Path(self.path).stem


@dataclass(frozen=True)
class FinalTestConfig:
    schema_version: str
    opponent_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    maps: tuple[FinalTestMap, ...]
    subprocess_timeout_seconds: float
    matches_per_opponent: int
    player_sides: tuple[int, ...]
    player_side_policy: str
    output_directory: str
    failure_policy: str
    microrts_dir: Path
    resolved_opponents_manifest: Path
    raw_config: str = ""

    @classmethod
    def from_file(cls, path: Path, *, repository_root: Path | None = None) -> "FinalTestConfig":
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw) if path.suffix.lower() == ".json" else parse_minimal_yaml(raw)
        return cls.from_mapping(payload, raw_config=raw, repository_root=repository_root)

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        *,
        raw_config: str = "",
        repository_root: Path | None = None,
    ) -> "FinalTestConfig":
        root = (repository_root or Path.cwd()).resolve()
        map_paths = tuple(str(value) for value in payload.get("maps", ()))
        cycles = tuple(int(value) for value in payload.get("cycles_per_map", ()))
        if len(map_paths) != len(cycles):
            raise ValueError("maps and cycles_per_map must have the same length.")
        config = cls(
            schema_version=str(payload.get("final_test_schema_version", "")),
            opponent_ids=tuple(str(value) for value in payload.get("opponent_ids", ())),
            seeds=tuple(int(value) for value in payload.get("deterministic_seeds", ())),
            maps=tuple(FinalTestMap(path, cycle) for path, cycle in zip(map_paths, cycles)),
            subprocess_timeout_seconds=float(payload.get("subprocess_timeout_seconds", 300.0)),
            matches_per_opponent=int(payload.get("matches_per_opponent", 0)),
            player_sides=tuple(int(value) for value in payload.get("player_sides", ())),
            player_side_policy=str(payload.get("player_side_policy", "")),
            output_directory=str(payload.get("output_directory", "final_tests")),
            failure_policy=str(payload.get("failure_policy", "")),
            microrts_dir=_rooted_path(root, payload.get("microrts_dir", "third_party/microrts")),
            resolved_opponents_manifest=_rooted_path(
                root,
                payload.get(
                    "resolved_opponents_manifest",
                    "third_party/final_test_opponents/resolved_manifest.json",
                ),
            ),
            raw_config=raw_config,
        )
        config.validate(repository_root=root)
        return config

    def validate(self, *, repository_root: Path) -> None:
        if self.schema_version != FINAL_TEST_SCHEMA_VERSION:
            raise ValueError(f"final_test_schema_version must be {FINAL_TEST_SCHEMA_VERSION}.")
        if self.opponent_ids != tuple(item.opponent_id for item in FINAL_TEST_ROSTER):
            raise ValueError("Final tests must use exactly the external and basic opponent roster in order.")
        if not self.seeds or len(self.seeds) != len(set(self.seeds)):
            raise ValueError("deterministic_seeds must be a non-empty list of distinct integers.")
        if self.matches_per_opponent != 10:
            raise ValueError("Final tests must run exactly 10 matches per opponent.")
        if len(self.seeds) != self.matches_per_opponent:
            raise ValueError("deterministic_seeds must contain one seed per opponent match.")
        if not self.maps or any(item.max_cycles < 1 for item in self.maps):
            raise ValueError("At least one map with a positive cycle limit is required.")
        map_ids = [item.map_id for item in self.maps]
        if len(map_ids) != len(set(map_ids)):
            raise ValueError("Configured maps must have distinct file stems for artifact IDs.")
        for item in self.maps:
            map_file = self.microrts_dir / item.path
            if not map_file.is_file():
                raise ValueError(f"Configured map is not present in vendored MicroRTS: {map_file}")
        if self.player_sides != (0, 1) or self.player_side_policy != "both_player_sides":
            raise ValueError("Final tests require player_sides [0, 1] and both_player_sides policy.")
        if self.subprocess_timeout_seconds <= 0:
            raise ValueError("subprocess_timeout_seconds must be positive.")
        if self.failure_policy != "complete_all_then_fail":
            raise ValueError("failure_policy must be complete_all_then_fail.")
        output = Path(self.output_directory)
        if output.is_absolute() or ".." in output.parts or output.parts != ("final_tests",):
            raise ValueError("output_directory must be the run-relative final_tests directory.")
        if not self.microrts_dir.is_dir():
            raise ValueError(f"Vendored MicroRTS directory does not exist: {self.microrts_dir}")
        try:
            self.microrts_dir.relative_to(repository_root)
        except ValueError as exc:
            raise ValueError("microrts_dir must remain inside the EAGLE repository.") from exc

    def smoke_subset(self) -> "FinalTestConfig":
        """Return the bounded all-opponent, one-map, one-seed, both-side protocol."""

        return replace(
            self,
            seeds=self.seeds[:2],
            maps=self.maps[:1],
            matches_per_opponent=2,
        )

    def to_resolved_dict(self, *, formal: bool) -> dict[str, Any]:
        return {
            "final_test_schema_version": self.schema_version,
            "formal_final_test": formal,
            "opponent_ids": list(self.opponent_ids),
            "deterministic_seeds": list(self.seeds),
            "maps": [
                {"map_id": item.map_id, "path": item.path, "max_cycles": item.max_cycles}
                for item in self.maps
            ],
            "subprocess_timeout_seconds": self.subprocess_timeout_seconds,
            "matches_per_opponent": self.matches_per_opponent,
            "player_sides": list(self.player_sides),
            "player_side_policy": self.player_side_policy,
            "output_directory": self.output_directory,
            "failure_policy": self.failure_policy,
            "microrts_dir": str(self.microrts_dir),
            "resolved_opponents_manifest": str(self.resolved_opponents_manifest),
        }


def _rooted_path(root: Path, value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()

