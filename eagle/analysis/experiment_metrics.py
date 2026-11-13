"""Read committed experiment metrics without opening candidate or match artifacts by default."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import yaml

from eagle.final_test import SUPPORTED_FINAL_TEST_SCHEMA_VERSIONS
from eagle.fixed_evaluation import SCHEMA_VERSION as FIXED_SCHEMA
from eagle.run_artifacts import GENERATION_SCHEMA_VERSION
from eagle.self_play import SNAPSHOT_SCHEMA_VERSION
from eagle.semantic_distances import SEMANTIC_DISTANCE_PAIR_SCHEMA_VERSION

GENERATION = re.compile(r"generation_(\d+)\.json")
OUTCOMES = {"win": "wins", "draw": "draws", "loss": "losses", "error": "errors"}
SCORE_FIELDS = (
    "result_win_score", "result_draw_score", "result_loss_score",
    "material_scale", "resource_scale", "shaping_min", "shaping_max",
)
NICHE_FIELDS = (
    "unique_niches", "dominant_niche_ratio", "new_niches", "revisited_niches", "niche_change_rate",
)
FIXED_SELECTIONS = {"generation_representative", "all_runnable_candidates"}
FINAL_SELECTIONS = {"latest_or_fallback", "explicit_candidate"}


def _object(value):
    return value if isinstance(value, dict) else {}


def _items(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _safe_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[\w.$+ -]+", value)) and value not in {".", ".."}


def _safe_relative(value):
    if not isinstance(value, str):
        return None
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or ":" in value:
        return None
    return path.as_posix()


def _digest(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[a-fA-F0-9]{64}", value))


def _json_object(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _portable_scoring(payload):
    values = {key: payload[key] for key in SCORE_FIELDS if _number(payload.get(key))}
    units = _object(payload.get("unit_values") or payload.get("unit_material_values"))
    if units and all(_safe_id(key) and _number(value) for key, value in units.items()):
        values["unit_values"] = units
    return values


def _recorded_benchmark(payload, selection_mode, metric, run_seed):
    """Normalize recorded identities while preserving seed policy and candidate selection."""
    opponents = []
    for row in _items(payload.get("opponents")):
        if not all(_safe_id(row.get(key)) for key in ("id", "class")):
            return None
        digest = row.get("jar_sha256")
        if digest is not None and not _digest(digest):
            return None
        opponents.append({"id": row["id"], "class": row["class"], "jar_sha256": digest})

    maps = []
    for row in _items(payload.get("maps")):
        path = _safe_relative(row.get("path"))
        if not _safe_id(row.get("id")) or not path or not _digest(row.get("sha256")):
            return None
        if type(row.get("tick_limit")) is not int or row["tick_limit"] <= 0:
            return None
        maps.append({"id": row["id"], "path": path, "tick_limit": row["tick_limit"], "sha256": row["sha256"]})

    scoring = _portable_scoring(_object(payload.get("scoring")))
    games = payload.get("games_per_side_per_map")
    scheme = payload.get("seed_scheme")
    seed_identity = payload.get("seed_identity")
    seed_root = payload.get("random_seed")
    runtime = _object(payload.get("microrts_identity"))
    support = _object(payload.get("support_identity"))
    worker_rush = payload.get("worker_rush_source_sha256")
    sides = payload.get("candidate_sides", [0, 1])
    if (
        not opponents or not maps or len(scoring) != len(SCORE_FIELDS) + 1
        or len({row["id"] for row in opponents}) != len(opponents)
        or len({row["id"] for row in maps}) != len(maps)
        or type(games) is not int or games < 1 or sides != [0, 1]
        or not isinstance(scheme, str) or not re.fullmatch(r"[\w ,().-]{1,240}", scheme)
        or not _safe_id(seed_identity) or type(seed_root) is not int or type(run_seed) is not int
        or not runtime or not all(_safe_id(key) and _digest(value) for key, value in runtime.items())
        or not support or not all(_safe_relative(key) and _digest(value) for key, value in support.items())
        or not _digest(worker_rush)
        or selection_mode not in FIXED_SELECTIONS | FINAL_SELECTIONS
    ):
        return None
    count = len(opponents) * len(maps) * games * len(sides)
    if payload.get("matches_per_representative") != count:
        return None
    return {
        "definition": metric, "selection_mode": selection_mode, "opponents": opponents, "maps": maps,
        "games_per_side_per_map": games, "candidate_sides": sides, "matches_per_representative": count,
        "scoring": scoring, "seed_scheme": scheme, "seed_identity": seed_identity,
        "seed_root_policy": "run seed" if seed_root == run_seed else "override",
        "seed_root_override": seed_root if seed_root != run_seed else None,
        "microrts_identity": runtime, "support_identity": support,
        "worker_rush_source_sha256": worker_rush,
        "match_timeout_seconds": payload.get("match_timeout_seconds")
        if _number(payload.get("match_timeout_seconds")) else None,
    }


def _signature_hash(signature):
    value = signature.get("dataset_sha256")
    return value if _digest(value) else None


def _normalization(signature):
    value = signature.get("normalization_version")
    return value if _safe_id(value) else None


def _semantic_protocol(population):
    signatures = Counter()
    for item in population:
        signature = _object(item.get("semantic_signature"))
        if signature.get("status") != "complete" or not _safe_id(signature.get("dataset_id")):
            continue
        probes = signature.get("probe_ids")
        if not isinstance(probes, list) or not probes or not all(isinstance(probe, str) and re.fullmatch(r"[\w.:-]+", probe) for probe in probes):
            continue
        signatures[
            (signature["dataset_id"], _signature_hash(signature), _normalization(signature), tuple(probes))
        ] += 1
    comparable = [key for key, count in signatures.items() if count >= 2]
    if len(comparable) != 1:
        return None
    dataset, digest, normalization, probes = comparable[0]
    if digest is None or normalization is None:
        return None
    return {
        "definition": SEMANTIC_DISTANCE_PAIR_SCHEMA_VERSION, "distance": "normalized Hamming",
        "dataset_id": dataset, "dataset_sha256": digest, "normalization_version": normalization,
        "probe_ids": list(probes),
    }


def _opponent_rows(summary, generation, source, protocol):
    for opponent, maps in _object(summary.get("table")).items():
        if not _safe_id(opponent) or not isinstance(maps, dict) or not maps:
            continue
        cells = list(maps.values())
        if not all(
            isinstance(cell, dict) and all(type(cell.get(key)) is int and cell[key] >= 0 for key in OUTCOMES.values())
            for cell in cells
        ):
            continue
        counts = {key: sum(cell[key] for cell in cells) for key in OUTCOMES.values()}
        for key in ("opponent_fault_contained", "opponent_fault_recovered"):
            if all(type(cell.get(key)) is int and cell[key] >= 0 for cell in cells):
                counts[key] = sum(cell[key] for cell in cells)
        counts["faults"] = counts.get("opponent_fault_contained")
        counted = counts["wins"] + counts["draws"] + counts["losses"]
        yield {
            "opponent": opponent, "generation": generation, "source": source, "protocol": protocol, **counts,
            "counted": counted, "win_rate": counts["wins"] / counted if counted else None,
        }


def _invalid_matrix(payload):
    return (
        payload.get("fixed_evaluation_valid") is False or payload.get("final_test_valid") is False
        or payload.get("matrix_valid") is False
        or payload.get("valid") is False or payload.get("invalid_matrix") is True
    )


def _match_scores(summary, opponent=None):
    """Verify the exact set of recorded benchmark cells before using scores."""
    roster = [row.get("id") for row in _items(summary.get("opponents"))]
    maps = [row.get("id") for row in _items(summary.get("maps"))]
    rounds = summary.get("games_per_side_per_map")
    if not roster or not maps or not all(_safe_id(value) for value in roster + maps):
        return []
    if type(rounds) is not int or rounds <= 0 or _invalid_matrix(summary):
        return []
    if opponent and opponent not in roster:
        return []
    expected = {
        (enemy, map_id, side, game)
        for enemy in ([opponent] if opponent else roster)
        for map_id in maps for side in (0, 1) for game in range(rounds)
    }
    seen = set()
    scores = []
    for row in _items(summary.get("matches")):
        if opponent and row.get("opponent_id") != opponent:
            continue
        key = tuple(row.get(field) for field in ("opponent_id", "map_id", "candidate_player", "game_index"))
        if not all(type(value) in (str, int) for value in key):
            return []
        score = _object(row.get("match")).get("score")
        if key not in expected or key in seen or row.get("result") not in {"win", "draw", "loss"} or not _number(score):
            return []
        seen.add(key)
        scores.append(score)
    return scores if seen == expected else []


class _RunMetrics:
    def __init__(self, run, fixed_opponent):
        self.run = run
        self.root = Path(run["path"])
        self.fixed_opponent = fixed_opponent if fixed_opponent != "all" else None
        self.points = []
        self.opponents = []
        self.issues = []
        self.protocols = {}
        self.populations = {}
        self.fixed_opponents = set()
        self.fixed_coverage = []

    def protocol(self, definition):
        if definition is None:
            return None
        payload = json.dumps(definition, sort_keys=True, allow_nan=False).encode("utf-8")
        identifier = hashlib.sha256(payload).hexdigest()
        self.protocols[identifier] = definition
        return identifier

    def point(self, metric, statistic, generation, value, source, **fields):
        if _number(value):
            self.points.append({
                "metric": metric, "statistic": statistic, "generation": generation,
                "value": value, "source": source, **fields,
            })

    def read(self, path, source):
        try:
            return _json_object(path)
        except (OSError, ValueError) as exc:
            self.issues.append(f"{source}: {exc.strerror if isinstance(exc, OSError) else 'unreadable JSON'}")
            return {}

    def generations(self):
        latest = self.run.get("latest_generation")
        if type(latest) is not int:
            self.issues.append("No committed generation")
            return
        try:
            config = _object(yaml.safe_load((self.root / "config.yaml").read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, yaml.YAMLError):
            config = {}
            self.issues.append("Resolved config is unreadable")
        evaluation = _object(config.get("evaluation"))
        is_self_play = evaluation.get("mode") == "self_play" or config.get("evaluation_mode") == "self_play"
        refresh = evaluation.get("self_play_refresh_interval")
        scoring = _portable_scoring(config)
        maps = [
            {"path": _safe_relative(item.get("path")), "tick_limit": item.get("tick_limit")}
            for item in _items(evaluation.get("maps"))
            if _safe_relative(item.get("path")) and type(item.get("tick_limit")) is int
        ]
        self_play_protocol = self.protocol({
            "definition": "persisted self-play Game Performance", "scoring": scoring, "maps": maps,
            "rounds_per_map": evaluation.get("rounds_per_map") if type(evaluation.get("rounds_per_map")) is int else None,
            "swap_player_sides": evaluation.get("swap_player_sides")
            if type(evaluation.get("swap_player_sides")) is bool else None,
        }) if is_self_play else None
        contexts = {}
        generations = sorted(
            (int(match[1]), path)
            for path in (self.root / "generations").glob("generation_*.json")
            if (match := GENERATION.fullmatch(path.name)) and int(match[1]) <= latest
        )
        present = set()
        for generation, path in generations:
            source = path.relative_to(self.root).as_posix()
            snapshot = self.read(path, source)
            if snapshot.get("schema_version") != GENERATION_SCHEMA_VERSION or snapshot.get("generation") != generation:
                self.issues.append(f"{source}: unsupported or mismatched generation snapshot")
                continue
            if generation in present:
                self.issues.append(f"{source}: duplicate generation snapshot")
                continue
            present.add(generation)
            population = _items(snapshot.get("population"))
            ids = [row.get("candidate_id") for row in population]
            if ids and all(_safe_id(item) for item in ids) and len(set(ids)) == len(ids):
                self.populations[generation] = set(ids)
            metrics = _object(snapshot.get("metrics"))
            if is_self_play:
                context_generation = generation
                if generation > 0 and type(refresh) is int and refresh > 0:
                    context_generation = 1 + (generation - 1) // refresh * refresh
                if context_generation not in contexts:
                    context_path = path.with_name(f"generation_{context_generation:04d}_self_play_snapshot.json")
                    context = self.read(context_path, context_path.relative_to(self.root).as_posix()) if context_path.is_file() else {}
                    identity = context.get("context_id")
                    if context.get("schema_version") != SNAPSHOT_SCHEMA_VERSION or context.get("generation") != context_generation:
                        identity = None
                    contexts[context_generation] = identity if _safe_id(identity) else None
                scores = _object(metrics.get("game_performance"))
                for statistic in ("best", "mean", "median", "worst"):
                    self.point(
                        "self_play", statistic, generation, scores.get(statistic), source, protocol=self_play_protocol,
                        context=contexts[context_generation], context_generation=context_generation,
                        coverage={"expected": metrics.get("population_size"), "evaluated": scores.get("count")},
                    )
            semantic = _object(metrics.get("semantic_distance") or snapshot.get("semantic_distances"))
            if any(_number(semantic.get(key)) for key in ("mean", "minimum", "maximum")):
                protocol = self.protocol(_semantic_protocol(population))
                for statistic in ("mean", "minimum", "maximum"):
                    self.point(
                        "diversity", statistic, generation, semantic.get(statistic), source, protocol=protocol,
                        coverage={key: semantic.get(key) for key in (
                            "pair_count", "comparable_pair_count", "unavailable_pair_count",
                        )},
                    )
            niche = _object(metrics.get("strategy_diversity"))
            if niche:
                protocol = self.protocol({"definition": "eagle-generation-metrics-v1 strategy_diversity"})
                for statistic in NICHE_FIELDS:
                    self.point("diversity", statistic, generation, niche.get(statistic), source, protocol=protocol)
                if _number(niche.get("known_signature_count")) and niche["known_signature_count"] >= 2:
                    self.point("diversity", "mean_strategy_distance", generation,
                               niche.get("mean_strategy_distance"), source, protocol=protocol)
        missing = latest + 1 - len(present)
        if missing > 0:
            self.issues.append(f"{missing} committed generation snapshot(s) missing or unreadable through G{latest}")

    def final(self):
        source = "final_test/final_test_summary.json"
        path = self.root / source
        if not path.is_file():
            self.issues.append("Final test summary is missing")
            return
        summary = self.read(path, source)
        if summary.get("schema_version") not in SUPPORTED_FINAL_TEST_SCHEMA_VERSIONS:
            self.issues.append(f"{source}: unsupported final-test schema")
            return
        if _invalid_matrix(summary):
            self.issues.append(f"{source}: explicitly invalid benchmark matrix")
            return
        selection = _object(summary.get("selection"))
        candidate = _object(summary.get("candidate"))
        generation = selection.get("selected_generation")
        requested = selection.get("requested_generation")
        if type(generation) is not int:
            self.issues.append(f"{source}: evaluated checkpoint is unavailable")
        protocol = self.protocol(_recorded_benchmark(
            _object(summary.get("protocol")), selection.get("mode"), "final-test Game Performance", self.run.get("seed"),
        ))
        if not protocol:
            self.issues.append(f"{source}: unknown benchmark protocol (recorded hashes, scoring or seed policy unavailable)")
        fields = {
            "requested_generation": requested if type(requested) is int else None,
            "fallback": selection.get("fallback") is True,
            "candidate_id": candidate.get("candidate_id") if _safe_id(candidate.get("candidate_id")) else None,
            "birth_generation": candidate.get("generation") if type(candidate.get("generation")) is int else None,
        }
        opponents = list(_opponent_rows(summary, generation, source, protocol))
        self.opponents.extend(opponents)
        scores = _match_scores(summary)
        if not scores:
            self.issues.append(f"{source}: final score unavailable because the score matrix is incomplete or invalid")
        if type(generation) is int and scores:
            self.point("final", "score", generation, statistics.fmean(scores), source, protocol=protocol,
                       coverage={"expected": len(scores), "evaluated": len(scores)}, **fields)
        counted = sum(row["counted"] for row in opponents)
        if type(generation) is int and counted:
            self.point(
                "final", "win_rate", generation, sum(row["wins"] for row in opponents) / counted, source,
                protocol=protocol, coverage={"evaluated": counted}, **fields,
            )

    def fixed(self):
        base = self.root / "final_test"
        paths = [
            {"path": self.root / "fixed_evaluation" / "fixed_evaluation_summary.json"},
            {"path": base / "cross_generation" / "fixed_evaluation_summary.json"},
            *({"path": path} for path in sorted(base.glob("cross_generation_retry_*/fixed_evaluation_summary.json"))),
            *self.run.get("benchmarks", []),
        ]
        visited = set()
        for entry in paths:
            path = Path(entry["path"])
            if path.is_dir():
                path /= "fixed_evaluation_summary.json"
            if path.resolve() in visited:
                continue
            visited.add(path.resolve())
            source = path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else f"external/{path.name}"
            if not path.is_file():
                if entry in self.run.get("benchmarks", []):
                    self.issues.append(f"{source}: registered benchmark is missing")
                continue
            if path.suffix.lower() == ".csv":
                self.external_csv(entry, path, source)
            else:
                self.fixed_summary(path, source)
        if not self.fixed_coverage:
            self.issues.append("No fixed benchmark checkpoints found")

    def external_csv(self, entry, path, source):
        by_generation = defaultdict(dict)
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not {"seed", "generation", "candidate_id", "mean_match_score"}.issubset(reader.fieldnames or []):
                    raise ValueError("Unsupported fixed-evaluation CSV fields")
                for row in reader:
                    if int(row["seed"]) != self.run["seed"] or (
                        "treatment" in row and row["treatment"] != entry.get("label", self.run.get("label"))
                    ):
                        continue
                    value = float(row["mean_match_score"])
                    if not _number(value) or not _safe_id(row["candidate_id"]):
                        raise ValueError("Invalid candidate score")
                    generation = int(row["generation"])
                    if generation < 0 or row["candidate_id"] in by_generation[generation]:
                        raise ValueError("Invalid generation or duplicate candidate")
                    by_generation[generation][row["candidate_id"]] = value
        except (OSError, ValueError, TypeError) as exc:
            self.issues.append(f"{source}: {exc.strerror if isinstance(exc, OSError) else str(exc)}")
            return
        protocol_data = self.read(Path(entry["protocol"]), f"{source} protocol") if entry.get("protocol") else {}
        protocol = self.protocol(_recorded_benchmark(
            protocol_data, "all_runnable_candidates", "fixed-benchmark Game Performance", self.run.get("seed"),
        ))
        if not protocol:
            self.issues.append(f"{source}: unknown benchmark protocol (external CSV)")
        if not by_generation:
            self.issues.append(f"{source}: no matching treatment and seed in external CSV")
        if self.fixed_opponent:
            self.issues.append(f"{source}: external CSV has no opponent-level scores")
            return
        for generation, values in sorted(by_generation.items()):
            population = self.populations.get(generation)
            expected = len(population) if population is not None else entry.get("population_size")
            complete = set(values) == population if population is not None else len(values) == expected
            self.population_points(generation, source, protocol, values, expected, complete)

    def fixed_summary(self, path, source):
        summary = self.read(path, source)
        if summary.get("schema_version") != FIXED_SCHEMA or _invalid_matrix(summary):
            self.issues.append(f"{source}: unsupported or invalid fixed benchmark")
            return
        raw_protocol = _object(summary.get("protocol"))
        self.fixed_opponents.update(row["id"] for row in _items(raw_protocol.get("opponents")) if _safe_id(row.get("id")))
        mode = summary.get("selection_mode")
        if mode not in FIXED_SELECTIONS:
            self.issues.append(f"{source}: unknown fixed benchmark candidate selection")
            return
        protocol = self.protocol(_recorded_benchmark(
            raw_protocol, mode, "fixed-benchmark Game Performance", self.run.get("seed"),
        ))
        if not protocol:
            self.issues.append(f"{source}: unknown benchmark protocol (recorded hashes, scoring or seed policy unavailable)")
        selections = defaultdict(dict)
        rows = defaultdict(dict)
        for item in _items(summary.get("selections")):
            generation, candidate = item.get("generation"), item.get("candidate_id")
            if type(generation) is int and _safe_id(candidate):
                selections[generation][candidate] = item
        for item in _items(summary.get("rows")):
            generation, candidate = item.get("generation"), item.get("candidate_id")
            if (
                type(generation) is int and _safe_id(candidate) and item.get("status") == "complete"
                and not _invalid_matrix(item) and item.get("errors") == 0
                and type(item.get("expected_matches")) is int and item["expected_matches"] > 0
                and item.get("completed_matches") == item["expected_matches"]
                and item["expected_matches"] == raw_protocol.get("matches_per_representative", item["expected_matches"])
            ):
                rows[generation][candidate] = item
        for generation in sorted(selections.keys() | rows.keys()):
            population = self.populations.get(generation)
            selected = selections[generation]
            completed = rows[generation]
            values = {}
            for candidate, row in completed.items():
                if selected and candidate not in selected:
                    continue
                value = row.get("mean_match_score")
                if self.fixed_opponent:
                    value = self.fixed_detail(path, source, row)
                if _number(value):
                    values[candidate] = value
            if mode == "all_runnable_candidates":
                expected = len(population) if population is not None else None
                self.population_points(
                    generation, source, protocol, values, expected, population is not None and set(values) == population,
                )
                rank = [(item["search_game_performance"], candidate) for candidate, item in selected.items()
                        if _number(item.get("search_game_performance"))]
                if selected and len(rank) == len(selected):
                    candidate = min(rank, key=lambda item: (-item[0], item[1]))[1]
                    self.representative_point(generation, source, protocol, values.get(candidate))
            elif len(selected) == 1:
                candidate = next(iter(selected))
                self.representative_point(generation, source, protocol, values.get(candidate))
            elif not selected and len(values) == 1:
                self.representative_point(generation, source, protocol, next(iter(values.values())))
            else:
                self.representative_point(generation, source, protocol, None)

    def fixed_detail(self, path, source, row):
        relative = _safe_relative(row.get("summary_path"))
        if not relative:
            return None
        detail = (path.parent / relative).resolve()
        if not detail.is_relative_to(path.parent.resolve()):
            return None
        summary = self.read(detail, f"{source} → {relative}")
        if summary.get("schema_version") not in SUPPORTED_FINAL_TEST_SCHEMA_VERSIONS:
            return None
        if _object(summary.get("candidate")).get("candidate_id") != row.get("candidate_id"):
            return None
        scores = _match_scores(summary, self.fixed_opponent)
        return statistics.fmean(scores) if scores else None

    def population_points(self, generation, source, protocol, values, expected, complete):
        coverage = {"expected": expected, "evaluated": len(values)}
        fields = {"protocol": protocol, "coverage": coverage}
        if self.fixed_opponent:
            fields["opponent"] = self.fixed_opponent
        for statistic in ("mean", "best"):
            self.fixed_coverage.append({
                "generation": generation, "statistic": statistic, "source": source, **fields,
            })
        if complete and values:
            self.point("fixed", "mean", generation, statistics.fmean(values.values()), source, **fields)
            self.point("fixed", "best", generation, max(values.values()), source, **fields)
        else:
            self.issues.append(f"{source}: G{generation} fixed population coverage {len(values)}/{expected or '?'}")

    def representative_point(self, generation, source, protocol, value):
        fields = {"protocol": protocol, "coverage": {"expected": 1, "evaluated": int(_number(value))}}
        if self.fixed_opponent:
            fields["opponent"] = self.fixed_opponent
        self.fixed_coverage.append({
            "generation": generation, "statistic": "representative", "source": source, **fields,
        })
        self.point("fixed", "representative", generation, value, source, **fields)

    def result(self):
        points = {}
        conflicts = set()
        for row in self.points:
            identity = tuple(row.get(key) for key in ("metric", "statistic", "generation", "protocol", "opponent"))
            existing = points.setdefault(identity, row)
            if existing["value"] != row["value"] and identity not in conflicts:
                conflicts.add(identity)
                self.issues.append(
                    f"{row['metric']}/{row['statistic']} G{row['generation']}: conflicting scores "
                    f"in {existing['source']} and {row['source']}"
                )
        self.points = [row for identity, row in points.items() if identity not in conflicts]
        for metric in ("self_play", "diversity"):
            if not any(row["metric"] == metric for row in self.points):
                self.issues.append(f"No persisted {metric.replace('_', ' ')} metric")
        return {
            "points": self.points, "opponents": self.opponents, "issues": self.issues,
            "protocols": self.protocols, "fixed_opponents": sorted(self.fixed_opponents),
            "fixed_coverage": self.fixed_coverage,
        }


def read_metrics(run: dict, *, fixed_opponent: str | None = None) -> dict:
    """Read canonical run summaries and explicitly registered benchmark evidence."""
    reader = _RunMetrics(run, fixed_opponent)
    reader.generations()
    reader.fixed()
    reader.final()
    return reader.result()
