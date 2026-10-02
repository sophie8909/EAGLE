"""Preparation and validation for fixed and self-play evaluation opponents."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.compiler import compile_generated_agent
from eagle.opponent_cases import FAILED_OPPONENT_SCORE
from eagle.opponents import (
    ALLINBOT_UPSTREAM_CLASS_NAME,
    OpponentSetupError,
    SEARCH_OPPONENT_REGISTRY,
    SAFE_ALLINBOT_CLASS_NAME,
    rooted_jar_path,
)
from eagle.self_play import expand_self_play_slots

from .records import BoundedGenerationResult, EvaluationOpponent


def _build_self_play_opponents(
    opponent_candidates: list[Candidate],
    *,
    prepared: list[tuple[Candidate, BoundedGenerationResult]],
    config: ExperimentConfig,
    classes_dir: Path,
    mock: bool,
) -> tuple[EvaluationOpponent, ...]:
    """Build a stable ten-slot opponent pool from one population snapshot."""

    prepared_by_id = {candidate.id: result for candidate, result in prepared}
    available = [
        candidate
        for candidate in opponent_candidates
        if (candidate.generated_java and candidate.compile_status == "success")
        or (
            candidate.id in prepared_by_id
            and prepared_by_id[candidate.id].compile_result is not None
            and prepared_by_id[candidate.id].compile_result.ok
        )
    ]
    slots = expand_self_play_slots(available)
    opponents: list[EvaluationOpponent] = []
    for index, candidate in enumerate(slots):
        bounded = prepared_by_id.get(candidate.id)
        source = candidate.generated_java
        if bounded is not None and bounded.generation.assembled_java:
            source = bounded.generation.assembled_java
        if not source:
            continue
        opponent_id = config.lexicase_case_ids[index]
        class_name, classpath = _prepare_self_play_class(
            candidate,
            source=source,
            classes_dir=classes_dir,
            config=config,
            mock=mock,
        )
        opponents.append(EvaluationOpponent(
            opponent_id=opponent_id,
            class_name=class_name,
            classpath_entries=(classpath,),
            weight=1.0,
            display_name=f"Self-play slot {index:03d} ({candidate.id})",
            source_generation=candidate.generation,
            source_candidate_id=candidate.id,
        ))
    return tuple(opponents)


def _prepare_self_play_class(
    candidate: Candidate,
    *,
    source: str,
    classes_dir: Path,
    config: ExperimentConfig,
    mock: bool,
) -> tuple[str, Path]:
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    suffix = hashlib.sha256(f"{candidate.id}:{source_sha256}".encode("utf-8")).hexdigest()[:12]
    unique_class = f"CandidateAgentOpponent_{suffix}"
    class_name = f"ai.generated.{unique_class}"
    source_dir = classes_dir / ".self_play_sources"
    class_dir = classes_dir / ".self_play_opponents" / f"{candidate.id}_{source_sha256[:12]}"
    source_path = source_dir / f"{unique_class}.java"
    source_dir.mkdir(parents=True, exist_ok=True)
    class_dir.parent.mkdir(parents=True, exist_ok=True)
    if not source_path.is_file():
        source_path.write_text(
            re.sub(r"\bCandidateAgent\b", unique_class, source),
            encoding="utf-8",
        )
    if not mock and not (class_dir / "ai" / "generated" / f"{unique_class}.class").is_file():
        result = compile_generated_agent(
            source_path,
            microrts_dir=config.microrts_dir,
            output_dir=class_dir,
            mock=False,
        )
        if not result.ok:
            raise RuntimeError(
                f"failed to compile self-play opponent {candidate.id}: {result.stderr}"
            )
    return class_name, class_dir


def preflight_evaluation_opponents(
    config: ExperimentConfig,
    *,
    mock: bool,
    repository_root: Path | None = None,
) -> None:
    """Fail early when real evolution needs unavailable bundled opponents."""

    if mock:
        return
    repository_root = (repository_root or _repository_root()).resolve()
    for item in SEARCH_OPPONENT_REGISTRY:
        if not item.enabled or not item.jar_path:
            continue
        jar_path = rooted_jar_path(repository_root, item)
        if jar_path is not None and not jar_path.is_file():
            raise OpponentSetupError(f"Bundled evolution opponent JAR is missing: {jar_path}")
        if item.opponent_id == "allinbot":
            manifest_path = repository_root / "third_party" / "gui_opponents" / "resolved_allibot.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OpponentSetupError(f"AlliBot resolution manifest is missing or invalid: {manifest_path}") from exc
            if (
                manifest.get("schema_version") != "eagle-allibot-v2"
                or manifest.get("class_name") != ALLINBOT_UPSTREAM_CLASS_NAME
            ):
                raise OpponentSetupError(
                    "AllInBot resolution manifest does not match its pinned upstream "
                    f"class {ALLINBOT_UPSTREAM_CLASS_NAME}: {manifest_path}"
                )
            digest = hashlib.sha256(jar_path.read_bytes()).hexdigest() if jar_path is not None else ""
            if digest != manifest.get("jar_sha256"):
                raise OpponentSetupError(f"AllInBot JAR hash does not match its resolution manifest: {jar_path}")
            source_lib = repository_root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
            if not any(path.is_file() and path.suffix == ".jar" for path in source_lib.glob("*.jar")):
                raise OpponentSetupError(f"AllInBot upstream libraries are missing: {source_lib}")


def _resolved_static_evaluation_opponents(
    config: ExperimentConfig,
    *,
    mock: bool,
    classes_dir: Path | None = None,
    repository_root: Path | None = None,
) -> tuple[EvaluationOpponent, ...]:
    repository_root = (repository_root or _repository_root()).resolve()
    opponents: list[EvaluationOpponent] = []
    configured_weights = dict(config.evaluation_opponents)
    registry = {item.opponent_id: item for item in SEARCH_OPPONENT_REGISTRY}
    worker_rush_classes = (
        _prepare_worker_rush_opponent(config, classes_dir=classes_dir)
        if not mock and classes_dir is not None
        else None
    )
    safe_allinbot_classes = (
        _prepare_safe_allinbot_opponent(
            config,
            classes_dir=classes_dir,
            repository_root=repository_root,
        )
        if not mock and classes_dir is not None
        else None
    )
    for opponent_id in config.evaluation_opponent_ids:
        item = registry.get(opponent_id)
        if item is None:
            raise OpponentSetupError(f"Configured search opponent is unavailable: {opponent_id}")
        if not item.enabled:
            continue
        classpath_entries: tuple[Path, ...] = ()
        if opponent_id == "workerrush" and worker_rush_classes is not None:
            classpath_entries = (worker_rush_classes,)
        jar_path = rooted_jar_path(repository_root, item)
        if jar_path is not None:
            if not mock and not jar_path.is_file():
                raise OpponentSetupError(f"Bundled evolution opponent JAR is missing: {jar_path}")
            if jar_path.is_file() and not mock:
                classpath_entries = (jar_path,)
                if item.opponent_id == "allinbot":
                    source_lib = repository_root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
                    libraries = tuple(sorted(path.resolve() for path in source_lib.glob("*.jar") if path.is_file()))
                    if not mock and not libraries:
                        raise OpponentSetupError(f"AlliBot upstream libraries are missing: {source_lib}")
                    if safe_allinbot_classes is None:
                        raise OpponentSetupError("SafeAllInBot adapter was not prepared for real evaluation.")
                    classpath_entries = (safe_allinbot_classes, jar_path, *libraries)
        opponents.append(EvaluationOpponent(item.opponent_id, item.class_name, classpath_entries, configured_weights[item.opponent_id]))
    return tuple(opponents)


def _prepare_safe_allinbot_opponent(
    config: ExperimentConfig,
    *,
    classes_dir: Path,
    repository_root: Path | None = None,
) -> Path:
    """Compile the fault-containing reflection adapter once per run/final test.

    The adapter deliberately imports no AlliBot classes. The original pinned JAR
    is verified in preflight and stays on the match classpath only for reflective
    runtime delegation.
    """

    repository_root = (repository_root or _repository_root()).resolve()
    root = classes_dir.resolve() / "_opponent_adapters" / "safe_allinbot"
    source = repository_root / "eagle" / "opponent_adapters" / "SafeAllInBot.java"
    output = root / "classes"
    class_file = output / "ai" / "eagle" / "SafeAllInBot.class"
    manifest_path = root / "manifest.json"
    jar_path = repository_root / "third_party" / "gui_opponents" / "jars" / "allibot.jar"
    if not source.is_file():
        raise OpponentSetupError(f"SafeAllInBot adapter source is missing: {source}")
    if not jar_path.is_file():
        raise OpponentSetupError(f"Pinned AllInBot JAR is missing: {jar_path}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    jar_hash = hashlib.sha256(jar_path.read_bytes()).hexdigest()
    if class_file.is_file() and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if (
            manifest.get("source_sha256") == source_hash
            and manifest.get("delegate_class") == ALLINBOT_UPSTREAM_CLASS_NAME
            and manifest.get("upstream_jar_sha256") == jar_hash
        ):
            return output
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    microrts_dir = config.microrts_dir.resolve()
    classpath = os.pathsep.join((str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")))
    completed = subprocess.run(
        ["javac", "-cp", classpath, "-d", str(output), str(source)],
        cwd=microrts_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not class_file.is_file():
        raise OpponentSetupError(
            "SafeAllInBot adapter could not be compiled: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "eagle-search-opponent-source-v1",
                "opponent_id": "allinbot",
                "class_name": SAFE_ALLINBOT_CLASS_NAME,
                "delegate_class": ALLINBOT_UPSTREAM_CLASS_NAME,
                "implementation": "reflection adapter with permanent passive fallback",
                "source_path": str(source),
                "source_sha256": source_hash,
                "upstream_jar_path": str(jar_path),
                "upstream_jar_sha256": jar_hash,
                "classes_dir": str(output),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


def _prepare_worker_rush_opponent(config: ExperimentConfig, *, classes_dir: Path) -> Path:
    """Compile the vendored upstream WorkerRush implementation once per run."""

    root = classes_dir.resolve() / "_opponent_adapters" / "worker_rush"
    source = (
        Path(__file__).resolve().parents[2]
        / "third_party" / "microrts" / "src" / "ai" / "abstraction" / "WorkerRush.java"
    )
    output = root / "classes"
    class_file = output / "ai" / "abstraction" / "WorkerRush.class"
    manifest_path = root / "manifest.json"
    if not source.is_file():
        raise OpponentSetupError(f"Canonical WorkerRush source is missing: {source}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if class_file.is_file() and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if manifest.get("source_sha256") == source_hash:
            return output
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    microrts_dir = config.microrts_dir.resolve()
    classpath = os.pathsep.join((str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")))
    completed = subprocess.run(
        ["javac", "-cp", classpath, "-d", str(output), str(source)],
        cwd=microrts_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not class_file.is_file():
        raise OpponentSetupError(
            "Canonical WorkerRush implementation could not be compiled: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "eagle-search-opponent-source-v1",
                "opponent_id": "workerrush",
                "class_name": "ai.abstraction.WorkerRush",
                "implementation": "vendored drchangliu/MicroRTS WorkerRush",
                "source_url": (
                    "https://github.com/drchangliu/MicroRTS/blob/master/"
                    "src/ai/abstraction/WorkerRush.java"
                ),
                "source_path": str(source),
                "source_sha256": source_hash,
                "classes_dir": str(output),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


def _opponent_display_name(opponent_id: str) -> str:
    for item in SEARCH_OPPONENT_REGISTRY:
        if item.opponent_id == opponent_id:
            return item.display_name
    return opponent_id


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]
