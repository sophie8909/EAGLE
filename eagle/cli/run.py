"""Canonical experiment preflight and EA execution."""
from __future__ import annotations
import argparse,sys
from dataclasses import replace
from pathlib import Path
import yaml
from eagle.config import ExperimentConfig
from eagle.llm_errors import LLMServerError
from eagle.resume import resume_search
from eagle.runtime.config import load_runtime_config
from eagle.runtime.endpoints import health_check,load_resolved_endpoint
from eagle.search import run_search

def main(argv=None):
    parser=argparse.ArgumentParser(prog="python -m eagle run");parser.add_argument("--config",required=True);parser.add_argument("--runtime-config",default="configs/runtime.yaml");parser.add_argument("--resume",type=Path);parser.add_argument("--mock",action="store_true");args=parser.parse_args(argv)
    try:
        config_path=Path(args.config).expanduser().resolve();runtime=load_runtime_config(args.runtime_config);raw=_validate_experiment_document(config_path);config=replace(ExperimentConfig.from_file(config_path),runs_dir=runtime.run_root,llm_base_url=runtime.llm.base_url,llm_model=str(runtime.llm.model or "remote-model"));config.validate()
        endpoint=load_resolved_endpoint(runtime.resolved_endpoint_path) if runtime.resolved_endpoint_path.exists() else {"base_url":runtime.llm.base_url,"model":str(runtime.llm.model) if runtime.llm.model else None,"mode":runtime.llm.mode}
        if not args.mock:
            ok,_=health_check(runtime)
            if not ok: raise LLMServerError(f"LLM endpoint unavailable:\n  URL: {endpoint['base_url']}\n  Check: ./run_env.sh status")
        print(f"Experiment: {config_path}\nAlgorithm: {raw.get('algorithm')}\nApplication: {raw.get('application')}\nGenerations: {config.generations}   Population: {config.population_size}")
        if args.resume: result=resume_search(config,config_path=config_path,run_dir=args.resume.expanduser().resolve(),mock=args.mock)
        else: result=run_search(config,config_path=config_path,mock=args.mock)
        print(f"run_dir={result.run_dir}\ncompleted_generation={result.completed_generation}");return 0
    except (OSError,ValueError,RuntimeError,LLMServerError) as exc:print(f"ERROR: {exc}",file=sys.stderr);return 2

def _validate_experiment_document(path):
    payload=yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload,dict):raise ValueError("Experiment config must contain a YAML mapping.")
    if payload.get("schema_version") not in {None,"experiment-v1"}:raise ValueError(f"Unsupported experiment schema version: {payload.get('schema_version')!r}")
    if payload.get("algorithm","nsga2")!="nsga2":raise ValueError("The canonical EAGLE algorithm is nsga2.")
    if payload.get("application","microrts")!="microrts":raise ValueError("The configured application plugin is not supported.")
    if payload.get("objectives",{"game_performance":"maximize","code_quality":"maximize"}) != {"game_performance":"maximize","code_quality":"maximize"}:raise ValueError("Objectives must be game_performance and code_quality, both maximize.")
    forbidden={"llm_base_url","llm_model","llm_role_topology_path","required_llm_roles","servers","role_mapping","endpoints"}
    found=sorted(forbidden.intersection(payload))
    if found:raise ValueError("Experiment config cannot select runtime endpoints or models: "+", ".join(found))
    return payload

