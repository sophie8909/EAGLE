# Canonical EAGLE Runtime Paths

This document records the ownership selected during the cleanup. Public import
paths are kept stable where they are the active package API; a responsibility
has only one implementation even when an application-facing module re-exports
it.

| Responsibility | Canonical package/module | Canonical entrypoint/data model | Canonical configuration | Deprecated alternatives removed or fenced |
|---|---|---|---|---|
| EA execution | `eagle.search` | `run_search`, `SearchResult` | `eagle.config.ExperimentConfig` from `configs/*.yaml` | Historical `archive/legacy_runtime` runners and old `run_evolution` paths are Git history only. |
| Candidate lifecycle | `eagle.candidate`, `eagle.offspring` | `Candidate`, `normalize_prompt` | Experiment config limits | Old individual/population models in archived runtime. |
| Generation | `generation.java_agent_generator` | `generate_java_agent_result` and `GeneratedJavaAgent` | `generation.backend` plus prompt templates | Split Java/function-body generators and old module validators. |
| Reflection | `eagle.mutation` | `ReflectionStage` and `ReflectionResult` | Role-routed LLM backend | Archived round-reflection/surrogate paths. |
| Prompt rewriting | `eagle.rewrite` | `PromptRewriteStage`, `PromptRewriteMutation` | `config/prompt_templates.toml` | Archived identity-shift and legacy prompt operators. |
| Mutation | `eagle.mutation`, `eagle.rewrite` | `Mutation` and the two prompt mutation operators | `mutation_rate`, role profiles | Direct Java patch/method-body mutation. |
| Crossover | `eagle.crossover` | `Crossover` | `crossover_rate` | Archived component operator copies. |
| Validation | `generation.java_agent_generator` | complete-source validation and strategy-region validation | `agent_template_path` | Old module/function validators. |
| Compilation | `evaluation.compiler` | `compile_generated_agent` | `microrts_dir`, Java toolchain | Archived Java runners and precompile helpers. |
| Runtime evaluation | `evaluation.microrts_runner`, `eagle.evaluation` | `run_microrts_match`, `evaluate_candidate` | 10-match LightRush evolution protocol | RandomAI/one-match legacy evaluators. |
| Objective calculation | `evaluation.game_performance`, `evaluation.game_metrics`, `evaluation.code_quality`, `evaluation.nsga2_objectives` | Canonical formula dataclasses and `build_objectives` | resolved experiment values and formula version | Legacy objective aliases are analysis-only and version-fenced. |
| Artifact persistence | `eagle.artifacts`, `eagle.final_test.artifacts` | versioned candidate/run/final-test writers | `resolved_config.json` and schema versions | Flat/old readers remain only where explicitly documented for historical analysis. |
| Configuration loading | `eagle.config`, `eagle.llm_profiles` | `ExperimentConfig.from_file`, role profile loading | YAML experiment config and TOML role endpoints | Equivalent config keys are not added; endpoint-to-role fallback is tracked for migration. |
| LLM role routing | `eagle.llm_profiles`, `generation.backend` | `LLMProfile`, `load_role_profiles`, stage-specific backend builders | `config/llm_endpoints.toml` and `llm_topology` | Archived Ollama/proxy launchers and split runtime LLM agents. |
| Application plugin loading | `eagle.config` boundary plus `evaluation.microrts_runner` | Explicit MicroRTS paths and runner boundary | `microrts_dir`, opponent, map, cycles | MicroRTS implementation is not moved into framework modules. |
| GUI execution | `eagle_ui.app`, `eagle_ui.__main__` | NiceGUI application entrypoint | GUI controllers read experiment config | Removed Tk/duplicate GUI trees in Git history. |
| GUI data access | `eagle.analysis.records`, controllers/views | `discover_runs`, `load_candidate_records`, `load_candidate` | canonical artifact schema | GUI-local readers and stale adapters are not added. |
| Analysis and plotting | `eagle.analysis.*`, `scripts/analysis/*` | shared records/objectives/errors plus plotting entrypoints | run artifact schema | Historical analysis fallback remains explicitly scoped for migration. |
| Experiment launch | `scripts/run_eagle.py`, `scripts/run_final_test.py`, `run.sh` | Python entrypoints; shell wrapper only for environment setup | checked-in configs and CLI overrides | Obsolete archived launchers and copied wrappers. |

## Consolidation rule

The public `evaluation.game_metrics` and `evaluation.game_performance` paths are
the canonical import paths for active callers. Their former `canonical_*`
duplicates are removed after their effective implementations are moved there.
`evaluation.code_quality` remains a special case during this cleanup because it
contains active complete-source region/static analysis APIs as well as the
failure-aware objective API; those APIs are merged before its duplicate is
removed. No production code selects an implementation by smoke mode.

The bounded final-test smoke flag is retained as a named integration protocol,
not as an EA runtime branch: it is the only current path that exercises the
pinned external champions in a short deterministic schedule.
