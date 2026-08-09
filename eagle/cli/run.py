"""Canonical experiment preflight and EA execution."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig
from eagle.llm_errors import LLMServerError
from eagle.resume import resume_search
from eagle.runtime.config import load_runtime_config
from eagle.runtime.endpoints import health_check
from eagle.search import run_search


ENDPOINT_ERROR = """Qwen3.5 endpoint unavailable:
  URL: {url}
  Start it with: ./run_env.sh
  Inspect it with: ./run_env.sh status
  Log: runtime/logs/llm-server.log"""


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m eagle run")
    parser.add_argument("--config", required=True)
    parser.add_argument("--runtime-config", default="configs/runtime.yaml")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_path = Path(args.config).expanduser().resolve()
        runtime = load_runtime_config(args.runtime_config)
        raw = _validate_experiment_document(config_path)
        config = replace(
            ExperimentConfig.from_file(config_path),
            runs_dir=runtime.run_root,
            llm_base_url=runtime.llm.base_url,
            llm_model=runtime.llm.model_name,
            generation_backend="mock" if args.mock else "openai",
            alignment_backend="mock" if args.mock else "openai",
        )
        config.validate()
        if not args.mock:
            ok, _ = health_check(runtime, retries=1)
            if not ok:
                raise LLMServerError(ENDPOINT_ERROR.format(url=runtime.llm.base_url))
        print("EAGLE experiment")
        print(f"Config: {config_path.relative_to(runtime.project_root) if config_path.is_relative_to(runtime.project_root) else config_path}")
        print("Model: Qwen3.5-9B")
        print(f"Endpoint: {runtime.llm.base_url}")
        print(f"Resume: {'yes' if args.resume else 'no'}")
        if args.resume:
            result = resume_search(
                config, config_path=config_path,
                run_dir=args.resume.expanduser().resolve(), mock=args.mock,
            )
        else:
            result = run_search(config, config_path=config_path, mock=args.mock)
        print(f"run_dir={result.run_dir}")
        print(f"completed_generation={result.completed_generation}")
        return 0
    except (OSError, ValueError, RuntimeError, LLMServerError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _validate_experiment_document(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Experiment config must contain a YAML mapping.")
    if payload.get("schema_version") not in {None, "experiment-v1"}:
        raise ValueError(f"Unsupported experiment schema version: {payload.get('schema_version')!r}")
    if payload.get("algorithm", "nsga2") != "nsga2":
        raise ValueError("The canonical EAGLE algorithm is nsga2.")
    if payload.get("application", "microrts") != "microrts":
        raise ValueError("The configured application plugin is not supported.")
    if payload.get("objectives", {"game_performance": "maximize", "code_quality": "maximize"}) != {
        "game_performance": "maximize", "code_quality": "maximize",
    }:
        raise ValueError("Objectives must be game_performance and code_quality, both maximize.")
    forbidden = {
        "llm_base_url", "llm_model", "llm_role_topology_path", "required_llm_roles",
        "servers", "server_binary", "role_mapping", "endpoints", "endpoint",
        "base_url", "model", "model_name", "model_path", "host", "port",
    }
    found = sorted(forbidden.intersection(payload))
    llm = payload.get("llm")
    if isinstance(llm, dict):
        forbidden_llm = forbidden | {"mode", "remote", "roles", "role_mapping", "operations"}
        found.extend(f"llm.{key}" for key in sorted(forbidden_llm.intersection(llm)))
    if found:
        raise ValueError("Experiment config cannot select runtime endpoints or models: " + ", ".join(sorted(found)))
    return payload
