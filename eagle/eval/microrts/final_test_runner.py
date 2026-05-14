"""Replay saved individuals for final benchmark evaluation and result logging."""

from __future__ import annotations

import re
from pathlib import Path

from ...config import EAConfig
from ...main import OPPONENT_LIST
from ...project import DEFAULT_FINAL_TEST_CONFIG_PATH
from ...utils.component_pool import ComponentPool
from ...evolution.component.log_parse import parse_individuals_from_ea_log, parse_population_snapshot_from_ea_log
from .full_game_evaluator import FullGameEvaluator
from .generation_replay import build_result_record, extract_individual_ids_up_to_front
from .replay_common import apply_runtime_overrides, build_interval_runs, write_results_snapshot


def _resolve_final_test_max_front(config: EAConfig) -> int | None:
    """Normalize the configured front cutoff for final-test replay selection."""
    configured_value = config.final_test_max_front
    if configured_value is None:
        return 1
    if int(configured_value) < 1:
        return 0
    return int(configured_value)


def _extract_generation_number(path: Path) -> int:
    """Extract the human-readable generation number from `generation_<N>_mo.txt`."""
    match = re.match(r"generation_(\d+)_mo\.txt$", path.name)
    if not match:
        return -1
    return int(match.group(1))


def _resolve_latest_generation_log_path(current_log_dir: str | Path) -> Path:
    """Return the newest saved multi-objective generation log under one run directory."""
    log_dir = Path(current_log_dir)
    candidates = sorted(
        log_dir.glob("generation_*_mo.txt"),
        key=_extract_generation_number,
    )
    if not candidates:
        raise FileNotFoundError(f"No multi-objective generation logs found under {log_dir}.")
    return candidates[-1]


def _resolve_final_generation_log_path(current_log_dir: str | Path, last_gen: int | None) -> Path:
    """Resolve the saved generation log for the final replay step."""
    log_dir = Path(current_log_dir)
    if last_gen is not None:
        exact_match = log_dir / f"generation_{last_gen}_mo.txt"
        if exact_match.exists():
            return exact_match

        one_based_match = log_dir / f"generation_{last_gen + 1}_mo.txt"
        if one_based_match.exists():
            return one_based_match

    return _resolve_latest_generation_log_path(log_dir)

def _resolve_final_test_config(
    base_config: EAConfig,
    config_path: str | Path | None = None,
) -> EAConfig:
    """Apply final-test-specific runtime overrides onto the saved run config."""
    return apply_runtime_overrides(base_config, config_path)


