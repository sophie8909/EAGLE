"""Canonical experiment preflight and EA execution."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig
from eagle.llm import LLMServerError
from eagle.resume import resume_search
from eagle.runtime.config import load_runtime_config
from eagle.runtime.endpoints import health_check
from eagle.search import run_search


ENDPOINT_ERROR = """Configured llama.cpp endpoint unavailable:
  URL: {url}
  Start it with: ./run_env.sh
  Inspect it with: ./run_env.sh status
  Log: runtime/logs/llm-server.log"""


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m eagle run")
    parser.add_argument("--config", required=True)
    parser.add_argument("--runtime-config", default="configs/runtime.yaml")
    parser.add_argument(
        "--resume",
        nargs="?",
        const="latest",
        help="Resume RUN_DIR; without a path, resume the latest interrupted/resumable run.",
    )
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
            llm_model=str(runtime.llm.model_path),
            llm_model_path=str(runtime.llm.model_path),
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
        print(f"Model: {runtime.llm.model_path}")
        print(f"Endpoint: {runtime.llm.base_url}")
        resume_dir = _resolve_resume_dir(args.resume, runtime.run_root) if args.resume else None
        print(f"Resume: {'yes' if resume_dir else 'no'}")
        if resume_dir:
            result = resume_search(
                config, config_path=config_path,
                run_dir=resume_dir, mock=args.mock,
            )
        else:
            result = run_search(config, config_path=config_path, mock=args.mock)
        print(f"run_dir={result.run_dir}")
        print(f"completed_generation={result.completed_generation}")
        return 0
    except (OSError, ValueError, RuntimeError, LLMServerError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "\nEAGLE interrupted. The last completed generation was preserved. "
            "Resume with: ./run.sh configs/experiments/microrts.yaml --resume",
            file=sys.stderr,
        )
        return 130


def _resolve_resume_dir(value: str, runs_root: Path) -> Path:
    if value != "latest":
        return Path(value).expanduser().resolve()
    candidates: list[Path] = []
    for manifest_path in runs_root.glob("*/manifest.json"):
        try:
            payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("status") not in {"initialized", "running", "interrupted"}:
            continue
        if not payload.get("completed_generations"):
            continue
        candidates.append(manifest_path.parent)
    if not candidates:
        raise ValueError(f"No interrupted/resumable run found under {runs_root}.")
    return max(candidates, key=lambda path: path.name)


def _validate_experiment_document(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Experiment config must contain a YAML mapping.")
    if payload.get("schema_version") not in {None, "experiment-v1"}:
        raise ValueError(f"Unsupported experiment schema version: {payload.get('schema_version')!r}")
    if payload.get("algorithm", "lexicase") != "lexicase":
        raise ValueError("The canonical EAGLE parent-selection algorithm is lexicase.")
    if payload.get("application", "microrts") != "microrts":
        raise ValueError("The configured application plugin is not supported.")
    if payload.get("objectives", {"opponent_cases": "maximize"}) != {"opponent_cases": "maximize"}:
        raise ValueError("The evolutionary objective contract is the seven fixed opponent cases.")
    forbidden = {
        "llm_base_url", "llm_model", "llm_role_topology_path", "required_llm_roles",
        "servers", "server_binary", "role_mapping", "endpoints", "endpoint",
        "base_url", "model", "model_name", "model_path", "host", "port", "eagle_opponent",
    }
    found = sorted(forbidden.intersection(payload))
    llm = payload.get("llm")
    if isinstance(llm, dict):
        # Role-local behavior is valid in the experiment document. Endpoint,
        # model, and server selection remain owned by runtime.yaml.
        forbidden_llm = forbidden | {"mode", "remote", "role_mapping", "operations"}
        found.extend(f"llm.{key}" for key in sorted(forbidden_llm.intersection(llm)))
        if "roles" in llm:
            raise ValueError("llm.roles is obsolete; configure only llm.match_commentator settings.")
    if found:
        raise ValueError("Experiment config cannot select runtime endpoints or models: " + ", ".join(sorted(found)))
    return payload
