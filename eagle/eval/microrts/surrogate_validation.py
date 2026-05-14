"""Run prompt-level benchmark batches comparing EAGLE vs eaglePolicy matches."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ...config import EAConfig, load_config_from_json
from ...envs.microrts import locate_microrts_root
from ...main import OPPONENT_LIST, _resolve_component_pool_path
from ...project import DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH, EAGLE_LOGS_DIR
from ...surrogate.compiler.eagle_policy_spec import compile_prompt_to_eagle_policy_spec
from ...utils.component_pool import ComponentPool
from ...utils.match_score_recorder import MatchScoreRecorder
from ...evolution.component.individual import Individual
from .full_game_evaluator import FullGameEvaluator
from .surrogate_validation_outputs import refresh_experiment_outputs
DEFAULT_SURROGATE_VALIDATION_TICK_LIMIT = 60
DEFAULT_QUICK_RUN_OPPONENT = "ai.PassiveAI"


def _build_random_prompt_artifacts(component_pool: ComponentPool, config: EAConfig) -> tuple[Individual, str]:
    """Create one random EA-style individual and render its prompt."""
    individual = Individual()
    individual.initialize_randomly(component_pool)
    evaluator = FullGameEvaluator(component_pool, config)
    prompt = evaluator._construct_prompt(individual)
    return individual, prompt


def _make_experiment_log_dir() -> Path:
    """Create the output directory for one surrogate-validation experiment run."""
    log_dir = EAGLE_LOGS_DIR / f"surrogate_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _make_smoke_log_dir() -> Path:
    """Create the output directory for one fast surrogate smoke-test run."""
    log_dir = EAGLE_LOGS_DIR / f"surrogate_validation_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _individual_payload(individual: Individual) -> dict[str, Any]:
    """Serialize one individual's identifying fields for JSON outputs."""
    return {
        "id": individual.id,
        "game_rule": individual.game_rule,
        "component_indices": dict(individual.component_indices),
    }


