"""Deterministic full-agent behavior signatures over fixed MicroRTS states.

The probe dataset is generated once from configured maps and reference agents.
Candidate evaluation reloads each immutable state, asks a fresh compiled agent
for one action, and hashes a canonical action representation.  These hashes are
diagnostic evidence and a tie-break only; probe failures never change fitness.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Iterable


DATASET_SCHEMA_VERSION = "eagle-semantic-probe-dataset-v1"
SIGNATURE_SCHEMA_VERSION = "eagle-semantic-signature-v1"
NORMALIZATION_VERSION = "microrts-player-action-v1"
PHASES = ("early", "mid", "late")
JAVA_SOURCE = Path(__file__).resolve().parent / "java" / "EAGLESemanticProbe.java"


@dataclass(frozen=True)
class ProbeMap:
    map_id: str
    path: str
    tick_limit: int


@dataclass(frozen=True)
class SemanticDataset:
    root: Path
    manifest: dict[str, Any]

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])

    @property
    def dataset_sha256(self) -> str:
        return str(self.manifest["dataset_sha256"])

    @property
    def probes(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.manifest["probes"])


@dataclass(frozen=True)
class SemanticSignatureResult:
    status: str
    wrapper: dict[str, Any]
    cache_payload: dict[str, Any] | None
    duration_seconds: float

    @property
    def summary(self) -> dict[str, Any]:
        if self.status != "complete" or self.cache_payload is None:
            return {
                "status": "unavailable",
                "reason": str(self.wrapper.get("failure_reason") or "semantic probe unavailable"),
            }
        probes = list(self.cache_payload.get("probe_results") or [])
        return {
            "status": "complete",
            "dataset_id": self.wrapper["dataset_id"],
            "dataset_sha256": self.wrapper["dataset_sha256"],
            "normalization_version": NORMALIZATION_VERSION,
            "probe_ids": [str(item["probe_id"]) for item in probes],
            "action_hashes": [str(item["action_hash"]) for item in probes],
            "global_hash": str(self.cache_payload["global_signature_hash"]),
            "map_hashes": dict(self.cache_payload.get("map_signature_hashes") or {}),
            "phase_hashes": dict(self.cache_payload.get("phase_signature_hashes") or {}),
        }


class SemanticLibrary:
    """Exact-equivalence index for compatible behavioral output vectors.

    LISS compares the complete output vector produced by a program on its
    fixed input set.  EAGLE stores the same evidence as ordered probe/action
    hashes, so the vector is the primary key here.  The global hash fallback
    keeps older compact summaries readable while new signatures remain
    collision-independent at the library boundary.
    """

    def __init__(self) -> None:
        self._members: dict[tuple[object, ...], list[str]] = {}

    def add(self, candidate_id: str, summary: dict[str, Any]) -> bool:
        key = _summary_key(summary)
        if key is None:
            return False
        self._members.setdefault(key, []).append(candidate_id)
        return True

    def find_equivalent(self, summary: dict[str, Any]) -> tuple[str, ...]:
        key = _summary_key(summary)
        return () if key is None else tuple(self._members.get(key, ()))

    @property
    def unique_count(self) -> int:
        return len(self._members)

    @property
    def duplicate_count(self) -> int:
        return sum(max(0, len(items) - 1) for items in self._members.values())


def ensure_semantic_dataset(
    *,
    microrts_dir: Path,
    maps: Iterable[ProbeMap],
    output_root: Path,
    reference_agents: tuple[str, str],
    player_side: int,
    phase_fractions: tuple[float, float, float],
    timeout_seconds: float,
) -> SemanticDataset:
    """Create or validate the immutable configured map × phase dataset."""

    microrts_dir = microrts_dir.resolve()
    maps = tuple(maps)
    if len(maps) != 3:
        raise ValueError("Semantic probing requires exactly three configured maps.")
    if player_side not in {0, 1}:
        raise ValueError("Semantic probe player_side must be 0 or 1.")
    specification = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "maps": [
            {
                "map_id": item.map_id,
                "path": item.path,
                "tick_limit": item.tick_limit,
                "map_sha256": _hash_file(_resolve_map(microrts_dir, item.path)),
            }
            for item in maps
        ],
        "reference_agents": list(reference_agents),
        "reference_agent_artifacts": [
            _reference_agent_identity(microrts_dir, class_name)
            for class_name in reference_agents
        ],
        "player_side": player_side,
        "phase_fractions": list(phase_fractions),
    }
    specification_hash = _sha256_json(specification)
    dataset_id = f"semantic-probes-{specification_hash[:16]}"
    dataset_root = output_root.resolve() / dataset_id
    manifest_path = dataset_root / "manifest.json"
    if manifest_path.is_file():
        manifest = _read_object(manifest_path)
        _validate_dataset(dataset_root, manifest, expected_specification_hash=specification_hash)
        return SemanticDataset(dataset_root, manifest)

    dataset_root.mkdir(parents=True, exist_ok=True)
    helper_classes = dataset_root / ".helper_classes"
    _compile_helper(
        microrts_dir,
        helper_classes,
        timeout_seconds,
        source_class_names=reference_agents,
    )
    probes: list[dict[str, Any]] = []
    for item in maps:
        targets = tuple(max(1, int(round(item.tick_limit * value))) for value in phase_fractions)
        map_output = dataset_root / "states" / item.map_id
        map_output.mkdir(parents=True, exist_ok=True)
        command = [
            "java", "-cp", _classpath(microrts_dir, helper_classes),
            "EAGLESemanticProbe", "generate", str(_resolve_map(microrts_dir, item.path)),
            str(map_output), str(player_side), str(item.tick_limit),
            *(str(value) for value in targets), *reference_agents,
        ]
        completed = _run(command, cwd=microrts_dir, timeout_seconds=timeout_seconds)
        rows = _parse_prefixed_rows(completed.stdout, "EAGLE_STATE", expected_columns=4)
        by_phase = {row[0]: row for row in rows}
        for phase, target_cycle in zip(PHASES, targets, strict=True):
            if phase not in by_phase:
                raise RuntimeError(f"Semantic dataset generator omitted {item.map_id}/{phase}.")
            _, emitted_target, actual_cycle, encoded_path = by_phase[phase]
            state_path = Path(base64.b64decode(encoded_path).decode("utf-8")).resolve()
            state_path.relative_to(dataset_root)
            probes.append({
                "probe_id": f"{item.map_id}:{phase}:p{player_side}",
                "map_id": item.map_id,
                "map_path": item.path,
                "map_sha256": next(row["map_sha256"] for row in specification["maps"] if row["map_id"] == item.map_id),
                "phase": phase,
                "phase_fraction": phase_fractions[PHASES.index(phase)],
                "target_cycle": int(emitted_target),
                "actual_cycle": int(actual_cycle),
                "player_side": player_side,
                "state_path": str(state_path.relative_to(dataset_root)),
                "state_sha256": _hash_file(state_path),
            })
    if len(probes) != 9:
        raise RuntimeError(f"Expected exactly 9 semantic probes, produced {len(probes)}.")
    manifest_core = {
        **specification,
        "dataset_id": dataset_id,
        "specification_sha256": specification_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_count": len(probes),
        "probes": probes,
    }
    manifest = {**manifest_core, "dataset_sha256": _sha256_json(_dataset_hash_core(manifest_core))}
    _write_json(manifest_path, manifest)
    _validate_dataset(dataset_root, manifest, expected_specification_hash=specification_hash)
    return SemanticDataset(dataset_root, manifest)


def evaluate_semantic_signature(
    *,
    candidate_id: str,
    agent_class: str,
    candidate_classes_dir: Path,
    phenotype_sha256: str,
    dataset: SemanticDataset,
    microrts_dir: Path,
    cache_root: Path,
    timeout_seconds: float,
) -> SemanticSignatureResult:
    """Evaluate one compiled full agent, with a phenotype+dataset cache."""

    started = time.monotonic()
    cache_key = _sha256_json({
        "phenotype_sha256": phenotype_sha256,
        "dataset_sha256": dataset.dataset_sha256,
        "normalization_version": NORMALIZATION_VERSION,
    })
    cache_root = cache_root.resolve()
    cache_path = cache_root / f"{cache_key}.json"
    cache_ref = str(cache_path.relative_to(cache_root.parent.parent))
    wrapper_base = {
        "schema_version": SIGNATURE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "phenotype_sha256": phenotype_sha256,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "dataset_id": dataset.dataset_id,
        "dataset_sha256": dataset.dataset_sha256,
        "normalization_version": NORMALIZATION_VERSION,
        "cache_key": cache_key,
        "cache_ref": cache_ref,
    }
    if cache_path.is_file():
        try:
            payload = _read_object(cache_path)
            _validate_cache(payload, cache_key=cache_key, dataset=dataset)
            return SemanticSignatureResult(
                "complete",
                {**wrapper_base, "status": "complete", "cache_hit": True,
                 "global_signature_hash": payload["global_signature_hash"]},
                payload,
                max(0.0, time.monotonic() - started),
            )
        except (OSError, ValueError, KeyError) as exc:
            return SemanticSignatureResult(
                "unavailable",
                {**wrapper_base, "status": "unavailable", "cache_hit": True,
                 "failure_reason": f"invalid semantic cache: {type(exc).__name__}: {exc}"},
                None,
                max(0.0, time.monotonic() - started),
            )

    try:
        helper_classes = dataset.root / ".helper_classes"
        _compile_helper(microrts_dir.resolve(), helper_classes, timeout_seconds)
        command = [
            "java", "-cp", _classpath(microrts_dir.resolve(), helper_classes, candidate_classes_dir.resolve()),
            "EAGLESemanticProbe", "evaluate", agent_class,
        ]
        for probe in dataset.probes:
            command.extend((
                str(probe["probe_id"]),
                str((dataset.root / str(probe["state_path"])).resolve()),
                str(probe["player_side"]),
            ))
        completed = _run(command, cwd=microrts_dir.resolve(), timeout_seconds=timeout_seconds)
        rows = _parse_prefixed_rows(completed.stdout, "EAGLE_ACTION", expected_columns=2)
        actions_by_probe = {row[0]: json.loads(base64.b64decode(row[1]).decode("utf-8")) for row in rows}
        probe_results: list[dict[str, Any]] = []
        for probe in dataset.probes:
            probe_id = str(probe["probe_id"])
            if probe_id not in actions_by_probe:
                raise RuntimeError(f"Semantic probe output omitted {probe_id}.")
            actions = actions_by_probe[probe_id]
            canonical = _canonical_json(actions)
            probe_results.append({
                "probe_id": probe_id,
                "map_id": probe["map_id"],
                "phase": probe["phase"],
                "player_side": probe["player_side"],
                "canonical_actions": actions,
                "action_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            })
        global_hash = _signature_hash(probe_results)
        map_hashes = {
            map_id: _signature_hash(item for item in probe_results if item["map_id"] == map_id)
            for map_id in dict.fromkeys(str(item["map_id"]) for item in probe_results)
        }
        phase_hashes = {
            phase: _signature_hash(item for item in probe_results if item["phase"] == phase)
            for phase in PHASES
        }
        payload = {
            "schema_version": SIGNATURE_SCHEMA_VERSION,
            "cache_key": cache_key,
            "phenotype_sha256": phenotype_sha256,
            "dataset_id": dataset.dataset_id,
            "dataset_sha256": dataset.dataset_sha256,
            "normalization_version": NORMALIZATION_VERSION,
            "probe_results": probe_results,
            "global_signature_hash": global_hash,
            "map_signature_hashes": map_hashes,
            "phase_signature_hashes": phase_hashes,
        }
        cache_root.mkdir(parents=True, exist_ok=True)
        _write_json(cache_path, payload)
        return SemanticSignatureResult(
            "complete",
            {**wrapper_base, "status": "complete", "cache_hit": False,
             "global_signature_hash": global_hash},
            payload,
            max(0.0, time.monotonic() - started),
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return SemanticSignatureResult(
            "unavailable",
            {**wrapper_base, "status": "unavailable", "cache_hit": False,
             "failure_reason": f"{type(exc).__name__}: {exc}"},
            None,
            max(0.0, time.monotonic() - started),
        )


def unavailable_semantic_signature(reason: str) -> SemanticSignatureResult:
    return SemanticSignatureResult(
        "unavailable",
        {"schema_version": SIGNATURE_SCHEMA_VERSION, "status": "unavailable", "failure_reason": reason},
        None,
        0.0,
    )


def _compile_helper(
    microrts_dir: Path,
    output_dir: Path,
    timeout_seconds: float,
    *,
    source_class_names: tuple[str, ...] = (),
) -> None:
    class_file = output_dir / "EAGLESemanticProbe.class"
    supplemental_sources: list[Path] = []
    supplemental_classes: list[Path] = []
    for class_name in source_class_names:
        relative = Path(*class_name.split("."))
        runtime_class = (microrts_dir / "bin" / relative).with_suffix(".class")
        source = (microrts_dir / "src" / relative).with_suffix(".java")
        helper_class = (output_dir / relative).with_suffix(".class")
        if not runtime_class.is_file() and source.is_file():
            supplemental_sources.append(source)
            supplemental_classes.append(helper_class)
    if (
        class_file.is_file()
        and class_file.stat().st_mtime_ns >= JAVA_SOURCE.stat().st_mtime_ns
        and all(
            helper_class.is_file()
            and helper_class.stat().st_mtime_ns >= source.stat().st_mtime_ns
            for source, helper_class in zip(
                supplemental_sources, supplemental_classes, strict=True
            )
        )
    ):
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = [str(JAVA_SOURCE), *(str(path.resolve()) for path in supplemental_sources)]
    _run(
        ["javac", "-cp", _classpath(microrts_dir), "-d", str(output_dir), *sources],
        cwd=microrts_dir,
        timeout_seconds=timeout_seconds,
    )


def _classpath(microrts_dir: Path, *entries: Path) -> str:
    return os.pathsep.join([
        *(str(item.resolve()) for item in entries),
        str(microrts_dir / "bin"),
        str(microrts_dir / "lib" / "*"),
    ])


def _run(command: list[str], *, cwd: Path, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True,
        timeout=timeout_seconds, check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(message)
    return completed


def _parse_prefixed_rows(stdout: str, prefix: str, *, expected_columns: int) -> list[list[str]]:
    marker = prefix + "\t"
    rows = [line[len(marker):].split("\t") for line in stdout.splitlines() if line.startswith(marker)]
    if any(len(row) != expected_columns for row in rows):
        raise RuntimeError(f"Malformed {prefix} output.")
    return rows


def _validate_dataset(root: Path, manifest: dict[str, Any], *, expected_specification_hash: str) -> None:
    if manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise ValueError("Unsupported semantic dataset schema.")
    if manifest.get("specification_sha256") != expected_specification_hash:
        raise ValueError("Semantic dataset configuration does not match its directory.")
    probes = manifest.get("probes")
    if not isinstance(probes, list) or len(probes) != 9:
        raise ValueError("Semantic dataset must contain exactly nine probes.")
    if manifest.get("dataset_sha256") != _sha256_json(_dataset_hash_core(manifest)):
        raise ValueError("Semantic dataset manifest hash mismatch.")
    for probe in probes:
        path = (root / str(probe["state_path"])).resolve()
        path.relative_to(root.resolve())
        if _hash_file(path) != probe.get("state_sha256"):
            raise ValueError(f"Semantic state hash mismatch: {probe.get('probe_id')}.")


def _validate_cache(payload: dict[str, Any], *, cache_key: str, dataset: SemanticDataset) -> None:
    if (
        payload.get("schema_version") != SIGNATURE_SCHEMA_VERSION
        or payload.get("cache_key") != cache_key
        or payload.get("dataset_sha256") != dataset.dataset_sha256
        or len(payload.get("probe_results") or []) != len(dataset.probes)
    ):
        raise ValueError("Semantic signature cache is incompatible or incomplete.")


def _summary_key(summary: dict[str, Any]) -> tuple[object, ...] | None:
    if summary.get("status") != "complete":
        return None
    dataset_id = summary.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        return None
    probe_ids = summary.get("probe_ids")
    action_hashes = summary.get("action_hashes")
    if isinstance(probe_ids, (list, tuple)) and isinstance(action_hashes, (list, tuple)):
        if (
            probe_ids
            and len(probe_ids) == len(action_hashes)
            and all(isinstance(item, str) and item for item in probe_ids)
            and all(isinstance(item, str) and item for item in action_hashes)
            and len(set(probe_ids)) == len(probe_ids)
        ):
            return (
                "vector",
                dataset_id,
                str(summary.get("dataset_sha256") or ""),
                str(summary.get("normalization_version") or ""),
                tuple(probe_ids),
                tuple(action_hashes),
            )
    global_hash = summary.get("global_hash")
    if not isinstance(global_hash, str) or not global_hash:
        return None
    return "hash", dataset_id, global_hash


def _dataset_hash_core(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in manifest.items()
        if key not in {"dataset_sha256", "generated_at"}
    }


def _signature_hash(items: Iterable[dict[str, Any]]) -> str:
    value = [{"probe_id": item["probe_id"], "action_hash": item["action_hash"]} for item in items]
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _resolve_map(microrts_dir: Path, path: str) -> Path:
    value = Path(path)
    resolved = value.resolve() if value.is_absolute() else (microrts_dir / value).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"MicroRTS semantic probe map not found: {resolved}")
    return resolved


def _reference_agent_identity(microrts_dir: Path, class_name: str) -> dict[str, str]:
    relative = Path(*class_name.split("."))
    candidates = (
        (microrts_dir / "bin" / relative).with_suffix(".class"),
        (microrts_dir / "src" / relative).with_suffix(".java"),
    )
    artifact = next((path for path in candidates if path.is_file()), None)
    if artifact is None:
        raise FileNotFoundError(
            f"Semantic reference-agent artifact not found for {class_name}."
        )
    return {
        "class_name": class_name,
        "path": str(artifact.relative_to(microrts_dir)),
        "sha256": _hash_file(artifact),
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