def run_final_test_suite(
    current_log_dir: str,
    last_gen: int | None,
    config: EAConfig | None = None,
    final_test_config_path: str | Path | None = None,
):
    """Replay final-generation individuals up to the configured Pareto front cutoff."""
    experiment_log_dir = Path(current_log_dir)
    base_config = config or EAConfig()
    runtime_config = _resolve_final_test_config(base_config, final_test_config_path)
    evaluator = FullGameEvaluator(
        ComponentPool.from_json(str(experiment_log_dir / "component_pool.json")),
        runtime_config,
        runtime_logs_dir=experiment_log_dir / "microrts",
    )
    final_test_max_front = _resolve_final_test_max_front(base_config)
    if final_test_max_front == 0:
        print("[Final Test] skipped because final_test_max_front=0", flush=True)
        return {
            "generation": None,
            "generation_log": None,
            "selected_individual_count": 0,
            "selection_rule": "skipped_final_test_max_front_0",
            "test_config_path": str(
                Path(final_test_config_path) if final_test_config_path is not None else DEFAULT_FINAL_TEST_CONFIG_PATH
            ),
            "run_time_per_game_sec": int(runtime_config.run_time_per_game_sec),
            "interval_runs": [],
            "results": {},
            "skipped": True,
            "skip_reason": "final_test_max_front=0",
        }

    generation_log_path = _resolve_final_generation_log_path(experiment_log_dir, last_gen)
    individuals_by_front = parse_individuals_from_ea_log(str(generation_log_path))
    population_snapshot = parse_population_snapshot_from_ea_log(str(generation_log_path))
    selected_front_ids = set(
        extract_individual_ids_up_to_front(
            generation_log_path,
            final_test_max_front,
        )
    )

    # Final test should replay the survivor population saved in Population Snapshot,
    # not the full parent+offspring union listed in Pareto Front sections.
    if population_snapshot:
        candidate_individuals = population_snapshot
    else:
        # Fallback for older logs that may not contain Population Snapshot.
        seen_ids: set[str] = set()
        candidate_individuals = []
        for front in individuals_by_front:
            for individual in front:
                if individual.id in seen_ids:
                    continue
                seen_ids.add(individual.id)
                candidate_individuals.append(individual)

    if selected_front_ids:
        selected_individuals = [
            individual
            for individual in candidate_individuals
            if individual.id in selected_front_ids
        ]
    else:
        selected_individuals = candidate_individuals

    interval_runs = build_interval_runs(final_test_config_path, runtime_config.llm_interval)
    generation_number = _extract_generation_number(generation_log_path)
    results = {
        "generation": generation_number,
        "generation_log": generation_log_path.name,
        "selected_individual_count": len(selected_individuals),
        "selection_rule": (
            f"pareto_front_1_to_{final_test_max_front}"
            if final_test_max_front is not None
            else "all_fronts"
        ),
        "test_config_path": str(
            Path(final_test_config_path) if final_test_config_path is not None else DEFAULT_FINAL_TEST_CONFIG_PATH
        ),
        "run_time_per_game_sec": int(runtime_config.run_time_per_game_sec),
        "interval_runs": interval_runs,
        "results": {},
    }

    print(
        "[Final Test] start: "
        f"generation={generation_number}, "
        f"selected_individuals={len(selected_individuals)}, "
        f"interval_runs={len(interval_runs)}",
        flush=True,
    )

    for individual_index, individual in enumerate(selected_individuals, start=1):
        print(
            f"[Final Test] individual {individual_index}/{len(selected_individuals)} "
            f"(id={individual.id})",
            flush=True,
        )
        prompt = evaluator._construct_prompt(individual)

        for interval_index, interval_run in enumerate(interval_runs, start=1):
            llm_interval = int(interval_run["llm_interval"])
            print(
                f"[Final Test] individual {individual_index}/{len(selected_individuals)} "
                f"interval {interval_index}/{len(interval_runs)} "
                f"({interval_run['label']}, llm_interval={llm_interval})",
                flush=True,
            )
            for opponent_index, opponent in enumerate(OPPONENT_LIST, start=1):
                print(
                    "[Final Test] "
                    f"individual {individual_index}/{len(selected_individuals)} "
                    f"interval {interval_index}/{len(interval_runs)} "
                    f"opponent {opponent_index}/{len(OPPONENT_LIST)}: "
                    f"{opponent} (mode={interval_run['label']}, llm_interval={llm_interval})",
                    flush=True,
                )
                result = evaluator.run_prompt_based_agent(
                    prompt=prompt,
                    opponent=opponent,
                    generation=generation_number,
                    llm_interval=llm_interval,
                    test=True,
                )
                match_score = dict(result["match_score"])
                metadata = dict(result.get("simulation_meta") or {})
                result_record = build_result_record(
                    individual,
                    opponent,
                    match_score,
                    str(metadata.get("log_path")),
                    trace_xml_path=str(metadata.get("trace_xml_path")) if metadata.get("trace_xml_path") else None,
                    trace_json_path=str(metadata.get("trace_json_path")) if metadata.get("trace_json_path") else None,
                )
                result_record["interval_mode"] = str(interval_run["label"])
                result_record["llm_interval"] = llm_interval

                results["results"].setdefault(individual.id, [])
                results["results"][individual.id].append(result_record)

                write_results_snapshot(results, experiment_log_dir / "final_test_results.json")

    print("[Final Test] complete", flush=True)
    return results