def _prompt_digest(prompt: str) -> str:
    """Build a stable digest for the rendered prompt text."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

def _infer_final_tick(parsed_log: dict[str, Any] | None) -> int | None:
    """Infer the last observed game tick from parsed log structures."""
    if not isinstance(parsed_log, dict):
        return None

    candidates: list[int] = []
    for row in list(parsed_log.get("resource_history") or []):
        time_value = row.get("time")
        if isinstance(time_value, int):
            candidates.append(time_value)
    for row in list(parsed_log.get("feature_history") or []):
        time_value = row.get("time")
        if isinstance(time_value, int):
            candidates.append(time_value)
    for segment in list(parsed_log.get("segments") or []):
        current_time = segment.get("current_time")
        if isinstance(current_time, int):
            candidates.append(current_time)
    return max(candidates) if candidates else None

def _match_win_score(match_score: Any) -> float:
    if isinstance(match_score, dict):
        try:
            return float(match_score.get("win_score", 0.0))
        except (TypeError, ValueError):
            return 0.0
    if isinstance(match_score, list) and match_score:
        try:
            return float(match_score[0])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _match_resource_advantage_score(match_score: Any) -> float:
    if isinstance(match_score, dict):
        try:
            return float(match_score.get("raw_resource_advantage_score", 0.0))
        except (TypeError, ValueError):
            return 0.0
    if isinstance(match_score, list) and len(match_score) > 1:
        try:
            return float(match_score[1])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _normalize_match_score(match_score: Any) -> dict[str, float]:
    return {
        "win_score": _match_win_score(match_score),
        "raw_resource_advantage_score": _match_resource_advantage_score(match_score),
    }


def _result_label_from_match_score(match_score: Any) -> str:
    """Map the first objective to the familiar Win/Draw/Loss labels."""
    win_score = _match_win_score(match_score)
    if win_score == 1.0:
        return "Win"
    if win_score == 0.0:
        return "Loss"
    return "Draw"



def run_surrogate_validation_smoke_test(
    *,
    config: EAConfig | None = None,
    num_individuals: int = 1,
) -> dict[str, Any]:
    """Run a fast surrogate smoke test without launching full Java matches."""
    config = config or EAConfig()
    log_dir = _make_smoke_log_dir()
    component_pool = ComponentPool.from_json(_resolve_component_pool_path())
    microrts_root = locate_microrts_root()
    results: dict[str, Any] = {
        "experiment_type": "surrogate_validation_smoke",
        "timestamp": datetime.now().isoformat(),
        "log_dir": str(log_dir),
        "component_pool_path": _resolve_component_pool_path(),
        "microrts_root": str(microrts_root),
        "num_individuals": int(num_individuals),
        "individual_results": [],
    }

    required_java_files = {
        "eagle_java": microrts_root / "src" / "ai" / "abstraction" / "EAGLE.java",
        "eagle_policy_java": microrts_root / "src" / "ai" / "abstraction" / "eaglePolicy.java",
        "config_properties": microrts_root / "resources" / "config.properties",
    }

    for individual_index in range(max(1, int(num_individuals))):
        individual, prompt = _build_random_prompt_artifacts(component_pool, config)
        policy, eagle_policy_spec = compile_prompt_to_eagle_policy_spec(prompt)
        individual_dir = log_dir / f"individual_{individual_index:03d}_{individual.id}"
        individual_dir.mkdir(parents=True, exist_ok=True)
        (individual_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (individual_dir / "policy.json").write_text(
            json.dumps(policy, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (individual_dir / "eagle_policy_spec.json").write_text(
            json.dumps(eagle_policy_spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (individual_dir / "individual.json").write_text(
            json.dumps(
                _individual_payload(individual),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        results["individual_results"].append(
            {
                "individual_index": individual_index,
                "prompt_digest": _prompt_digest(prompt),
                "prompt_line_count": len(prompt.splitlines()),
                "individual": _individual_payload(individual),
                "compiled_policy": policy,
                "eagle_policy_spec": eagle_policy_spec,
                "checks": {
                    "microrts_root_exists": microrts_root.exists(),
                    "required_java_files": {
                        name: path.exists()
                        for name, path in required_java_files.items()
                    },
                },
            }
        )

    (log_dir / "surrogate_validation_smoke_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results


def _history_record_to_result(
    *,
    opponent: str,
    benchmark_mode: str,
    history_record: dict[str, Any],
) -> dict[str, Any]:
    """Convert one cached history row into the experiment result schema."""
    match_score = _normalize_match_score(history_record.get("match_score") or history_record.get("fitness_score"))
    return {
        "opponent": opponent,
        "benchmark_mode": benchmark_mode,
        "match_score": match_score,
        "fitness": match_score,
        "result": _result_label_from_match_score(match_score),
        "win_score": _match_win_score(match_score),
        "resource_advantage_score": _match_resource_advantage_score(match_score),
        "game_time_sec": history_record.get("game_time_sec"),
        "log_path": history_record.get("log_path"),
        "winner": history_record.get("winner"),
        "timeout": history_record.get("timeout"),
        "llm_calls": history_record.get("llm_calls"),
        "parsed_summary": history_record.get("parsed_summary"),
        "stats": history_record.get("stats"),
        "llm_interval": history_record.get("llm_interval"),
        "tick_limit": history_record.get("tick_limit"),
        "llm_call_limit": history_record.get("llm_call_limit"),
        "runner_script": history_record.get("runner_script"),
        "ai1": history_record.get("ai1"),
        "ai2": history_record.get("ai2"),
        "history_key": history_record.get("history_key"),
        "cached": True,
    }


def _maybe_reuse_cached_match(
    recorder: MatchScoreRecorder,
    *,
    prompt: str,
    opponent: str,
    benchmark_mode: str,
) -> dict[str, Any] | None:
    """Reuse a prior prompt/opponent/mode match when history already has it."""
    matches = recorder.find_matching_history(prompt, opponent)
    for match in reversed(matches):
        if match.get("benchmark_mode") != benchmark_mode:
            continue
        if match.get("game_time_sec") is None:
            continue
        return _history_record_to_result(
            opponent=opponent,
            benchmark_mode=benchmark_mode,
            history_record=match,
        )
    return None


def _record_match(
    recorder: MatchScoreRecorder,
    *,
    prompt: str,
    opponent: str,
    benchmark_mode: str,
    match_score: dict[str, float],
    game_time_sec: float,
    log_path: str | None,
    metadata: dict[str, Any] | None = None,
    stats: dict[str, float] | None = None,
    llm_interval: int | None = None,
    ai1: str | None = None,
    runner_script: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one benchmark match so future reruns can reuse its result."""
    metadata = dict(metadata or {})
    parsed_log = metadata.get("parsed_log") if isinstance(metadata.get("parsed_log"), dict) else None
    parsed_summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else None
    final_tick = _infer_final_tick(parsed_log)
    ai2 = opponent
    record = {
        "individual_id": None,
        "generation": None,
        "prompt": prompt,
        "match_score": dict(match_score),
        "opponent": opponent,
        "evaluation_mode": "gameplay",
        "benchmark_mode": benchmark_mode,
        "evaluation_time": float(game_time_sec),
        "game_time_sec": float(game_time_sec),
        "final_tick": final_tick,
        "max_cycles": parsed_summary.get("max_cycles") if isinstance(parsed_summary, dict) else None,
        "log_path": log_path,
        "winner": metadata.get("winner"),
        "timeout": metadata.get("timeout"),
        "llm_calls": metadata.get("llm_calls"),
        "parsed_summary": parsed_summary,
        "stats": dict(stats or {}),
        "llm_interval": llm_interval,
        "tick_limit": int(recorder.config.tick_limit),
        "llm_call_limit": int(recorder.config.llm_call_limit),
        "runner_script": runner_script,
        "ai1": ai1,
        "ai2": ai2,
        "components": {},
    }
    if isinstance(extra, dict):
        record.update(extra)
    recorder.record_match_score(record)
    result = {
        "opponent": opponent,
        "benchmark_mode": benchmark_mode,
        "match_score": dict(match_score),
        "fitness": dict(match_score),
        "result": _result_label_from_match_score(match_score),
        "win_score": _match_win_score(match_score),
        "resource_advantage_score": _match_resource_advantage_score(match_score),
        "game_time_sec": float(game_time_sec),
        "final_tick": final_tick,
        "max_cycles": parsed_summary.get("max_cycles") if isinstance(parsed_summary, dict) else None,
        "log_path": log_path,
        "winner": metadata.get("winner"),
        "timeout": metadata.get("timeout"),
        "llm_calls": metadata.get("llm_calls"),
        "parsed_summary": parsed_summary,
        "stats": dict(stats or {}),
        "llm_interval": llm_interval,
        "tick_limit": int(recorder.config.tick_limit),
        "llm_call_limit": int(recorder.config.llm_call_limit),
        "runner_script": runner_script,
        "ai1": ai1,
        "ai2": ai2,
        "trace_xml_path": metadata.get("trace_xml_path"),
        "trace_json_path": metadata.get("trace_json_path"),
        "cached": False,
    }
    if isinstance(extra, dict):
        result.update(extra)
    return result


