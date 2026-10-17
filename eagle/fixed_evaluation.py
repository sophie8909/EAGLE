"""Compare saved generation representatives with one fixed, paired benchmark."""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from eagle import final_test
from eagle.analysis.loader import validate_run_dir
from eagle.config import ExperimentConfig
from eagle.evaluation.game_metrics import FAILED_GAME_PERFORMANCE
from eagle.evaluation.match_matrix import canonical_evaluation_maps
from eagle.evaluation.matches import scoring_config_from_experiment
from eagle.evaluation.runtime_evaluation import hash_class_directory, hash_file
from eagle.opponents import rooted_jar_path
from eagle.run_artifacts import GENERATION_SCHEMA_VERSION


SCHEMA_VERSION = "eagle-fixed-evaluation-v1"
ROW_FIELDS = (
    "generation", "candidate_id", "birth_generation", "search_game_performance",
    "status", "expected_matches", "completed_matches", "wins", "losses", "draws",
    "errors", "win_rate", "mean_match_score", "opponent_fault_contained_matches",
    "opponent_fault_recovered_matches", "source_sha256", "summary_path",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle.fixed_evaluation")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--generations", nargs="+", type=int, default=[0, 5, 10, 15, 20])
    parser.add_argument("--seed", type=int, help="Defaults to the run's random_seed.")
    parser.add_argument("--output-dir", type=Path, help="Must be empty; defaults to <run>/fixed_evaluation.")
    args = parser.parse_args(argv)
    run_dir = args.run_dir.expanduser().resolve()
    output_dir = (args.output_dir or run_dir / "fixed_evaluation").expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[1]
    summary: dict[str, Any] | None = None
    try:
        manifest = validate_run_dir(run_dir)
        if manifest.get("status") != "complete":
            raise ValueError("Fixed evaluation requires a complete evolutionary run.")
        generations = sorted(args.generations)
        if generations[0] < 0 or len(generations) != len(set(generations)):
            raise ValueError("Requested generations must be distinct nonnegative integers.")
        completed = manifest.get("completed_generations")
        if completed is not None and not set(generations).issubset(completed):
            raise ValueError("Requested generations must be marked complete in the run manifest.")
        if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
            raise ValueError(f"Refusing to overwrite fixed-evaluation output: {output_dir}")
        config = final_test._load_config(run_dir / "config.yaml", repository_root)
        if args.seed is not None:
            config = replace(config, random_seed=args.seed)
        candidates = [_select_representative(run_dir, generation) for generation in generations]
        final_test.preflight_evaluation_opponents(config, mock=False, repository_root=repository_root)
        protocol = _build_protocol(config, repository_root)
        selections = [
            {"generation": generation, "candidate_id": candidate["candidate_id"],
             "birth_generation": candidate.get("generation"),
             "search_game_performance": candidate["_selection"]["search_game_performance"],
             "source_sha256": hash_file(final_test._candidate_source_path(
                 run_dir / "classes" / candidate["candidate_id"], candidate["candidate_id"],
             ))}
            for generation, candidate in zip(generations, candidates, strict=True)
        ]
        output_dir.mkdir(parents=True, exist_ok=True)
        final_test._atomic_json(output_dir / "protocol.json", protocol)
        summary = {
            "schema_version": SCHEMA_VERSION, "run_dir": str(run_dir),
            "status": "running", "active_generation": None,
            "protocol": protocol, "selections": selections, "rows": [],
        }
        _write_comparison(output_dir, summary)
        for selection, candidate in zip(selections, candidates, strict=True):
            summary["active_generation"] = selection["generation"]
            _write_comparison(output_dir, summary)
            if _build_protocol(config, repository_root) != protocol:
                raise ValueError("Fixed evaluation assets changed after the protocol was frozen.")
            source = final_test._candidate_source_path(
                run_dir / "classes" / candidate["candidate_id"], candidate["candidate_id"],
            )
            if hash_file(source) != selection["source_sha256"]:
                raise ValueError(f"Saved candidate source changed: {source}")
            generation_dir = output_dir / f"generation_{selection['generation']:04d}"
            result = final_test._evaluate_candidate(
                config=config, repository_root=repository_root, run_dir=run_dir,
                candidate=candidate, output_dir=generation_dir, seed_identity=SCHEMA_VERSION,
            )
            result["fixed_evaluation_protocol"] = "../protocol.json"
            result["fixed_evaluation_valid"] = False
            try:
                if _build_protocol(config, repository_root) != protocol or hash_file(source) != selection["source_sha256"]:
                    raise ValueError("Fixed evaluation assets changed during the benchmark.")
                result["fixed_evaluation_valid"] = True
            finally:
                final_test._write_outputs(generation_dir, result)
            row = _comparison_row(selection, result, protocol["matches_per_representative"])
            summary["rows"].append(row)
            _write_comparison(output_dir, summary)
            print(f"generation={selection['generation']} candidate={candidate['candidate_id']} status={row['status']}", flush=True)
        if _build_protocol(config, repository_root) != protocol:
            raise ValueError("Fixed evaluation assets changed during the benchmark.")
        summary["status"] = "complete" if all(row["status"] == "complete" for row in summary["rows"]) else "failed"
        summary["active_generation"] = None
        _write_comparison(output_dir, summary)
        print(f"fixed_evaluation_summary={output_dir / 'fixed_evaluation_summary.json'}")
        return 0 if summary["status"] == "complete" else 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        if summary is not None:
            summary.update(status="failed", error=str(exc))
            _write_comparison(output_dir, summary)
        print(f"ERROR: fixed evaluation failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if summary is not None:
            summary.update(status="interrupted", error="KeyboardInterrupt")
            _write_comparison(output_dir, summary)
        return 130


def _select_representative(run_dir: Path, generation: int) -> dict[str, Any]:
    snapshot = final_test._read_json(run_dir / "generations" / f"generation_{generation:04d}.json")
    if snapshot.get("schema_version") != GENERATION_SCHEMA_VERSION or snapshot.get("generation") != generation:
        raise ValueError(f"Unsupported or mismatched generation snapshot: {generation}")
    ranked = []
    if not isinstance(snapshot.get("population"), list):
        raise ValueError(f"Invalid population in generation {generation}")
    for reference in snapshot.get("population", []):
        if not isinstance(reference, dict):
            raise ValueError(f"Invalid candidate reference in generation {generation}")
        identity = str(reference.get("candidate_id") or reference.get("id") or "")
        if not identity or identity in {".", ".."} or "/" in identity or "\\" in identity or ":" in identity:
            raise ValueError(f"Invalid candidate identity in generation {generation}: {identity!r}")
        candidate_dir = run_dir / "candidates" / identity
        candidate_path = candidate_dir / "candidate.json"
        stored = final_test._read_json(candidate_path) if candidate_path.is_file() else {}
        # Historical survivor fitness/status take precedence over candidate-level metadata.
        candidate = {**stored, **reference, "candidate_id": identity}
        if not final_test._candidate_is_runnable(run_dir, candidate):
            continue
        score = (candidate.get("fitness_objectives") or {}).get("game_performance")
        if score is None:
            game = candidate.get("game_eval_result")
            if not isinstance(game, dict):
                game_path = candidate_dir / "evaluation" / "game_performance.json"
                game = final_test._read_json(game_path) if game_path.is_file() else {}
            score = game.get("game_performance")
        if score is None or not math.isfinite(float(score)) or float(score) == FAILED_GAME_PERFORMANCE:
            continue
        score = float(score)
        candidate["_selection"] = {
            "mode": "generation_game_performance", "requested_generation": generation,
            "selected_generation": generation, "fallback": False,
            "search_game_performance": score,
        }
        ranked.append((score, identity, candidate))
    if not ranked:
        raise ValueError(f"Generation {generation} has no runnable candidate with finite Game Performance.")
    return sorted(ranked, key=lambda item: (-item[0], item[1]))[0][2]


def _build_protocol(config: ExperimentConfig, repository_root: Path) -> dict[str, Any]:
    maps = canonical_evaluation_maps(config.evaluation_maps, tick_limits=config.resolved_evaluation_map_tick_limits)
    opponents = []
    for opponent in final_test.FINAL_TEST_OPPONENTS:
        jar = rooted_jar_path(repository_root, opponent)
        opponents.append({
            "id": opponent.opponent_id, "class": opponent.class_name,
            "jar_sha256": hash_file(jar) if jar is not None else None,
        })
    return {
        "schema_version": SCHEMA_VERSION, "random_seed": config.random_seed,
        "seed_identity": SCHEMA_VERSION,
        "seed_scheme": "derive_match_seed(root, fixed identity, opponent, map, game, side, match index)",
        "opponents": opponents,
        "maps": [
            {"id": item.map_id, "path": item.path, "tick_limit": item.tick_limit,
             "sha256": hash_file(config.microrts_dir / item.path)} for item in maps
        ],
        "games_per_side_per_map": final_test.FINAL_TEST_GAMES_PER_SIDE,
        "matches_per_representative": len(opponents) * len(maps) * final_test.FINAL_TEST_GAMES_PER_SIDE * 2,
        "scoring": scoring_config_from_experiment(config).to_json_dict(),
        "match_timeout_seconds": config.match_timeout_seconds, "match_workers": config.match_workers,
        "microrts_identity": {
            name: hash_class_directory(config.microrts_dir / name) for name in ("src", "bin", "lib")
        },
        "support_identity": {
            name: hash_class_directory(repository_root / name)
            for name in ("eagle/opponent_sources", "eagle/opponent_adapters", "third_party/gui_opponents/src/allibot/lib")
        },
        "worker_rush_source_sha256": hash_file(
            repository_root / "third_party/microrts/src/ai/abstraction/WorkerRush.java"
        ),
    }


def _comparison_row(selection: dict[str, Any], result: dict[str, Any], expected: int) -> dict[str, Any]:
    matches = result["matches"]
    counts = {label: sum(item["result"] == label for item in matches) for label in ("win", "loss", "draw", "error")}
    complete = len(matches) == expected and counts["error"] == 0
    return {
        **selection, "status": "complete" if complete else "failed", "expected_matches": expected,
        "completed_matches": counts["win"] + counts["loss"] + counts["draw"],
        "wins": counts["win"], "losses": counts["loss"], "draws": counts["draw"], "errors": counts["error"],
        "win_rate": counts["win"] / expected if complete else None,
        "mean_match_score": statistics.fmean(item["match"]["score"] for item in matches) if complete else None,
        "opponent_fault_contained_matches": result["opponent_fault_contained_matches"],
        "opponent_fault_recovered_matches": result["opponent_fault_recovered_matches"],
        "summary_path": f"generation_{selection['generation']:04d}/final_test_summary.json",
    }


def _write_comparison(output_dir: Path, summary: dict[str, Any]) -> None:
    final_test._atomic_json(output_dir / "fixed_evaluation_summary.json", summary)
    with (output_dir / "fixed_evaluation_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(summary["rows"])
    lines = [
        "# EAGLE Fixed Evaluation", "", f"Status: {summary['status']}", "",
        "Same opponents, maps, tick caps and paired seeds for every representative; see protocol.json.",
        "Mean match score is unweighted and separate from search fitness. Incomplete matrices have no aggregate score or win rate.",
        "Search score records representative selection only; its original opponent context may differ across generations.",
        "", "| Generation | Candidate | Search score | W/L/D/E | Win rate | Mean match score | Status |",
        "|---:|---|---:|---|---:|---:|---|",
    ]
    for row in summary["rows"]:
        rate = "unavailable" if row["win_rate"] is None else f"{row['win_rate']:.4f}"
        score = "unavailable" if row["mean_match_score"] is None else f"{row['mean_match_score']:.6f}"
        lines.append(
            f"| {row['generation']} | {row['candidate_id']} | {row['search_game_performance']:.6f} | "
            f"{row['wins']}/{row['losses']}/{row['draws']}/{row['errors']} | {rate} | {score} | {row['status']} |"
        )
    if summary.get("error"):
        lines.extend(["", f"Error: {summary['error']}"])
    (output_dir / "fixed_evaluation_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
