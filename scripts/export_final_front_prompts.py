from __future__ import annotations

import argparse
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
    fronts, source_name = load_final_fronts(log_dir)
    selected_fronts = fronts[:max_front]
    export_dir = output_root / log_dir.name / f"front_1_to_{max_front}"
    export_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "log_dir": str(log_dir),
        "source": source_name,
        "front_count": len(selected_fronts),
        "individual_count": sum(len(front) for front in selected_fronts),
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
