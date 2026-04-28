"""Entry point for the round-level EAGLE evolutionary search."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eagle.config import EAConfig, load_config_from_json, resolve_component_pool_path
from eagle.utils.component_pool import ComponentPool

from eagle_round_evol.ga import GA
from eagle_round_evol.nsga2 import NSGA2

DEFAULT_ROUND_CONFIG_PATH = Path(__file__).resolve().with_name("config.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the round-level EAGLE evolutionary search.")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Config JSON path. Defaults to {DEFAULT_ROUND_CONFIG_PATH.as_posix()}.",
    )
    parser.add_argument(
        "--component-pool",
        type=str,
        default=None,
        help="Override component_pool_path for this run.",
    )
    parser.add_argument(
        "--population-size",
        type=int,
        default=None,
        help="Override population size.",
    )
    parser.add_argument(
        "--num-generations",
        type=int,
        default=None,
        help="Override number of generations.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Ollama model name used by the round evaluator.",
    )
    parser.add_argument(
        "--state-seed",
        type=int,
        default=None,
        help="Seed for generated round states.",
    )
    parser.add_argument(
        "--quick-run",
        action="store_true",
        help="Run a tiny smoke test: population_size=2 and num_generations=1.",
    )
    parser.add_argument(
        "--algorithm",
        type=str,
        choices=["nsga2", "ga"],
        default=None,
        help="Evolution algorithm. Defaults to config value; fallback is nsga2.",
    )
    return parser


def _load_config(args: argparse.Namespace) -> EAConfig:
    extra_payload = _load_extra_config_payload(args.config)
    if args.config:
        config = load_config_from_json(args.config)
    elif DEFAULT_ROUND_CONFIG_PATH.exists():
        config = load_config_from_json(DEFAULT_ROUND_CONFIG_PATH)
        extra_payload = _load_extra_config_payload(str(DEFAULT_ROUND_CONFIG_PATH))
    else:
        config = EAConfig()

    config.algorithm = str(args.algorithm or getattr(config, "algorithm", "nsga2")).lower()
    config.real_eval_rate = 1.0
    config.final_test_max_front = 0

    if args.component_pool:
        config.component_pool_path = args.component_pool
    if args.population_size is not None:
        config.population_size = max(2, int(args.population_size))
    if args.num_generations is not None:
        config.num_generations = max(1, int(args.num_generations))
    if args.quick_run:
        config.population_size = 2
        config.num_generations = 1
        config.enable_reflection_operator = False
        config.reproduction_operator_probs = {
            "crossover": 0.5,
            "mutation": 0.5,
            "reflection": 0.0,
        }

    config.validate()

    round_eval_model = args.model or extra_payload.get("round_eval_model")
    round_state_seed = args.state_seed if args.state_seed is not None else extra_payload.get("round_state_seed")
    if round_eval_model:
        setattr(config, "round_eval_model", str(round_eval_model))
    if round_state_seed is not None:
        setattr(config, "round_state_seed", int(round_state_seed))

    return config


def _load_extra_config_payload(config_path: str | None) -> dict:
    if not config_path:
        return {}
    path = Path(config_path)
    if path.is_dir():
        path = path / "config.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_component_pool(config: EAConfig, args: argparse.Namespace) -> ComponentPool:
    base_dir = Path(args.config).resolve().parent if args.config else DEFAULT_ROUND_CONFIG_PATH.parent
    return ComponentPool.from_json(str(resolve_component_pool_path(config, base_dir=base_dir)))


def main() -> None:
    args = _build_parser().parse_args()
    config = _load_config(args)
    component_pool = _resolve_component_pool(config, args)

    algorithm = str(getattr(config, "algorithm", "nsga2")).lower()
    if algorithm == "ga":
        evolver = GA(config, component_pool, opponent_list=[])
    elif algorithm == "nsga2":
        evolver = NSGA2(config, component_pool, opponent_list=[])
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    log_dir = evolver.create_log_folder()
    evolver.save_config(log_dir)
    print(f"[Round Evol] log_dir={log_dir}", flush=True)
    evolver.run()
    print("[Round Evol] complete", flush=True)


if __name__ == "__main__":
    main()