def _run_eagle_match(
    evaluator: FullGameEvaluator,
    recorder: MatchScoreRecorder,
    *,
    prompt: str,
    opponent: str,
    llm_interval: int,
) -> dict[str, Any]:
    """Run one 5000-cycle benchmark match with the gameplay EAGLE Java agent."""
    ai1 = "ai.abstraction.EAGLE"

    cached = _maybe_reuse_cached_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="eagle_final_test",
    )
    if cached is not None:
        return cached

    stats: dict[str, float] = {}
    started = time.perf_counter()
    result = evaluator.run_prompt_based_agent(
        prompt=prompt,
        opponent=opponent,
        llm_interval=llm_interval,
        test=True,
    )
    match_score = dict(result["match_score"])
    metadata = dict(result.get("simulation_meta") or {})
    elapsed = time.perf_counter() - started
    log_path = metadata.get("log_path")

    return _record_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="eagle_final_test",
        match_score=match_score,
        game_time_sec=elapsed,
        log_path=log_path,
        metadata=metadata,
        stats=stats,
        llm_interval=llm_interval,
        ai1=ai1,
        runner_script="RunLoop_5000.sh",
    )


def _run_eagle_policy_match(
    evaluator: FullGameEvaluator,
    recorder: MatchScoreRecorder,
    *,
    prompt: str,
    opponent: str,
    llm_interval: int,
) -> dict[str, Any]:
    """Run one 5000-cycle benchmark match with the generated eaglePolicy Java agent."""
    ai1 = "ai.abstraction.eaglePolicy"

    cached = _maybe_reuse_cached_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="eagle_policy_final_test",
    )
    if cached is not None:
        return cached

    stats: dict[str, float] = {}
    started = time.perf_counter()
    result = evaluator.run_java_based_agent(
        prompt=prompt,
        opponent=opponent,
        llm_interval=llm_interval,
        test=True,
    )
    java_fitness = dict(result["match_score"])
    metadata = dict(result.get("simulation_meta") or {})
    elapsed = time.perf_counter() - started
    match_score = dict(java_fitness)

    return _record_match(
        recorder,
        prompt=prompt,
        opponent=opponent,
        benchmark_mode="eagle_policy_final_test",
        match_score=match_score,
        game_time_sec=elapsed,
        log_path=metadata.get("log_path"),
        metadata=metadata,
        stats=stats,
        llm_interval=llm_interval,
        ai1=ai1,
        runner_script="RunLoop_5000.sh",
        extra={
            "java_match_fitness": dict(java_fitness),
            "java_match_win_score": _match_win_score(java_fitness),
            "java_match_resource_advantage_score": _match_resource_advantage_score(java_fitness),
        },
    )


