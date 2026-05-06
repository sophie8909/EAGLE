from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "prompt"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eagle.config import load_config_from_json
from eagle.eval.microrts.full_game_evaluator import FullGameEvaluator
from eagle.main import _resolve_component_pool_path
from eagle.utils.checkpoint import CheckpointManager, deserialize_individual
from eagle.utils.component_pool import ComponentPool
from eagle.evolution.component.log_parse import parse_individuals_from_ea_log


def _sorted_fronts_from_checkpoint_population(individuals: list) -> list[list]:
    """Group checkpoint-restored individuals by pareto rank when no generation log exists."""
    grouped: dict[int, list] = {}
    for individual in individuals:
        rank = int(getattr(individual, "pareto_rank", 0) or 0)
        grouped.setdefault(rank, []).append(individual)
    return [grouped[key] for key in sorted(grouped)]


def _extract_generation_number(path: Path) -> int:
    """Extract the one-based generation number from GA or MO generation logs."""
    match = re.fullmatch(r"generation_(\d+)(?:_mo)?\.txt", path.name)
    if not match:
        return -1
    return int(match.group(1))


def _ga_generation_logs(log_dir: Path) -> list[Path]:
    """Return GA generation logs, excluding multi-objective logs."""
    return [
        path for path in log_dir.glob("generation_*.txt")
        if "_mo" not in path.name and _extract_generation_number(path) >= 0
    ]


def _mo_generation_logs(log_dir: Path) -> list[Path]:
    """Return multi-objective generation logs."""
    return [
        path for path in log_dir.glob("generation_*_mo.txt")
        if _extract_generation_number(path) >= 0
    ]


def _detect_ea_mode(log_dir: Path) -> str | None:
    """Detect whether one log directory contains GA or multi-objective logs."""
    if _mo_generation_logs(log_dir):
        return "mo"
    if _ga_generation_logs(log_dir):
        return "ga"
    return None


def _latest_generation_log(log_dir: Path, ea_mode: str) -> Path:
    """Resolve the latest generation log for one EA mode."""
    if ea_mode == "mo":
        candidates = _mo_generation_logs(log_dir)
    elif ea_mode == "ga":
        candidates = _ga_generation_logs(log_dir)
    else:
        candidates = _mo_generation_logs(log_dir) + _ga_generation_logs(log_dir)
    if not candidates:
        raise FileNotFoundError(f"No {ea_mode} generation logs found under {log_dir}")
    return max(candidates, key=lambda path: (_extract_generation_number(path), path.stat().st_mtime))


def load_final_groups(log_dir: Path, ea_mode: str) -> tuple[list[list], str, str]:
    """Load final MO fronts or the final GA population from logs/checkpoints."""
    resolved_mode = _detect_ea_mode(log_dir) if ea_mode == "auto" else ea_mode
    if resolved_mode in {"mo", "ga"}:
        latest_generation_log = _latest_generation_log(log_dir, resolved_mode)
        groups = parse_individuals_from_ea_log(str(latest_generation_log))
        if resolved_mode == "ga":
            groups = [[individual for group in groups for individual in group]]
        return groups, latest_generation_log.name, resolved_mode

    checkpoint_state = CheckpointManager(log_dir).load_state()
    if checkpoint_state and checkpoint_state.get("population"):
        individuals = [
            deserialize_individual(payload)
            for payload in list(checkpoint_state.get("population") or [])
        ]
        return _sorted_fronts_from_checkpoint_population(individuals), "checkpoint_population", "mo"

    raise FileNotFoundError(
        f"No generation log or checkpoint population found under {log_dir}"
    )


