"""Canonical offline analysis command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eagle.analysis.loader import load_run, resolve_explicit_run, resolve_latest_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle analyze")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--latest", action="store_true")
    target.add_argument("--run-dir")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--agent", help="Print Game Performance for one candidate agent across generations.")
    parser.add_argument("--match")
    parser.add_argument("--match-commentaries", action="store_true")
    parser.add_argument("--commentary", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_dir = resolve_latest_run(Path("runs").resolve()) if args.latest else resolve_explicit_run(args.run_dir)
        if args.agent:
            return _print_agent_game_performance(load_run(run_dir), args.agent)
        if args.candidate and (args.match_commentaries or args.commentary):
            return _print_commentary_view(run_dir, args.candidate, args.match, args.commentary)
        from eagle.analysis.report import generate_analysis
        print(f"Analyzing run: {run_dir}")
        output = generate_analysis(
            load_run(run_dir),
            output_name="analysis",
            force=args.force,
        )
        print(f"Analysis written to: {output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _print_agent_game_performance(data, candidate_id: str) -> int:
    from eagle.analysis.report import _agent_game_performance_rows

    rows = [
        {
            "generation": item.get("generation"),
            "candidate_id": item.get("candidate_id"),
            "game_performance": item.get("game_performance"),
        }
        for item in _agent_game_performance_rows(data)
        if str(item.get("candidate_id") or "") == candidate_id
    ]
    if not rows:
        raise ValueError(f"Agent does not exist in run snapshots: {candidate_id}")
    print(json.dumps(sorted(rows, key=lambda item: (item.get("generation", -1), item["candidate_id"])), ensure_ascii=False, indent=2))
    return 0


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