def run_surrogate_validation_experiment(
    *,
    config: EAConfig | None = None,
    opponents: list[str] | None = None,
    num_individuals: int = 1,
) -> dict[str, Any]:
    """Compare multiple random EA-style prompts under final-test and eaglePolicy matches."""
    config = config or EAConfig()
    log_dir = _make_experiment_log_dir()
    component_pool = ComponentPool.from_json(_resolve_component_pool_path())
    evaluator = FullGameEvaluator(component_pool, config, runtime_logs_dir=log_dir / "microrts")
    recorder = MatchScoreRecorder(log_dir, config)

    opponents = list(opponents or OPPONENT_LIST)
    llm_interval = int(config.active_llm_interval())

    results = {
        "experiment_type": "surrogate_validation",
        "timestamp": datetime.now().isoformat(),
        "log_dir": str(log_dir),
        "llm_interval": llm_interval,
        "tick_limit": int(config.tick_limit),
        "llm_call_limit": int(config.llm_call_limit),
        "population_size": int(config.population_size),
        "num_generations": int(config.num_generations),
        "num_individuals": int(num_individuals),
        "component_pool_path": _resolve_component_pool_path(),
        "opponents": opponents,
        "history_cache_schema_version": 5,
        "individual_results": [],
        "alignment_summary": {},
    }

    for individual_index in range(int(num_individuals)):
        individual, prompt = _build_random_prompt_artifacts(component_pool, config)
        individual_result = {
            "individual_index": individual_index,
            "prompt": prompt,
            "prompt_digest": _prompt_digest(prompt),
            "prompt_line_count": len(prompt.splitlines()),
            "individual": _individual_payload(individual),
            "modes": {
                "eagle_final_test": [],
                "eagle_policy_final_test": [],
            },
            "mode_summaries": {},
        }

        individual_dir = log_dir / f"individual_{individual_index:03d}_{individual.id}"
        individual_dir.mkdir(parents=True, exist_ok=True)
        (individual_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (individual_dir / "individual.json").write_text(
            json.dumps(individual_result["individual"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        results["individual_results"].append(individual_result)

        for opponent in opponents:
            individual_result["modes"]["eagle_final_test"].append(
                _run_eagle_match(
                    evaluator,
                    recorder,
                    prompt=prompt,
                    opponent=opponent,
                    llm_interval=llm_interval,
                )
            )
            individual_result["modes"]["eagle_policy_final_test"].append(
                _run_eagle_policy_match(
                    evaluator,
                    recorder,
                    prompt=prompt,
                    opponent=opponent,
                    llm_interval=llm_interval,
                )
            )
            _refresh_experiment_outputs(log_dir, results, individual_result)

        _refresh_experiment_outputs(log_dir, results, individual_result)

    return results


def run_surrogate_validation_quick_run(
    *,
    config: EAConfig | None = None,
    opponents: list[str] | None = None,
) -> dict[str, Any]:
    """Run the smallest gameplay surrogate-validation benchmark that still launches games."""
    selected_opponents = list(opponents or [DEFAULT_QUICK_RUN_OPPONENT])
    if not selected_opponents:
        selected_opponents = [DEFAULT_QUICK_RUN_OPPONENT]
    return run_surrogate_validation_experiment(
        config=config,
        opponents=selected_opponents[:1],
        num_individuals=1,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI for the surrogate-validation experiment."""
    parser = argparse.ArgumentParser(
        description="Compare one random EA-style prompt under EAGLE final-test and eaglePolicy benchmark matches.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Load one surrogate-validation config JSON file. "
            f"Defaults to {DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH.as_posix()} when present."
        ),
    )
    parser.add_argument(
        "--opponent",
        action="append",
        default=None,
        help="Optional opponent override. Repeat to benchmark multiple opponents.",
    )
    parser.add_argument(
        "--num-individuals",
        type=int,
        default=1,
        help="How many random EA-style individuals to benchmark in one experiment run.",
    )
    parser.add_argument(
        "--tick-limit",
        type=int,
        default=DEFAULT_SURROGATE_VALIDATION_TICK_LIMIT,
        help="Per-game MicroRTS tick limit for surrogate-validation matches.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a fast smoke test that validates surrogate prompt/spec and MicroRTS paths without launching games.",
    )
    parser.add_argument(
        "--quick-run",
        action="store_true",
        help="Run one individual against one opponent using gameplay matches for a minimal end-to-end benchmark.",
    )
    return parser


def main() -> None:
    """CLI entry point for the surrogate-validation experiment."""
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.config:
        config = load_config_from_json(args.config)
    elif DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH.exists():
        config = load_config_from_json(DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH)
    else:
        config = EAConfig()
    config.tick_limit = max(1, int(args.tick_limit))
    config.validate()
    if args.smoke_test:
        results = run_surrogate_validation_smoke_test(
            config=config,
            num_individuals=max(1, int(args.num_individuals)),
        )
    elif args.quick_run:
        results = run_surrogate_validation_quick_run(
            config=config,
            opponents=args.opponent,
        )
    else:
        results = run_surrogate_validation_experiment(
            config=config,
            opponents=args.opponent,
            num_individuals=max(1, int(args.num_individuals)),
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