def _component_entry_index(value: object) -> int:
    """Read a component candidate index from a component entry."""
    if isinstance(value, dict):
        value = value.get("index", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _component_entry_enabled(value: object) -> int:
    """Read a component inclusion bit from a component entry."""
    if isinstance(value, dict):
        value = value.get("enabled", 1)
    else:
        value = 1
    try:
        return 1 if int(value) else 0
    except (TypeError, ValueError):
        return 1


def _render_prompt(evaluator: FullGameEvaluator, individual) -> str:
    """Render one prompt through the current evaluator API."""
    return evaluator._construct_prompt(individual)


def _copy_candidates_by_indices(candidates: list[list[str]], indices: set[int]) -> tuple[list[list[str]], dict[int, int]]:
    """Copy selected candidate blocks and return old->new index mapping."""
    sorted_indices = sorted(index for index in indices if 0 <= int(index) < len(candidates))
    if not sorted_indices and candidates:
        sorted_indices = [0]

    copied_candidates: list[list[str]] = []
    index_map: dict[int, int] = {}
    for new_index, old_index in enumerate(sorted_indices):
        copied_candidates.append(list(candidates[old_index]))
        index_map[old_index] = new_index
    return copied_candidates, index_map


def build_next_experiment_bundle(
    component_pool: ComponentPool,
    individuals: list,
    *,
    source_config_payload: dict,
) -> dict[str, object]:
    """Build one reduced component pool plus remapped seeds for the exported individuals."""
    reduced_components = deepcopy(component_pool.to_flat_dict())
    remapped_seeds: list[dict[str, object]] = []
    index_maps: dict[str, dict[int, int]] = {}

    for category in component_pool.component_keys:
        candidates = list(component_pool.flat_components.get(category, []))
        if not candidates:
            continue
        if category in component_pool.non_evolving_component_keys:
            reduced_components[category] = deepcopy(candidates)
            index_maps[category] = {index: index for index in range(len(candidates))}
            continue

        used_indices = {
            _component_entry_index(
                getattr(individual, "component_indices", {}).get(category, 0)
            )
            for individual in individuals
        }
        reduced_components[category], index_maps[category] = _copy_candidates_by_indices(candidates, used_indices)

    for individual in individuals:
        remapped_components = {}
        component_indices = dict(getattr(individual, "component_indices", {}) or {})
        for category, old_index in component_indices.items():
            if category not in index_maps:
                continue
            remapped_components[category] = {
                "index": index_maps[category].get(_component_entry_index(old_index), 0),
                "enabled": _component_entry_enabled(old_index),
            }

        remapped_seeds.append(
            {
                "id": getattr(individual, "id", None),
                "game_rule": 0,
                "component_indices": remapped_components,
            }
        )

    next_config_payload = deepcopy(source_config_payload)
    next_config_payload["initial_population_seeds"] = remapped_seeds
    next_config_payload["population_size"] = max(
        int(next_config_payload.get("population_size", len(remapped_seeds) or 1)),
        len(remapped_seeds),
    )

    return {
        "components": reduced_components,
        "initial_population_seeds": remapped_seeds,
        "next_experiment_config": next_config_payload,
    }


def export_final_prompt(
    *,
    log_dir: Path,
    output_root: Path,
    ea_mode: str,
    max_front: int,
) -> Path:
    """Export the final MO fronts or GA population into prompt/<run>/final_prompt/."""
    component_pool_path = log_dir / "component_pool.json"
    if not component_pool_path.exists():
        component_pool_path = Path(_resolve_component_pool_path())
    if not component_pool_path.exists():
        raise FileNotFoundError(f"Component pool not found: {component_pool_path}")

    component_pool = ComponentPool.from_json(str(component_pool_path))
    config = load_config_from_json(log_dir)
    component_pool.configure_non_evolving_keys(getattr(config, "non_evolving_prompt_components", None))
    evaluator = FullGameEvaluator(component_pool, config=config)
    source_config_payload = json.loads((log_dir / "config.json").read_text(encoding="utf-8")) if (log_dir / "config.json").exists() else {}
    groups, source_name, resolved_ea_mode = load_final_groups(log_dir, ea_mode)
    selected_fronts = groups if resolved_ea_mode == "ga" else groups[:max_front]
    selected_individuals = [
        individual
        for front in selected_fronts
        for individual in front
    ]
    export_dir = output_root / log_dir.name / "final_prompt"
    export_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "log_dir": str(log_dir),
        "source": source_name,
        "ea_mode": resolved_ea_mode,
        "group_count": len(selected_fronts),
        "front_count": len(selected_fronts) if resolved_ea_mode == "mo" else 0,
        "individual_count": len(selected_individuals),
        "groups": [],
    }

    for group_index, group in enumerate(selected_fronts, start=1):
        group_manifest = {
            "group_index": group_index,
            "front_index": group_index if resolved_ea_mode == "mo" else None,
            "label": f"front_{group_index}" if resolved_ea_mode == "mo" else "ga_population",
            "individuals": [],
        }
        for individual_index, individual in enumerate(group, start=1):
            prefix = f"front_{group_index:02d}" if resolved_ea_mode == "mo" else "ga"
            individual_dir = export_dir / f"{prefix}_{individual_index:02d}_{individual.id}"
            individual_dir.mkdir(parents=True, exist_ok=True)

            individual_payload = {
                "id": individual.id,
                "game_rule": individual.game_rule,
                "component_indices": dict(getattr(individual, "component_indices", {}) or {}),
                "fitness": list(getattr(individual, "fitness", []) or []),
                "evaluation_mode": getattr(individual, "evaluation_mode", None),
                "pareto_rank": getattr(individual, "pareto_rank", None),
                "crowding_distance": getattr(individual, "crowding_distance", None),
            }
            components_payload = component_pool.describe_individual_components(
                individual,
                include_strategy_identity=evaluator.config.include_strategy_identity_in_prompt,
            )
            prompt_text = _render_prompt(evaluator, individual)

            (individual_dir / "individual.json").write_text(
                json.dumps(individual_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (individual_dir / "components.json").write_text(
                json.dumps(components_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (individual_dir / "prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")

            group_manifest["individuals"].append(
                {
                    "id": individual.id,
                    "fitness": list(getattr(individual, "fitness", []) or []),
                    "directory": str(individual_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                }
            )
        manifest["groups"].append(group_manifest)

    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    exported_component_pool_relative_path = str((export_dir / "components.json").relative_to(PROJECT_ROOT)).replace("\\", "/")
    next_experiment_bundle = build_next_experiment_bundle(
        component_pool,
        selected_individuals,
        source_config_payload=source_config_payload,
    )
    next_experiment_bundle["next_experiment_config"]["component_pool_path"] = exported_component_pool_relative_path
    (export_dir / "components.json").write_text(
        json.dumps(next_experiment_bundle["components"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (export_dir / "initial_population_seeds.json").write_text(
        json.dumps(next_experiment_bundle["initial_population_seeds"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (export_dir / "next_experiment_config.json").write_text(
        json.dumps(next_experiment_bundle["next_experiment_config"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return export_dir


def main() -> None:
    """Export final prompts and component selections for one experiment."""
    parser = argparse.ArgumentParser(
        description=(
            "Export final prompts from one experiment into prompt/<run>/final_prompt with "
            "prompt text, individual indices, and concrete component content."
        )
    )
    parser.add_argument("--log-dir", required=True, help="Experiment directory under logs/eagle/.")
    parser.add_argument(
        "--ea-mode",
        choices=["auto", "mo", "ga"],
        default="auto",
        help="Export mode. auto detects generation_*_mo.txt vs generation_*.txt.",
    )
    parser.add_argument(
        "--max-front",
        type=int,
        default=1,
        help="How many leading MO fronts to export. Ignored for GA. Defaults to 1.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Destination root directory. Defaults to repo-root prompt/.",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    if not log_dir.is_absolute():
        log_dir = (PROJECT_ROOT / log_dir).resolve()
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = (PROJECT_ROOT / output_root).resolve()

    export_dir = export_final_prompt(
        log_dir=log_dir,
        output_root=output_root,
        ea_mode=args.ea_mode,
        max_front=max(1, int(args.max_front)),
    )
    print(f"[DONE] Exported final prompts to {export_dir}")


if __name__ == "__main__":
    main()
