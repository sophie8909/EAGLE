"""Resolve immutable framework versions back to the run's initial bundle."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from eagle.generation.framework_slots import (
    FRAMEWORK_BUNDLE_SCHEMA_VERSION,
    validate_framework_bundle,
)

if TYPE_CHECKING:
    from eagle.candidate import Candidate
    from eagle.config import ExperimentConfig

FRAMEWORK_REFLECTION_VERSION_SCHEMA = "eagle-framework-reflection-version-v1"
_INITIAL_ARTIFACT = "framework/bundle.json"


def framework_bundle_artifact(run_dir: Path, digest: str) -> str:
    """Return the bundle reference after validating its accepted ancestry."""
    run_dir = run_dir.resolve()

    def read_json(relative: str, *, expected_digest: str | None = None) -> dict:
        path = run_dir / relative
        if not path.resolve().is_relative_to(run_dir):
            raise ValueError("Framework artifact escapes the run directory.")
        if not path.is_file():
            raise ValueError(f"Framework artifact is missing: {relative}")
        data = path.read_bytes()
        if expected_digest is not None and hashlib.sha256(data).hexdigest() != expected_digest:
            raise ValueError("Framework bundle hash mismatch.")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Framework artifact is not valid UTF-8 JSON: {relative}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Framework artifact must contain a JSON object: {relative}")
        return payload

    def check_digest(value: str) -> None:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Framework bundle digest must be 64 lowercase hexadecimal characters.")

    check_digest(digest)
    manifest = read_json("manifest.json")
    initial_digest = manifest.get("framework_bundle_sha256")
    check_digest(initial_digest)
    validate_framework_bundle(read_json(_INITIAL_ARTIFACT, expected_digest=initial_digest))
    if digest == initial_digest:
        return _INITIAL_ARTIFACT
    if manifest.get("framework_evolution_mode", "local") != "reflection":
        raise ValueError("Reflected framework versions require reflection evolution mode.")
    artifact = f"framework/versions/{digest}/bundle.json"
    visited = set()
    current = digest
    while current != initial_digest:
        check_digest(current)
        if current in visited:
            raise ValueError("Framework reflection ancestry contains a cycle.")
        visited.add(current)
        version_dir = f"framework/versions/{current}"
        validate_framework_bundle(read_json(f"{version_dir}/bundle.json", expected_digest=current))
        evidence = read_json(f"{version_dir}/reflection.json")
        if (
            evidence.get("schema_version") != FRAMEWORK_REFLECTION_VERSION_SCHEMA
            or evidence.get("status") != "accepted"
            or evidence.get("bundle_sha256") != current
        ):
            raise ValueError("Framework version lacks accepted reflection evidence.")
        current = evidence.get("parent_bundle_sha256")
    return artifact


def config_for_population(
    config: ExperimentConfig, run_dir: Path, population: Sequence[Candidate],
) -> ExperimentConfig:
    """Bind execution to the single framework in a committed population."""
    if config.java_materialization_mode != "framework_slots":
        return config
    digests = {candidate.framework_bundle_sha256 for candidate in population}
    if len(digests) != 1:
        raise ValueError("Framework population must contain exactly one bundle digest.")
    digest = next(iter(digests))
    artifact = framework_bundle_artifact(run_dir, digest)
    if digest != config.framework_bundle_sha256 and config.framework_evolution_mode != "reflection":
        raise ValueError("Framework population bundle differs from the configured initial bundle.")
    return replace(
        config,
        framework_bundle_path=(run_dir / artifact).resolve(),
        framework_bundle_sha256=digest,
        framework_bundle_version=FRAMEWORK_BUNDLE_SCHEMA_VERSION,
    )
