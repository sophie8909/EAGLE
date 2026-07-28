"""Canonical experiment preflight and EA execution."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig
from eagle.llm_errors import LLMServerError
from eagle.resume import resume_search
from eagle.runtime.config import load_runtime_config
from eagle.runtime.endpoints import health_check, load_resolved_endpoints
from eagle.search import run_search


def main(argv: list[str] | None = None) -> int:
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
        config = ExperimentConfig.from_file(config_path)
        config.validate()
        config = replace(config, runs_dir=runtime.run_root)
        required_roles = tuple(str(role) for role in raw.get("required_llm_roles", ()))
        if not args.mock:
            endpoint_roles = _resolve_and_check_roles(runtime, required_roles)
            topology_path = _write_runtime_topology(runtime, endpoint_roles)
            config = replace(config, llm_role_topology_path=topology_path)
        print(f"Experiment: {config_path}")
        print(f"Algorithm: {raw.get('algorithm')}")
        print(f"Application: {raw.get('application')}")
        print(f"Generations: {config.generations}   Population: {config.population_size}")
        if args.resume:
            result = resume_search(
                config, config_path=config_path, run_dir=args.resume.expanduser().resolve(), mock=args.mock
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
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Experiment config must contain a YAML mapping.")
    version = payload.get("schema_version")
    if version not in {None, "experiment-v1"}:
        raise ValueError(f"Unsupported experiment schema version: {version!r}")
    if payload.get("algorithm", "nsga2") != "nsga2":
        raise ValueError("The canonical EAGLE algorithm is nsga2.")
    if payload.get("application", "microrts") != "microrts":
        raise ValueError("The configured application plugin is not supported.")
    objectives = payload.get("objectives", {"game_performance": "maximize", "code_quality": "maximize"})
    if objectives != {"game_performance": "maximize", "code_quality": "maximize"}:
        raise ValueError("Objectives must be game_performance and code_quality, both maximize.")
    roles = payload.get("required_llm_roles", ["generator", "reflector", "rewriter"])
    if not isinstance(roles, list) or any(role not in {"generator", "reflector", "rewriter"} for role in roles):
        raise ValueError("required_llm_roles contains an unsupported role.")
    payload["required_llm_roles"] = roles
    return payload


def _resolve_and_check_roles(runtime, required_roles):
    mapping_path = runtime.resolved_endpoints_path
    if mapping_path.exists():
        mapping = load_resolved_endpoints(mapping_path)
    else:
        mapping = {
            role: {"server": server.name, "base_url": server.base_url}
            for role, server in runtime.roles().items()
        }
    missing = [role for role in required_roles if role not in mapping]
    if missing:
        raise ValueError(f"Missing required LLM role(s): {', '.join(missing)}")
    checked = set()
    for role in required_roles:
        item = mapping[role]
        server = next((server for server in runtime.enabled_servers() if server.name == item["server"]), None)
        if server is None:
            raise ValueError(f"Role {role}: configured server {item['server']} is not enabled.")
        if server.name in checked:
            continue
        healthy, detail = health_check(server, runtime)
        if not healthy:
            raise RuntimeError(
                f"Role {role}; server {server.name}; URL {server.base_url}; health-check failure: {detail}"
            )
        checked.add(server.name)
    return mapping


def _write_runtime_topology(runtime, mapping) -> Path:
    servers = {}
    roles = {}
    for role, item in mapping.items():
        server = next(server for server in runtime.enabled_servers() if server.name == item["server"])
        servers[server.name] = {
            "base_url": item["base_url"].rstrip("/") + "/v1",
            "model_id": server.model_id or (server.model.stem if server.model else server.name),
            "enabled": True,
        }
        roles[role] = {"server_id": server.name, "enabled": True}
    path = runtime.runtime_root / "ea_topology.json"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"version": 1, "servers": servers, "roles": roles}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
