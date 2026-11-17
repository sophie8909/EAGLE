#!/usr/bin/env python3
"""Create portable run summaries and remove reproducible execution debris.

The source ``runs`` tree is local evidence, not the portable analysis layer.
This command materializes the static analysis report and a short run note,
then keeps only metadata, compact generation snapshots, candidate metadata,
analysis outputs, and evaluation summaries.  It never touches active runs
unless ``--include-active`` is explicitly supplied.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from eagle.analysis.loader import load_run, validate_run_dir
from eagle.analysis.report import generate_analysis


TERMINAL = {"complete", "failed", "interrupted"}
DEFAULT_REMOVE_DIRS = {
    "llm_logs",
    "generated_agents",
    "classes",
    "match_logs",
    "matches",
    "compilation",
    "integration",
}
KEEP_CANDIDATE_FILES = {"candidate.json", "lineage.json", "timing.json"}


def _run_dirs(root: Path) -> list[Path]:
    # Run folders are direct children of runs/, except for named batches such
    # as runs/<batch>/seed_<n>/<timestamp>.  Avoid rglob/glob: candidate
    # evidence can contain millions of files and is irrelevant to discovery.
    found: set[Path] = set()
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if (child / "manifest.json").is_file():
            found.add(child)
            continue
        # Batch folders currently use seed_* children.  Inspect only those
        # bounded levels, never the contents of a run folder.
        for seed_dir in child.iterdir():
            if not seed_dir.is_dir() or not seed_dir.name.startswith("seed_"):
                continue
            for run_dir in seed_dir.iterdir():
                if run_dir.is_dir() and (run_dir / "manifest.json").is_file():
                    found.add(run_dir)
    return sorted(found, key=str)


def _load(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = validate_run_dir(run_dir)
    config = yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError(f"Resolved config is not a mapping: {run_dir / 'config.yaml'}")
    return manifest, config


def _description(run_dir: Path, manifest: dict[str, Any], config: dict[str, Any]) -> str:
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    evaluation = config.get("evaluation") if isinstance(config.get("evaluation"), dict) else {}
    objectives = config.get("objectives") or {}
    objective = ", ".join(str(key) for key in objectives) or "未記錄"
    seed = config.get("random_seed", config.get("seed", "未記錄"))
    generations = config.get("generations", manifest.get("latest_generation", "未記錄"))
    population = config.get("population_size", "未記錄")
    return "\n".join(
        [
            f"# Run {run_dir.name}",
            "",
            "此檔案由 `scripts/compact_runs.py` 產生，作為本 run 的版本索引。",
            "",
            f"- 狀態：{manifest.get('status', 'unknown')}；完成世代：{manifest.get('latest_generation', '未記錄')}",
            f"- 實驗版本：{config.get('experiment_name', manifest.get('experiment_name', '未命名'))}",
            f"- 演化協定：{config.get('evolution_protocol', manifest.get('evolution_protocol', '未記錄'))}",
            f"- Java materialization：{manifest.get('java_materialization_mode', config.get('java_materialization_mode', '未記錄'))}",
            f"- 模型：{manifest.get('model_name', model.get('name', '未記錄'))}",
            f"- seed：{seed}；generations：{generations}；population：{population}",
            f"- evaluation：{evaluation.get('mode', config.get('evaluation_mode', '未記錄'))}；objective：{objective}",
            "",
            "保留：`config.yaml`、`manifest.json`、`summary.json`、generation snapshots、",
            "candidate metadata/lineage、`analysis/`、final/fixed evaluation summaries。",
            "已移除：LLM logs、raw timing stream、Java/class/generated-agent、match/compile/integration 暫存。",
        ]
    ) + "\n"


def _remove_candidate_debris(candidates: Path, dry_run: bool, *, compact_data: bool) -> int:
    removed = 0
    if not candidates.is_dir():
        return removed
    if dry_run:
        return 0
    for candidate_dir in candidates.iterdir():
        if not candidate_dir.is_dir():
            if candidate_dir.is_file() and candidate_dir.name not in KEEP_CANDIDATE_FILES:
                removed += candidate_dir.stat().st_size
                candidate_dir.unlink()
            continue
        for path in candidate_dir.iterdir():
            if path.is_dir():
                if compact_data and not dry_run:
                    shutil.rmtree(path)
                continue
            removable = path.name not in KEEP_CANDIDATE_FILES if compact_data else path.suffix in {".java", ".class"}
            if removable:
                removed += path.stat().st_size
                if not dry_run:
                    path.unlink()
    return removed


def _covered_run_ids(results_root: Path) -> set[str]:
    covered: set[str] = set()
    if not results_root.is_dir():
        return covered
    for manifest_path in results_root.glob("*/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in payload.get("runs", []) if isinstance(payload, dict) else []:
            if isinstance(row, dict) and isinstance(row.get("run_id"), str):
                covered.add(row["run_id"])
        dashboard = payload.get("dashboard", {}) if isinstance(payload, dict) else {}
        for row in dashboard.get("runs", []) if isinstance(dashboard, dict) else []:
            if isinstance(row, dict) and isinstance(row.get("run_id"), str):
                covered.add(row["run_id"])
    return covered


def compact_run(
    run_dir: Path,
    *,
    dry_run: bool,
    include_active: bool,
    covered_run_ids: set[str],
    materialize_analysis: bool,
) -> int:
    manifest, config = _load(run_dir)
    status = str(manifest.get("status", "unknown"))
    if status not in TERMINAL and not include_active:
        print(f"SKIP active/non-terminal: {run_dir} ({status})")
        return 0
    if run_dir.name in covered_run_ids:
        print(f"DELETE covered run: {run_dir}")
        if not dry_run:
            shutil.rmtree(run_dir)
        return 0
    print(f"PROCESS {run_dir} ({status})")
    if not dry_run:
        has_analysis = (run_dir / "analysis" / "run_summary.json").is_file()
        if materialize_analysis and not has_analysis:
            generate_analysis(load_run(run_dir), force=True)
            has_analysis = True
        if not has_analysis:
            print(f"  no existing analysis; preserving source evidence: {run_dir.name}")
        (run_dir / "README.md").write_text(
            _description(run_dir, manifest, config), encoding="utf-8"
        )
    has_analysis = (run_dir / "analysis" / "run_summary.json").is_file()
    removed = _remove_candidate_debris(run_dir / "candidates", dry_run, compact_data=has_analysis)
    for name in DEFAULT_REMOVE_DIRS:
        path = run_dir / name
        if path.exists():
            if not dry_run:
                shutil.rmtree(path)
    timing = run_dir / "timing.jsonl"
    if has_analysis and timing.is_file():
        removed += timing.stat().st_size
        if not dry_run:
            timing.unlink()
    if not dry_run:
        (run_dir / "COMPACTED").write_text(
            "analysis-v2 materialized; raw execution artifacts removed\n",
            encoding="utf-8",
        )
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("runs"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-active", action="store_true")
    parser.add_argument("--results-root", type=Path, default=None)
    parser.add_argument(
        "--materialize-analysis",
        action="store_true",
        help="Generate missing analysis reports before compacting; can be slow for large runs.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    results_root = (args.results_root or root.parent / "results").resolve()
    covered_run_ids = _covered_run_ids(results_root)
    total = 0
    runs = _run_dirs(root)
    print(f"Found {len(runs)} canonical run(s) below {root}")
    for run_dir in runs:
        total += compact_run(
            run_dir,
            dry_run=args.dry_run,
            include_active=args.include_active,
            covered_run_ids=covered_run_ids,
            materialize_analysis=args.materialize_analysis,
        )
    print(f"Bytes scheduled for removal: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
