"""Canonical offline analysis command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eagle.analysis.loader import load_run, resolve_explicit_run, resolve_latest_run
from eagle.analysis.report import generate_analysis
from eagle.runtime.config import load_runtime_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle analyze")
    parser.add_argument("--runtime-config", default="configs/runtime.yaml")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--latest", action="store_true")
    target.add_argument("--run-dir")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--match")
    parser.add_argument("--match-commentaries", action="store_true")
    parser.add_argument("--commentary", action="store_true")
    args = parser.parse_args(argv)
    try:
        runtime = load_runtime_config(args.runtime_config, validate_files=False)
        run_dir = resolve_latest_run(runtime.run_root) if args.latest else resolve_explicit_run(args.run_dir)
        if args.candidate and (args.match_commentaries or args.commentary):
            return _print_commentary_view(run_dir, args.candidate, args.match, args.commentary)
        print(f"Analyzing run: {run_dir}")
        output = generate_analysis(
            load_run(run_dir),
            output_name=runtime.analysis_output_directory_name,
            force=args.force,
        )
        print(f"Analysis written to: {output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _print_commentary_view(run_dir: Path, candidate_id: str, match_id: str | None, single: bool) -> int:
    candidate_dir = run_dir / "candidates" / candidate_id
    if not candidate_dir.is_dir():
        raise FileNotFoundError(f"Candidate directory does not exist: {candidate_dir}")
    if single and match_id:
        paths = sorted(candidate_dir.rglob("commentary/match_commentary.json"))
        paths = [path for path in paths if match_id in str(path.parent.parent)]
        if not paths:
            raise FileNotFoundError(f"Match commentary does not exist for {match_id}")
        commentary = json.loads(paths[0].read_text(encoding="utf-8"))
        print(f"Match: {paths[0].parent.parent.name}")
        for key in ("match_summary", "timeline", "turning_points", "candidate_strengths", "candidate_weaknesses", "decisive_causes", "strategy_recommendations", "coverage"):
            if key in commentary:
                print(f"{key}: {json.dumps(commentary[key], ensure_ascii=False)}")
        print(f"trace: {paths[0].parent.parent / 'match_trace.jsonl.gz'}")
        return 0
    aggregation_path = candidate_dir / "evaluation" / "commentary_aggregation.json"
    payload = json.loads(aggregation_path.read_text(encoding="utf-8")) if aggregation_path.is_file() else {}
    for opponent in payload.get("opponent_summaries", []):
        for item in opponent.get("representative_matches", [])[:1]:
            print("match={match_id} opponent={opponent} map={map} side={candidate_side} result={result} cause={cause} recommendation={recommendation}".format(
                match_id=item.get("match_id"), opponent=opponent.get("opponent"), map=item.get("map"), candidate_side=item.get("candidate_side"), result=item.get("result"),
                cause=(item.get("decisive_causes") or [{}])[0].get("description", "") if item.get("decisive_causes") else "",
                recommendation=(item.get("recommendations") or [{}])[0].get("recommendation", "") if item.get("recommendations") else "",
            ))
    print(f"commented_matches={payload.get('commented_match_count', 0)} failed_commentaries={payload.get('failed_commentary_count', 0)}")
    return 0
