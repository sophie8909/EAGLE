from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "prompt"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eagle.config import load_config_from_json
from eagle.evaluation.evaluator import Evaluator
from eagle.evaluation.final_test_runner import _resolve_latest_generation_log_path
from eagle.main import _resolve_component_pool_path
from eagle.utils.checkpoint import CheckpointManager, deserialize_individual
from eagle.utils.component_pool import ComponentPool
from eagle.utils.ea_log_parse import parse_individuals_from_ea_log


def _sorted_fronts_from_checkpoint_population(individuals: list) -> list[list]:
    """Group checkpoint-restored individuals by pareto rank when no generation log exists."""
    grouped: dict[int, list] = {}
    for individual in individuals:
        rank = int(getattr(individual, "pareto_rank", 0) or 0)
        grouped.setdefault(rank, []).append(individual)
    return [grouped[key] for key in sorted(grouped)]


def load_final_fronts(log_dir: Path) -> tuple[list[list], str]:
    """Load the latest available fronts from generation logs or checkpoints."""
    generation_logs = sorted(log_dir.glob("generation_*_mo.txt"))
    if generation_logs:
        latest_generation_log = _resolve_latest_generation_log_path(log_dir)
        return parse_individuals_from_ea_log(str(latest_generation_log)), latest_generation_log.name

    checkpoint_state = CheckpointManager(log_dir).load_state()
    if checkpoint_state and checkpoint_state.get("population"):
        individuals = [
            deserialize_individual(payload)
            for payload in list(checkpoint_state.get("population") or [])
        ]
        return _sorted_fronts_from_checkpoint_population(individuals), "checkpoint_population"

    raise FileNotFoundError(
        f"No generation log or checkpoint population found under {log_dir}"
    )


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
    reduced_components = deepcopy(component_pool.components)
    remapped_seeds: list[dict[str, object]] = []
    index_maps: dict[str, dict[int, int]] = {}

    for category in component_pool.component_keys:
        candidates = list(component_pool.components.get(category, []))
        if not candidates:
            continue
        if category in component_pool.non_evolving_component_keys:
            reduced_components[category] = deepcopy(candidates)
            index_maps[category] = {index: index for index in range(len(candidates))}
            continue

        used_indices = {
            int(
                getattr(individual, "component_indices", {})
                .get(category, getattr(individual, "legacy_components", {}).get(category, 0))
            )
            for individual in individuals
        }
        reduced_components[category], index_maps[category] = _copy_candidates_by_indices(candidates, used_indices)

    for individual in individuals:
        remapped_components = {}
        component_indices = dict(getattr(individual, "component_indices", {}) or {})
        component_indices.update(dict(getattr(individual, "legacy_components", {}) or {}))
        component_indices.update(dict(getattr(individual, "strategy", {}) or {}))
        for category, old_index in component_indices.items():
            if category not in index_maps:
                continue
            remapped_components[category] = index_maps[category].get(int(old_index), 0)

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


def export_front(
    *,
    log_dir: Path,
    output_root: Path,
    max_front: int,
) -> Path:
    """Export the latest fronts into prompt/<run>/front_<N>/."""
    component_pool_path = log_dir / "component_pool.json"
    if not component_pool_path.exists():
        component_pool_path = Path(_resolve_component_pool_path())
    if not component_pool_path.exists():
        raise FileNotFoundError(f"Component pool not found: {component_pool_path}")

    component_pool = ComponentPool.from_json(str(component_pool_path))
    evaluator = Evaluator(component_pool, config=load_config_from_json(log_dir))
    source_config_payload = json.loads((log_dir / "config.json").read_text(encoding="utf-8")) if (log_dir / "config.json").exists() else {}
    fronts, source_name = load_final_fronts(log_dir)
    selected_fronts = fronts[:max_front]
    selected_individuals = [
        individual
        for front in selected_fronts
        for individual in front
    ]
    export_dir = output_root / log_dir.name / f"front_1_to_{max_front}"
    export_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "log_dir": str(log_dir),
        "source": source_name,
        "front_count": len(selected_fronts),
        "individual_count": len(selected_individuals),
        "fronts": [],
    }

    for front_index, front in enumerate(selected_fronts, start=1):
        front_manifest = {
            "front_index": front_index,
            "individuals": [],
        }
        for individual_index, individual in enumerate(front, start=1):
            individual_dir = export_dir / f"front_{front_index:02d}_{individual_index:02d}_{individual.id}"
            individual_dir.mkdir(parents=True, exist_ok=True)

            individual_payload = {
                "id": individual.id,
                "game_rule": individual.game_rule,
                "static_components": dict(getattr(individual, "legacy_components", {}) or {}),
                "strategy": dict(getattr(individual, "strategy", {}) or {}),
                "fitness": list(getattr(individual, "fitness", []) or []),
                "evaluation_mode": getattr(individual, "evaluation_mode", None),
                "pareto_rank": getattr(individual, "pareto_rank", None),
                "crowding_distance": getattr(individual, "crowding_distance", None),
            }
            components_payload = component_pool.describe_individual_components(
                individual,
                include_strategy_identity=evaluator.config.include_strategy_identity_in_prompt,
            )
            prompt_text = evaluator.construct_prompt(individual)

            (individual_dir / "individual.json").write_text(
                json.dumps(individual_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (individual_dir / "components.json").write_text(
                json.dumps(components_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (individual_dir / "prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")

            front_manifest["individuals"].append(
                {
                    "id": individual.id,
                    "fitness": list(getattr(individual, "fitness", []) or []),
                    "directory": str(individual_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                }
            )
        manifest["fronts"].append(front_manifest)

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
    """Export the final front prompts and component selections for one experiment."""
    parser = argparse.ArgumentParser(
        description=(
            "Export the latest final front from one experiment into prompt/<run>/ with "
            "prompt text, individual indices, and concrete component content."
        )
    )
    parser.add_argument("--log-dir", required=True, help="Experiment directory under logs/eagle/.")
    parser.add_argument(
        "--max-front",
        type=int,
        default=1,
        help="How many leading fronts to export. Defaults to 1.",
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

    export_dir = export_front(
        log_dir=log_dir,
        output_root=output_root,
        max_front=max(1, int(args.max_front)),
    )
    print(f"[DONE] Exported front prompts to {export_dir}")


if __name__ == "__main__":
    main()
