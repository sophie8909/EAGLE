"""Offline semantic-signature analysis for canonical EAGLE runs.

This module is intentionally a reader.  It never compiles candidates or
backfills missing semantic evidence; it summarizes the versioned candidate
wrappers and their referenced run-local cache records.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from eagle.analysis.loader import RunData


SEMANTIC_ANALYSIS_SCHEMA_VERSION = "eagle-semantic-analysis-v1"
SEMANTIC_WRAPPER_PATH = Path("evaluation/semantic_signature.json")

_CANDIDATE_FIELDS = (
    "candidate_id", "birth_generation", "candidate_status", "semantic_status",
    "unavailable_reason", "operator", "mutation_type", "parent_ids",
    "strategy_parent_id", "generation_prompt_parent_id", "java_parent_id",
    "source_candidate_ids", "phenotype_sha256", "dataset_schema_version",
    "dataset_id", "dataset_sha256", "normalization_version", "cache_key",
    "cache_ref", "cache_hit", "global_signature_hash", "wrapper_path",
)
_PROBE_FIELDS = (
    "candidate_id", "birth_generation", "probe_index", "probe_id", "map_id",
    "phase", "player_side", "action_hash", "canonical_actions",
)
_UNIQUENESS_FIELDS = (
    "population_scope", "generation", "scope_kind", "scope_id",
    "candidate_count", "usable_signature_count", "unique_signature_count",
    "duplicate_candidate_count", "uniqueness_ratio",
    "largest_equivalence_class",
)


def analyze_semantics(
    data: RunData,
    *,
    output_name: str = "analysis",
    dataset_path: str | Path | None = None,
) -> Path:
    """Summarize existing semantic evidence for all candidates and snapshots."""

    output = data.run_dir / output_name
    output.mkdir(parents=True, exist_ok=True)
    expected_dataset = _load_dataset_identity(dataset_path)
    candidates, probe_rows, signatures = _load_candidates(
        data.run_dir,
        expected_dataset=expected_dataset,
    )
    candidate_by_id = {str(item["candidate_id"]): item for item in candidates}

    uniqueness_rows: list[dict[str, Any]] = []
    all_ids = [str(item["candidate_id"]) for item in candidates]
    all_summary = _scope_summary(all_ids, signatures)
    uniqueness_rows.extend(
        _uniqueness_rows("all_candidates", None, all_ids, all_summary)
    )

    snapshot_summaries: list[dict[str, Any]] = []
    for snapshot in data.generations:
        generation = snapshot.get("generation")
        candidate_ids = _snapshot_candidate_ids(snapshot)
        summary = _scope_summary(candidate_ids, signatures)
        uniqueness_rows.extend(
            _uniqueness_rows(
                "survivor_snapshot", generation, candidate_ids, summary
            )
        )
        snapshot_summaries.append({
            "generation": generation,
            "candidate_ids": candidate_ids,
            **summary,
        })

    _write_csv(output / "semantic_candidates.csv", candidates, _CANDIDATE_FIELDS)
    _write_csv(
        output / "semantic_probe_signatures.csv", probe_rows, _PROBE_FIELDS
    )
    _write_csv(
        output / "semantic_uniqueness.csv", uniqueness_rows, _UNIQUENESS_FIELDS
    )
    library = {
        "schema_version": SEMANTIC_ANALYSIS_SCHEMA_VERSION,
        "run_dir": str(data.run_dir),
        "dataset_override": expected_dataset,
        "candidate_count": len(candidates),
        "available_candidate_count": sum(
            item["semantic_status"] == "available" for item in candidates
        ),
        "unavailable_candidate_count": sum(
            item["semantic_status"] != "available" for item in candidates
        ),
        "candidates": [
            {
                key: item.get(key)
                for key in (
                    "candidate_id", "birth_generation", "semantic_status",
                    "unavailable_reason", "parent_ids", "strategy_parent_id",
                    "generation_prompt_parent_id", "java_parent_id",
                    "source_candidate_ids", "global_signature_hash",
                )
            }
            for item in candidates
        ],
        "all_candidates": {
            "candidate_ids": all_ids,
            **all_summary,
        },
        "survivor_snapshots": snapshot_summaries,
        "unknown_snapshot_candidate_ids": sorted({
            candidate_id
            for snapshot in snapshot_summaries
            for candidate_id in snapshot["candidate_ids"]
            if candidate_id not in candidate_by_id
        }),
    }
    (output / "semantic_library.json").write_text(
        json.dumps(library, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def _load_candidates(
    run_dir: Path,
    *,
    expected_dataset: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    signatures: dict[str, dict[str, Any]] = {}
    candidates_dir = run_dir / "candidates"
    if not candidates_dir.is_dir():
        return candidates, probes, signatures

    for candidate_dir in sorted(
        (path for path in candidates_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        candidate = _read_object(candidate_dir / "candidate.json") or {}
        lineage = _read_object(candidate_dir / "lineage.json") or {}
        candidate_id = str(
            candidate.get("candidate_id") or candidate.get("id") or candidate_dir.name
        )
        row = _candidate_base_row(candidate_id, candidate, lineage, candidate_dir, run_dir)
        wrapper_path = candidate_dir / SEMANTIC_WRAPPER_PATH
        if not wrapper_path.is_file():
            row.update(semantic_status="unavailable", unavailable_reason="missing_wrapper")
            candidates.append(row)
            continue
        try:
            wrapper = _read_object(wrapper_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            row.update(
                semantic_status="unavailable",
                unavailable_reason=f"invalid_wrapper:{type(exc).__name__}",
            )
            candidates.append(row)
            continue
        if wrapper is None:
            row.update(semantic_status="unavailable", unavailable_reason="invalid_wrapper")
            candidates.append(row)
            continue

        identity = _dataset_identity(wrapper)
        row.update({
            "phenotype_sha256": wrapper.get("phenotype_sha256"),
            **identity,
            "normalization_version": (
                wrapper.get("normalization_version")
                or wrapper.get("action_normalization_version")
            ),
            "cache_key": wrapper.get("cache_key"),
            "cache_ref": wrapper.get("cache_ref") or wrapper.get("cache_artifact"),
            "cache_hit": wrapper.get("cache_hit"),
            "global_signature_hash": wrapper.get("global_signature_hash"),
        })
        if not _dataset_matches(identity, expected_dataset):
            row.update(
                semantic_status="unavailable",
                unavailable_reason="dataset_override_mismatch",
            )
            candidates.append(row)
            continue
        wrapper_status = str(wrapper.get("status") or "success").lower()
        if wrapper_status not in {"success", "available", "complete", "completed"}:
            row.update(
                semantic_status="unavailable",
                unavailable_reason=str(
                    wrapper.get("error") or wrapper.get("failure_reason") or wrapper_status
                ),
            )
            candidates.append(row)
            continue
        try:
            cache = _load_cache(run_dir, candidate_dir, wrapper)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            row.update(
                semantic_status="unavailable",
                unavailable_reason=f"invalid_cache:{type(exc).__name__}",
            )
            candidates.append(row)
            continue
        if cache is None:
            row.update(semantic_status="unavailable", unavailable_reason="missing_cache")
            candidates.append(row)
            continue

        probe_items = _probe_items(cache)
        if not probe_items:
            row.update(semantic_status="unavailable", unavailable_reason="empty_signature")
            candidates.append(row)
            continue
        normalized = []
        for index, probe in enumerate(probe_items):
            item = _normalize_probe(probe, index)
            normalized.append(item)
            probes.append({
                "candidate_id": candidate_id,
                "birth_generation": row["birth_generation"],
                **item,
                "canonical_actions": _canonical_json(item["canonical_actions"]),
            })
        signature = _candidate_signature(normalized, dataset_identity=identity)
        signatures[candidate_id] = signature
        row.update(
            semantic_status="available",
            unavailable_reason="",
            global_signature_hash=(
                wrapper.get("global_signature_hash")
                or cache.get("global_signature_hash")
                or signature["global"]["signature_hash"]
            ),
        )
        candidates.append(row)
    return candidates, probes, signatures


def _candidate_base_row(
    candidate_id: str,
    candidate: dict[str, Any],
    lineage: dict[str, Any],
    candidate_dir: Path,
    run_dir: Path,
) -> dict[str, Any]:
    def value(key: str, default: Any = None) -> Any:
        return lineage.get(key, candidate.get(key, default))

    return {
        "candidate_id": candidate_id,
        "birth_generation": candidate.get("generation", lineage.get("generation")),
        "candidate_status": candidate.get("status"),
        "semantic_status": "unavailable",
        "unavailable_reason": "",
        "operator": candidate.get("operator", lineage.get("operator")),
        "mutation_type": candidate.get("mutation_type", lineage.get("mutation_type")),
        "parent_ids": _canonical_json(value("parent_ids", [])),
        "strategy_parent_id": value("strategy_parent_id"),
        "generation_prompt_parent_id": value("generation_prompt_parent_id"),
        "java_parent_id": value("java_parent_id"),
        "source_candidate_ids": _canonical_json(value("source_candidate_ids", [])),
        "phenotype_sha256": None,
        "dataset_schema_version": None,
        "dataset_id": None,
        "dataset_sha256": None,
        "normalization_version": None,
        "cache_key": None,
        "cache_ref": None,
        "cache_hit": None,
        "global_signature_hash": None,
        "wrapper_path": str((candidate_dir / SEMANTIC_WRAPPER_PATH).relative_to(run_dir)),
    }


def _load_cache(
    run_dir: Path,
    candidate_dir: Path,
    wrapper: dict[str, Any],
) -> dict[str, Any] | None:
    cache_ref = wrapper.get("cache_ref") or wrapper.get("cache_artifact")
    if not cache_ref:
        embedded = wrapper.get("cache_payload")
        return embedded if isinstance(embedded, dict) else None
    relative = Path(str(cache_ref))
    if relative.is_absolute():
        raise ValueError("semantic cache reference must be run-relative")
    candidates = (run_dir / relative, candidate_dir / relative)
    for path in candidates:
        resolved = path.resolve()
        try:
            resolved.relative_to(run_dir.resolve())
        except ValueError:
            continue
        payload = _read_object(resolved)
        if payload is not None:
            return payload
    return None


def _probe_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("probe_results", "probes", "actions_by_probe"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    signature = payload.get("signature")
    if isinstance(signature, dict):
        return _probe_items(signature)
    return []


def _normalize_probe(probe: dict[str, Any], index: int) -> dict[str, Any]:
    actions = probe.get("canonical_actions", probe.get("actions", []))
    if actions is None:
        actions = []
    action_hash = probe.get("action_hash") or _sha256(_canonical_json(actions))
    return {
        "probe_index": index,
        "probe_id": str(probe.get("probe_id") or f"probe_{index:03d}"),
        "map_id": str(probe.get("map_id") or probe.get("map") or "unknown"),
        "phase": str(probe.get("phase") or "unknown"),
        "player_side": probe.get("player_side"),
        "action_hash": str(action_hash),
        "canonical_actions": actions,
    }


def _candidate_signature(
    probes: list[dict[str, Any]],
    *,
    dataset_identity: dict[str, Any],
) -> dict[str, Any]:
    global_item = _signature_item(probes, dataset_identity=dataset_identity)
    by_map: dict[str, dict[str, Any]] = {}
    by_phase: dict[str, dict[str, Any]] = {}
    for map_id in dict.fromkeys(str(item["map_id"]) for item in probes):
        by_map[map_id] = _signature_item(
            (item for item in probes if str(item["map_id"]) == map_id),
            dataset_identity=dataset_identity,
        )
    for phase in dict.fromkeys(str(item["phase"]) for item in probes):
        by_phase[phase] = _signature_item(
            (item for item in probes if str(item["phase"]) == phase),
            dataset_identity=dataset_identity,
        )
    return {"global": global_item, "by_map": by_map, "by_phase": by_phase}


def _signature_item(
    probes: Iterable[dict[str, Any]],
    *,
    dataset_identity: dict[str, Any],
) -> dict[str, Any]:
    canonical = {
        "dataset": dataset_identity,
        "probes": [
            {
                "probe_id": item["probe_id"],
                "actions": item["canonical_actions"],
            }
            for item in probes
        ],
    }
    key = _canonical_json(canonical)
    return {"equivalence_key": key, "signature_hash": _sha256(key)}


def _scope_summary(
    candidate_ids: list[str],
    signatures: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    known_ids = [candidate_id for candidate_id in candidate_ids if candidate_id in signatures]
    return {
        "candidate_count": len(candidate_ids),
        "usable_signature_count": len(known_ids),
        "global": _equivalence_classes(known_ids, signatures, "global", None),
        "by_map": {
            scope_id: _equivalence_classes(known_ids, signatures, "by_map", scope_id)
            for scope_id in sorted({
                scope_id
                for candidate_id in known_ids
                for scope_id in signatures[candidate_id]["by_map"]
            })
        },
        "by_phase": {
            scope_id: _equivalence_classes(known_ids, signatures, "by_phase", scope_id)
            for scope_id in sorted({
                scope_id
                for candidate_id in known_ids
                for scope_id in signatures[candidate_id]["by_phase"]
            })
        },
    }


def _equivalence_classes(
    candidate_ids: list[str],
    signatures: dict[str, dict[str, Any]],
    scope_kind: str,
    scope_id: str | None,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for candidate_id in candidate_ids:
        signature = signatures[candidate_id]
        item = signature[scope_kind] if scope_kind == "global" else signature[scope_kind].get(scope_id)
        if item is None:
            continue
        key = str(item["equivalence_key"])
        grouped.setdefault(key, {
            "signature_hash": item["signature_hash"],
            "candidate_ids": [],
        })["candidate_ids"].append(candidate_id)
    classes = sorted(
        grouped.values(),
        key=lambda item: (str(item["signature_hash"]), item["candidate_ids"]),
    )
    usable = sum(len(item["candidate_ids"]) for item in classes)
    unique = len(classes)
    return {
        "usable_signature_count": usable,
        "unique_signature_count": unique,
        "duplicate_candidate_count": max(0, usable - unique),
        "uniqueness_ratio": round(unique / usable, 6) if usable else 0.0,
        "largest_equivalence_class": max(
            (len(item["candidate_ids"]) for item in classes), default=0
        ),
        "equivalence_classes": classes,
    }


def _uniqueness_rows(
    population_scope: str,
    generation: Any,
    candidate_ids: list[str],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        _uniqueness_row(
            population_scope, generation, "global", "all", len(candidate_ids),
            summary["global"],
        )
    ]
    rows.extend(
        _uniqueness_row(
            population_scope, generation, "map", scope_id, len(candidate_ids), item,
        )
        for scope_id, item in summary["by_map"].items()
    )
    rows.extend(
        _uniqueness_row(
            population_scope, generation, "phase", scope_id, len(candidate_ids), item,
        )
        for scope_id, item in summary["by_phase"].items()
    )
    return rows


def _uniqueness_row(
    population_scope: str,
    generation: Any,
    scope_kind: str,
    scope_id: str,
    candidate_count: int,
    item: dict[str, Any],
) -> dict[str, Any]:
    return {
        "population_scope": population_scope,
        "generation": generation,
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "candidate_count": candidate_count,
        **{key: item[key] for key in (
            "usable_signature_count", "unique_signature_count",
            "duplicate_candidate_count", "uniqueness_ratio",
            "largest_equivalence_class",
        )},
    }


def _snapshot_candidate_ids(snapshot: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in snapshot.get("population") or []:
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("candidate_id") or item.get("id")
        if candidate_id is not None:
            result.append(str(candidate_id))
    return result


def _load_dataset_identity(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    manifest_path = Path(path).expanduser().resolve()
    if manifest_path.is_dir():
        manifest_path = manifest_path / "manifest.json"
    payload = _read_object(manifest_path)
    if payload is None:
        raise ValueError(f"Semantic probe dataset is not a JSON object: {manifest_path}")
    identity = _dataset_identity(payload)
    if not identity.get("dataset_sha256"):
        identity["dataset_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    identity["manifest_path"] = str(manifest_path)
    return identity


def _dataset_identity(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("dataset")
    source = nested if isinstance(nested, dict) else payload
    return {
        "dataset_schema_version": (
            source.get("schema_version") or source.get("dataset_schema_version")
        ),
        "dataset_id": source.get("dataset_id"),
        "dataset_sha256": source.get("dataset_sha256"),
    }


def _dataset_matches(
    actual: dict[str, Any],
    expected: dict[str, Any] | None,
) -> bool:
    if expected is None:
        return True
    for key in ("dataset_schema_version", "dataset_id", "dataset_sha256"):
        expected_value = expected.get(key)
        if expected_value is not None and actual.get(key) != expected_value:
            return False
    return True


def _read_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: tuple[str, ...],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
