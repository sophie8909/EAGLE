"""Run the post-evolution MicroRTS benchmark and write W/L/D tables.

The final test is deliberately separate from the evolutionary seven-opponent
evaluation.  It reuses the canonical MicroRTS process runner, but expands the
roster with PassiveAI, RandomAI, and RandomBiasedAI and runs ten games for
each map and candidate side.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from eagle.evaluation import (
    _prepare_worker_rush_adapter,
    hash_class_directory,
    hash_file,
    preflight_evaluation_opponents,
    scoring_config_from_experiment,
)
from eagle.opponents import (
    BASIC_OPPONENTS,
    SEARCH_OPPONENT_REGISTRY,
    rooted_jar_path,
)
from evaluation.match_matrix import canonical_evaluation_maps
from evaluation.microrts_runner import integrate_microrts_agent
from evaluation.runtime_evaluation import run_microrts_match
from eagle.config import ExperimentConfig


FINAL_TEST_SCHEMA_VERSION = "eagle-final-test-v1"
FINAL_TEST_GAMES_PER_SIDE = 10
AGENT_CLASS = "ai.generated.CandidateAgent"
FINAL_TEST_OPPONENTS = (*SEARCH_OPPONENT_REGISTRY, *BASIC_OPPONENTS[:3])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eagle.final_test")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--config", type=Path, help="Defaults to the run-local resolved config.yaml.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--candidate-id")
    args = parser.parse_args(argv)

    repository_root = Path(__file__).resolve().parents[1]
    run_dir = args.run_dir.expanduser().resolve()
    config_path = _resolve_path(repository_root, args.config or run_dir / "config.yaml")
    output_dir = (args.output_dir or run_dir / "final_test").expanduser().resolve()

    try:
        config = _load_config(config_path, repository_root)
        candidate = _select_candidate(run_dir, args.candidate_id)
        classes_dir = run_dir / "classes" / candidate["candidate_id"]
        _validate_candidate_artifacts(classes_dir, candidate)
        output_dir.mkdir(parents=True, exist_ok=True)

        preflight_evaluation_opponents(config, mock=False, repository_root=repository_root)
        integration = integrate_microrts_agent(
            microrts_dir=config.microrts_dir,
            classes_dir=classes_dir,
            agent_class=AGENT_CLASS,
            integration_artifacts_dir=output_dir / "integration",
            mock=False,
        )
        if not integration.ok:
            raise RuntimeError(
                "Final-test integration checks failed: "
                f"{integration.failure_reason or 'unknown integration failure'}"
            )

        results = _run_final_matrix(
            config=config,
            repository_root=repository_root,
            candidate=candidate,
            classes_dir=classes_dir,
            output_dir=output_dir,
        )
        summary = _build_summary(
            config=config,
            run_dir=run_dir,
            output_dir=output_dir,
            candidate=candidate,
            integration=integration,
            results=results,
        )
        _write_outputs(output_dir, summary)
        print(_markdown_table(summary))
        print(f"final_test_summary={output_dir / 'final_test_summary.json'}")
        print(f"final_test_csv={output_dir / 'final_test_results.csv'}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: final test failed: {exc}", file=sys.stderr)
        return 2


def _load_config(config_path: Path, repository_root: Path) -> ExperimentConfig:
    config = ExperimentConfig.from_file(config_path)
    microrts_dir = _resolve_path(repository_root, config.microrts_dir)
    return replace(config, microrts_dir=microrts_dir)


def _resolve_path(repository_root: Path, path: str | Path) -> Path:
    value = Path(path).expanduser()
    return value.resolve() if value.is_absolute() else (repository_root / value).resolve()


def _select_candidate(run_dir: Path, candidate_id: str | None) -> dict[str, Any]:
    manifest = _read_json(run_dir / "manifest.json")
    latest = manifest.get("latest_generation")
    if latest is None:
        completed = [int(value) for value in manifest.get("completed_generations", [])]
        latest = max(completed) if completed else None
    if latest is None:
        raise ValueError(f"Run has no completed generation: {run_dir}")
    generation_numbers = list(range(int(latest), -1, -1))
    if candidate_id is not None:
        for generation in generation_numbers:
            candidates = _load_generation_candidates(run_dir, generation)
            by_id = {str(item.get("candidate_id") or item.get("id")): item for item in candidates}
            selected = by_id.get(candidate_id)
            if selected is None:
                continue
            if _candidate_is_runnable(run_dir, selected):
                return selected
            raise ValueError(f"Candidate {candidate_id!r} is not runnable in generation {generation}")
        raise ValueError(f"Candidate {candidate_id!r} is not in the run: {run_dir}")

    summary_best_id: str | None = None
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        best = _read_json(summary_path).get("best_candidate") or {}
        summary_best_id = str(best.get("candidate_id") or "") or None

    for generation in generation_numbers:
        candidates = _load_generation_candidates(run_dir, generation)
        by_id = {str(item.get("candidate_id") or item.get("id")): item for item in candidates}
        if summary_best_id and generation == int(latest):
            selected = by_id.get(summary_best_id)
            if selected is not None and _candidate_is_runnable(run_dir, selected):
                return selected
        runnable = [item for item in candidates if _candidate_is_runnable(run_dir, item)]
        if runnable:
            return max(
                runnable,
                key=lambda item: tuple(
                    float((item.get("fitness_objectives") or {}).get(case, -1000.0))
                    for case in ("lightrush", "heavyrush", "workerrush", "allinbot", "mayari", "coac", "tma")
                ),
            )

    raise ValueError(f"No runnable candidate found in run: {run_dir}")


def _load_generation_candidates(run_dir: Path, generation: int) -> list[dict[str, Any]]:
    snapshot = _read_json(run_dir / "generations" / f"generation_{generation:04d}.json")
    references = [item for item in snapshot.get("population", []) if isinstance(item, dict)]
    candidates = []
    for reference in references:
        identity = str(reference.get("candidate_id") or reference.get("id") or "")
        candidate_path = run_dir / "candidates" / identity / "candidate.json"
        candidate = _read_json(candidate_path) if candidate_path.is_file() else dict(reference)
        candidates.append(candidate)
    return candidates


def _candidate_source_path(classes_dir: Path, candidate_id: str) -> Path:
    candidate_dir = classes_dir.parent.parent / "candidates" / candidate_id
    phenotype = candidate_dir / "phenotype" / "CandidateAgent.java"
    if phenotype.is_file():
        return phenotype
    # Isolated read compatibility for pre-v4 candidate artifacts.
    return candidate_dir / "generation" / "normalized_candidate.java"


def _candidate_is_runnable(run_dir: Path, candidate: dict[str, Any]) -> bool:
    candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "")
    if not candidate_id or candidate.get("status") == "failed":
        return False
    class_file = run_dir / "classes" / candidate_id / "ai" / "generated" / "CandidateAgent.class"
    source = _candidate_source_path(run_dir / "classes" / candidate_id, candidate_id)
    return class_file.is_file() and source.is_file() and source.read_text(encoding="utf-8").strip() != ""


def _validate_candidate_artifacts(classes_dir: Path, candidate: dict[str, Any]) -> None:
    class_file = classes_dir / "ai" / "generated" / "CandidateAgent.class"
    if not class_file.is_file():
        raise ValueError(
            f"Compiled final candidate is missing: {class_file}. "
            "Use a completed EAGLE run with preserved classes/ artifacts."
        )
    candidate_id = str(candidate.get("candidate_id") or candidate.get("id"))
    source = _candidate_source_path(classes_dir, candidate_id)
    if not source.is_file() or not source.read_text(encoding="utf-8").strip():
        raise ValueError(f"Candidate {candidate_id} has no generated Java source artifact.")


def _run_final_matrix(
    *,
    config: ExperimentConfig,
    repository_root: Path,
    candidate: dict[str, Any],
    classes_dir: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    candidate_id = str(candidate.get("candidate_id") or candidate.get("id"))
    candidate_generation = int(candidate.get("generation") or 0)
    source_hash = hash_file(_candidate_source_path(classes_dir, candidate_id))
    class_hash = hash_class_directory(classes_dir)
    maps = canonical_evaluation_maps(config.evaluation_maps)
    scoring_config = scoring_config_from_experiment(config)
    worker_adapter = _prepare_worker_rush_adapter(config, classes_dir=output_dir / "classes")
    opponent_classpaths = {
        item.opponent_id: _opponent_classpath(
            item.opponent_id,
            repository_root=repository_root,
            worker_adapter=worker_adapter,
        )
        for item in FINAL_TEST_OPPONENTS
    }

    results: list[dict[str, Any]] = []
    match_index = 0
    for opponent in FINAL_TEST_OPPONENTS:
        for evaluation_map in maps:
            for game_index in range(FINAL_TEST_GAMES_PER_SIDE):
                for candidate_player in (0, 1):
                    match_dir = (
                        output_dir
                        / "matches"
                        / opponent.opponent_id
                        / evaluation_map.map_id
                        / f"p{candidate_player}"
                        / f"game_{game_index:02d}"
                    )
                    result = run_microrts_match(
                        microrts_dir=config.microrts_dir,
                        classes_dir=classes_dir,
                        agent_class=AGENT_CLASS,
                        opponent=opponent.class_name,
                        tick_limit=config.tick_limit,
                        match_index=match_index,
                        match_artifacts_dir=output_dir / "matches",
                        match_output_dir=match_dir,
                        scoring_config=scoring_config,
                        mock=False,
                        generation_index=candidate_generation,
                        timeout_seconds=config.match_timeout_seconds,
                        map_path=evaluation_map.path,
                        candidate_id=candidate_id,
                        generation=candidate_generation,
                        source_hash=source_hash,
                        class_hash=class_hash,
                        candidate_player=candidate_player,
                        extra_classpath_entries=opponent_classpaths[opponent.opponent_id],
                        artifact_mode="compact",
                        map_id=evaluation_map.map_id,
                        round_index=game_index,
                    )
                    results.append(
                        {
                            "opponent_id": opponent.opponent_id,
                            "opponent_name": opponent.display_name,
                            "map_id": evaluation_map.map_id,
                            "map_path": evaluation_map.path,
                            "candidate_player": candidate_player,
                            "game_index": game_index,
                            "result": _result_label(result),
                            "ok": result.ok,
                            "failure_category": result.failure_category,
                            "failure_reason": result.failure_reason,
                            "match": result.to_json_dict(),
                        }
                    )
                    match_index += 1
    return results


def _opponent_classpath(
    opponent_id: str,
    *,
    repository_root: Path,
    worker_adapter: Path,
) -> tuple[Path, ...]:
    if opponent_id == "workerrush":
        return (worker_adapter,)
    spec = next(item for item in FINAL_TEST_OPPONENTS if item.opponent_id == opponent_id)
    jar_path = rooted_jar_path(repository_root, spec)
    if jar_path is None:
        return ()
    if not jar_path.is_file():
        raise ValueError(f"Opponent JAR is missing for {opponent_id}: {jar_path}")
    entries: list[Path] = [jar_path]
    if opponent_id == "allinbot":
        source_lib = repository_root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
        entries.extend(sorted(path.resolve() for path in source_lib.glob("*.jar") if path.is_file()))
    return tuple(entries)


def _result_label(result: Any) -> str:
    if not result.ok:
        return "error"
    if result.winner not in {0, 1}:
        return "draw"
    return "win" if result.winner == result.candidate_player else "loss"


def _build_summary(
    *,
    config: ExperimentConfig,
    run_dir: Path,
    output_dir: Path,
    candidate: dict[str, Any],
    integration: Any,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for item in results:
        cell = table.setdefault(item["opponent_id"], {}).setdefault(
            item["map_id"], _empty_cell()
        )
        side = f"p{item['candidate_player']}"
        cell[side][item["result"]] += 1
        cell[{"win": "wins", "loss": "losses", "draw": "draws", "error": "errors"}[item["result"]]] += 1
    return {
        "schema_version": FINAL_TEST_SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "candidate": {
            "candidate_id": candidate.get("candidate_id") or candidate.get("id"),
            "generation": candidate.get("generation"),
            "status": candidate.get("status"),
            "fitness_objectives": candidate.get("fitness_objectives", {}),
        },
        "agent_class": AGENT_CLASS,
        "opponents": [
            {"id": item.opponent_id, "name": item.display_name, "class": item.class_name}
            for item in FINAL_TEST_OPPONENTS
        ],
        "maps": [{"id": item.map_id, "path": item.path} for item in canonical_evaluation_maps(config.evaluation_maps)],
        "games_per_side_per_map": FINAL_TEST_GAMES_PER_SIDE,
        "total_matches": len(results),
        "integration": integration.to_json_dict(),
        "table": table,
        "matches": results,
    }


def _empty_cell() -> dict[str, Any]:
    return {
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "errors": 0,
        "p0": {"win": 0, "loss": 0, "draw": 0, "error": 0},
        "p1": {"win": 0, "loss": 0, "draw": 0, "error": 0},
    }


def _write_outputs(output_dir: Path, summary: dict[str, Any]) -> None:
    _atomic_json(output_dir / "final_test_summary.json", summary)
    csv_path = output_dir / "final_test_results.csv"
    rows = []
    for opponent in summary["opponents"]:
        opponent_id = opponent["id"]
        for evaluation_map in summary["maps"]:
            cell = summary["table"][opponent_id][evaluation_map["id"]]
            rows.append(
                {
                    "opponent": opponent_id,
                    "map": evaluation_map["id"],
                    "map_path": evaluation_map["path"],
                    "wins": cell["wins"],
                    "losses": cell["losses"],
                    "draws": cell["draws"],
                    "errors": cell["errors"],
                    "p0_wins": cell["p0"]["win"],
                    "p0_losses": cell["p0"]["loss"],
                    "p0_draws": cell["p0"]["draw"],
                    "p1_wins": cell["p1"]["win"],
                    "p1_losses": cell["p1"]["loss"],
                    "p1_draws": cell["p1"]["draw"],
                }
            )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "final_test_results.md").write_text(_markdown_table(summary) + "\n", encoding="utf-8")


def _markdown_table(summary: dict[str, Any]) -> str:
    maps = summary["maps"]
    lines = [
        f"# EAGLE Final Test — {summary['candidate']['candidate_id']}",
        "",
        f"Each cell contains total `W/L/D/E` across p0 and p1, followed by side-specific counts. "
        f"Each side has {summary['games_per_side_per_map']} games per map.",
        "",
        "| Opponent | " + " | ".join(item["id"] for item in maps) + " |",
        "|---|" + "---|" * len(maps),
    ]
    for opponent in summary["opponents"]:
        cells = []
        for evaluation_map in maps:
            cell = summary["table"][opponent["id"]][evaluation_map["id"]]
            cells.append(
                f"{cell['wins']}/{cell['losses']}/{cell['draws']}/{cell['errors']} "
                f"(p0 {cell['p0']['win']}/{cell['p0']['loss']}/{cell['p0']['draw']}; "
                f"p1 {cell['p1']['win']}/{cell['p1']['loss']}/{cell['p1']['draw']})"
            )
        lines.append("| " + opponent["name"] + " | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
