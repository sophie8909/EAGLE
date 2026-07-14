# Architecture Traceability Matrix

This document is the primary implementation tracking and verification checklist for the EAGLE architecture. It does not redefine the architecture. The authoritative contract remains [`../eagle_architecture_spec.md`](../eagle_architecture_spec.md); each row names exactly one responsibility-focused canonical owner.

Statuses describe the active repository after Migration Phase 1 on 2026-07-14. A path in **Implementation** or **Tests** is repository evidence, not proof that the contract is complete. A path prefixed with `Expected:` in **Artifact** is required output that the current implementation does not necessarily write.

Allowed status values:

- `✅ Implemented`: active implementation, tests, and persistence satisfy the tracked responsibility, or the row is a documentation/governance responsibility that is complete.
- `⚠️ Partial`: some required behavior exists, but one or more contract elements, tests, or artifacts are absent or conflicting.
- `❌ Missing`: the required behavior or decision does not exist in the active repository.
- `🕰️ Legacy`: the active surface implements or preserves a superseded contract and must not guide new implementation.

Priority meanings: `P0` blocks dependent architecture work; `P1` is required for contract completion; `P2` is operational or cleanup work after foundations; `P3` is optional hardening.

## Progress Summary

| Measure | Count |
| --- | ---: |
| Total tracked contracts | 75 |
| ✅ Implemented | 32 |
| ⚠️ Partial | 29 |
| ❌ Missing | 11 |
| 🕰️ Legacy | 3 |
| P0 | 54 |
| P1 | 17 |
| P2 | 4 |
| P3 | 0 |

Completion is not a simple percentage: a behavior row may be marked implemented only when its implementation, required tests, and required artifacts agree. `DEC-01` and `DEC-02` record completed normative decisions; their dependent implementation rows remain open.

## Traceability Matrix

| ID | Contract | Canonical Spec | Implementation | Tests | Artifact | Status | Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GOV-01 | Architecture authority and source precedence | Spec §1 and §29; owner: [`eagle_architecture_spec.md`](../eagle_architecture_spec.md) | `docs/README.md` | Documentation link validation | `—` | ✅ Implemented | P0 | English spec is preserved as the normative source; implementation differences are gaps. |
| GOV-02 | EAGLE scope excludes patches, fixed bodies, runtime LLM agents, surrogate research, and unrelated prompt optimizers | Spec §1 and §29; owner: [`architecture/overview.md`](../architecture/overview.md) | `generation/java_agent_generator.py`; `scripts/analyze_run.py`; `scripts/play_candidate_gui.py` | `tests/test_function_module_contract.py`; `tests/test_eagle_pipeline.py` | Current legacy readers under `runs/` compatibility paths | ⚠️ Partial | P1 | Complete-file generation is active, but legacy readers/viewer discovery remain; see G-18. |
| GOV-03 | Generated Java is an offline phenotype; matches do not use an LLM at runtime | Spec §1, §2.2, §13; owner: [`architecture/overview.md`](../architecture/overview.md) | `eagle/evaluation.py`; `evaluation/microrts_runner.py` | `tests/test_eagle_pipeline.py` | Current per-candidate generated source/classes | ✅ Implemented | P0 | No runtime-LLM match path is active. |
| CAND-01 | Candidate genotype contains `strategy_prompt`, `previous_code`, and `generation_prompt` | Spec §2.1 and §3; owner: [`architecture/candidate_model.md`](../architecture/candidate_model.md) | `eagle/candidate.py` | `tests/test_eagle_pipeline.py`; `tests/test_function_module_contract.py`; `tests/test_phase1_candidate_foundation.py` | `genotype/strategy_prompt.txt`, `genotype/previous_code.java`, `genotype/generation_prompt.txt` | ✅ Implemented | P0 | The three fields are first-class dataclass fields and canonical pre-generation artifacts. |
| CAND-02 | Candidate phenotype is one complete generated `CandidateAgent.java` | Spec §2.2 and §11; owner: [`architecture/candidate_model.md`](../architecture/candidate_model.md) | `generation/java_agent_generator.py`; `eagle/evaluation.py` | `tests/test_function_module_contract.py`; `tests/test_eagle_pipeline.py`; `tests/test_phase1_candidate_foundation.py` | `generation/normalized_candidate.java` | ✅ Implemented | P0 | Full-source generation is active and stored as `generated_java`. |
| CAND-03 | A child inherits the parent's most recently generated and evaluated Java as `previous_code` | Spec §2.3, §6.1, §29.6; owner: [`architecture/candidate_model.md`](../architecture/candidate_model.md) | `eagle/evaluation.py`; `eagle/crossover.py`; `eagle/search.py` | `tests/test_function_module_contract.py`; `tests/test_phase1_candidate_foundation.py` | `genotype/previous_code.java` | ✅ Implemented | P0 | Evaluation preserves the input field, and child construction reads the selected `parent.generated_java` phenotype. |
| CAND-04 | Preserve distinct pre-generation genotype and evaluated-phenotype states, including both pre/post Java values | Spec §2.3, §28.1, §29.27; owner: [`architecture/candidate_model.md`](../architecture/candidate_model.md) | `eagle/candidate.py`; `eagle/evaluation.py`; `eagle/artifacts.py` | `tests/test_phase1_candidate_foundation.py` | `genotype/previous_code.java` plus `generation/normalized_candidate.java` | ✅ Implemented | P0 | Evaluation and artifact readback retain both values without overwriting either one; G-01 closed. |
| CAND-05 | Candidate metadata exposes identity, variation, failure, objectives, artifact references, and timing | Spec §3; owner: [`architecture/candidate_model.md`](../architecture/candidate_model.md) | `eagle/candidate.py`; `eagle/evaluation.py` | `tests/test_phase1_candidate_foundation.py`; `tests/test_eagle_pipeline.py` | Candidate JSON plus canonical lineage/genotype/phenotype files | ✅ Implemented | P0 | Required fields are first-class; free-form metadata is no longer required for state or lineage reconstruction. |
| CAND-06 | Candidate lineage records direct parents, operator, mutation type, and all component sources | Spec §3 and §24; owner: [`artifacts/lineage_schema.md`](../artifacts/lineage_schema.md) | `eagle/candidate.py`; `eagle/crossover.py`; `eagle/search.py`; `eagle/artifacts.py` | `tests/test_phase1_candidate_foundation.py` | `lineage.json` | ✅ Implemented | P0 | Seed/copy/crossover/mutation shapes serialize first-class lineage with stable source IDs; G-14 closed. |
| EVO-01 | NSGA-II ranks and selects parent+offspring populations using two maximized objectives, retaining failures | Spec §4, §19; owner: [`architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) | `eagle/selection.py`; `eagle/search.py`; `evaluation/nsga2_objectives.py` | `tests/test_eagle_pipeline.py` | Current generation manifests and summary | ✅ Implemented | P0 | Non-dominated sorting, crowding, and elitist survivor selection are active. |
| EVO-02 | Binary tournament order is lower rank, higher crowding, then random tie-break | Spec §5; owner: [`architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) | `eagle/selection.py` | `tests/test_eagle_pipeline.py` | `—` | ⚠️ Partial | P1 | Comparator adds a dominance check before the random tie-break; record or remove that divergence. |
| EVO-03 | Uniform Crossover independently selects each of the three genotype components | Spec §6; owner: [`architecture/crossover.md`](../architecture/crossover.md) | `eagle/crossover.py` | `tests/test_eagle_pipeline.py` | Current candidate metadata | ✅ Implemented | P0 | Three independent RNG choices are present. |
| EVO-04 | Crossover persists `strategy_parent_id`, `previous_code_parent_id`, and `generation_prompt_parent_id` | Spec §6.2 and §24; owner: [`architecture/crossover.md`](../architecture/crossover.md) | `eagle/crossover.py`; `eagle/search.py` | `tests/test_phase1_candidate_foundation.py` | `crossover/provenance.json`; `lineage.json` | ✅ Implemented | P0 | All eight component choices, equal-text provenance, and seeded determinism are covered; feedback routing uses the recorded source; G-02 closed. |
| EVO-05 | Mutation selection uses gameplay evidence for Strategy Mutation and failure/code evidence for Code Mutation | Spec §10; owner: [`architecture/mutation.md`](../architecture/mutation.md) | `eagle/search.py`; `eagle/mutation.py` | `tests/test_eagle_pipeline.py` | Expected: `mutation/metadata.json` | ⚠️ Partial | P1 | A coarse failed-game switch exists; evidence completeness and provenance-aware routing are missing; G-04. |
| EVO-06 | Strategy Mutation changes only `strategy_prompt` and preserves the other genotype components | Spec §8; owner: [`architecture/mutation.md`](../architecture/mutation.md) | `eagle/mutation.py` | `tests/test_eagle_pipeline.py`; `tests/test_function_module_contract.py` | Expected: `mutation/metadata.json` | ⚠️ Partial | P0 | Copy semantics exist, but the default backend is a local no-op rather than the required LLM workflow; G-03. |
| EVO-07 | Strategy Reflection LLM consumes complete 10-match/behavior evidence and returns reflection only | Spec §8.1; owner: [`architecture/mutation.md`](../architecture/mutation.md) | `eagle/mutation.py`; `eagle/search.py` | No LLM/evidence contract test | Expected: `mutation/reflection_request.txt`, `reflection_response_raw.txt` | ⚠️ Partial | P0 | A prompt builder exists with a small evidence subset; no configured LLM call, retry, or durable raw response; G-03/G-04. |
| EVO-08 | Strategy Rewrite LLM consumes reflection and returns only a rewritten Strategy Prompt | Spec §8.2–8.3; owner: [`architecture/mutation.md`](../architecture/mutation.md) | `eagle/mutation.py`; `eagle/offspring.py` | No rewrite-output/order test | Expected: `mutation/rewrite_request.txt`, `rewrite_response_raw.txt` | ⚠️ Partial | P0 | Rewrite prompt exists, but the default backend returns the original prompt and output validation is absent; G-03. |
| EVO-09 | Code Mutation changes only `generation_prompt` and preserves strategy/previous Java | Spec §9; owner: [`architecture/mutation.md`](../architecture/mutation.md) | `eagle/mutation.py` | `tests/test_eagle_pipeline.py`; `tests/test_function_module_contract.py` | Expected: `mutation/metadata.json` | ⚠️ Partial | P0 | Copy semantics exist, but the required LLM workflow is not active; G-03. |
| EVO-10 | Code Reflection LLM consumes generation, validation, compilation, integration, runtime, capability, and alignment evidence | Spec §9.1; owner: [`architecture/mutation.md`](../architecture/mutation.md) | `eagle/mutation.py`; `eagle/search.py` | No complete-evidence/LLM test | Expected: `mutation/reflection_request.txt`, `reflection_response_raw.txt` | ⚠️ Partial | P0 | Prompt builder consumes partial current scoring evidence and has no integration/capability/alignment payload; G-03/G-04. |
| EVO-11 | Code Rewrite LLM returns only a revised full-file Code Generation Prompt | Spec §9.2–9.3; owner: [`architecture/mutation.md`](../architecture/mutation.md) | `eagle/mutation.py`; `eagle/offspring.py` | No rewrite-output/order test | Expected: `mutation/rewrite_request.txt`, `rewrite_response_raw.txt` | ⚠️ Partial | P0 | Rewrite prompt exists, but the default backend is inert and output validation is absent; G-03. |
| EVO-12 | Every copied, crossed, or mutated offspring invokes final Java Generation after variation | Spec §4, §6.3, §7, §11; owner: [`architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) | `eagle/search.py`; `eagle/evaluation.py` | `tests/test_eagle_pipeline.py`; `tests/test_function_module_contract.py` | Current generated source/result | ✅ Implemented | P0 | Child evaluation always calls the Java generator. |
| EVO-13 | LLM accounting is 1 call for crossover-only and Reflection+Rewrite+Generation for mutation, with alignment owned by evaluation | Spec §20; owner: [`architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) | `eagle/mutation.py`; `generation/backend.py`; `eagle/llm_logging.py` | `tests/test_llm_logging.py` | Current `logs/llm_calls/`; expected mutation/alignment attempts in timing | ⚠️ Partial | P0 | Final generation calls/retries are logged; mutation/alignment calls are not real/logged; G-03/G-13. |
| GEN-01 | Final generation request is composed from Strategy Prompt, latest Previous Code, and Code Generation Prompt | Spec §11; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `eagle/candidate.py`; `generation/backend.py` | `tests/test_function_module_contract.py`; `tests/test_eagle_pipeline.py` | Current request in LLM call log; expected `generation/request.txt` | ✅ Implemented | P0 | Complete child genotype is included in the generation input. |
| GEN-02 | Generation output is one complete Java source, never patch/diff/JSON/body map/prose | Spec §11; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/java_agent_generator.py`; `eagle/candidate.py` | `tests/test_function_module_contract.py`; `tests/test_eagle_pipeline.py` | Current generated source | ✅ Implemented | P0 | Complete-file boundary is enforced. |
| GEN-03 | Final-generation backend retries according to explicit policy | Spec §20 and §23; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/backend.py` | `tests/test_llm_logging.py` | Current per-attempt LLM log | ✅ Implemented | P1 | HTTP backend has bounded attempts and error logging. |
| GEN-04 | Every raw generation response is preserved before extraction, including failures and mock calls | Spec §11 and §23; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/backend.py`; `generation/java_agent_generator.py`; `eagle/artifacts.py`; `eagle/llm_logging.py` | `tests/test_llm_logging.py`; `tests/test_eagle_pipeline.py` | Current candidate result/failure debug/LLM log; expected `generation/response_raw.txt` per attempt | ⚠️ Partial | P0 | Raw data is present on several paths, but not in the canonical durable layout and mock calls are not logged; G-12. |
| GEN-05 | Extract exactly one complete Java source from raw or a single full Java fence | Spec §11 and §23; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/java_agent_generator.py` | `tests/test_eagle_pipeline.py` | Current `extracted_code.java`; expected `generation/extracted_candidate.java` | ✅ Implemented | P1 | Active extractor rejects unsupported response shapes. |
| GEN-06 | Normalize extracted Java before validation while retaining raw/extracted forms | Spec §23; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/java_agent_generator.py` | `tests/test_eagle_pipeline.py` | Current accepted source; expected separate extracted/normalized files | ✅ Implemented | P1 | Normalization exists; separate persistence is tracked in GEN-04/ART-02. |
| VAL-01 | Source validation rejects malformed Java and validates external MicroRTS/security requirements | Spec §12; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/java_agent_generator.py`; `generation/agent_template.py` | `tests/test_function_module_contract.py`; `tests/test_eagle_pipeline.py` | Current validation result in candidate result | ⚠️ Partial | P0 | Structural checks exist but mix the resolved external contract with fixed template internals; G-09. |
| VAL-02 | Validation permits arbitrary internal structure and enforces the resolved package/class/superclass/constructor/method/load contract | Spec §12 and §29.4/21; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/java_agent_generator.py`; `generation/agent_template.py`; `eagle/java_templates/CandidateAgent.java` | Current tests enforce markers/helpers | Expected: `validation/result.json`; `integration/result.json` | ❌ Missing | P0 | The exact external contract is now normative; current validation still requires fixed markers/six helpers and lacks parts of that contract; G-09. |
| VAL-03 | Generated Java cannot use network, processes, unauthorized file I/O, runtime modification, or unavailable dependencies | Spec §12; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `generation/java_agent_generator.py` | `tests/test_eagle_pipeline.py` | Expected: persisted security checks in `validation/result.json` | ⚠️ Partial | P0 | A regex deny-list exists but does not constitute the complete security/runtime contract; G-09. |
| VAL-04 | Validated Java is compiled once in an isolated candidate output directory with the MicroRTS classpath | Spec §13 and §29.11; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `evaluation/compiler.py`; `eagle/evaluation.py` | `tests/test_function_module_contract.py`; `tests/test_eagle_pipeline.py` | Current candidate classes/compile result; expected `compilation/` | ✅ Implemented | P0 | One compile result is reused by the current match loop. |
| VAL-05 | `javac` uses explicit warning flags and structured, deduplicated error/warning diagnostics | Spec §17.1; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `evaluation/compiler.py`; `evaluation/code_quality.py` | No canonical warning parser/cap test | Expected: `compilation/result.json`, stdout, stderr, command | ❌ Missing | P0 | No `-Xlint`; diagnostics rely on text matching and current penalty contract differs; G-10. |
| EVAL-01 | A distinct MicroRTS integration stage runs the seven resolved load/type/constructor/reset/clone/getAction/result checks without starting matches | Spec §12.1, §13.1, and §16.5; owner: [`evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md) | `eagle/evaluation.py`; `evaluation/microrts_runner.py` | No distinct integration fixture | Expected: `integration/result.json` | ❌ Missing | P0 | The checks are now normative, but the first match process still conflates integration and runtime; G-11. |
| EVAL-02 | The evaluation opponent is `ai.abstraction.LightRush` | Spec §13 and §29.14; owner: [`evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md) | `eagle/config.py`; `evaluation/microrts_runner.py` | `tests/test_eagle_pipeline.py` | Current match command/result | ✅ Implemented | P0 | Active config parsing forces LightRush. |
| EVAL-03 | Compile once and execute exactly 10 matches using identical Java/classes without regeneration | Spec §13 and §29.11–13; owner: [`evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md) | `eagle/config.py`; `eagle/evaluation.py`; `configs/` | Current tests cover configurable loop, not 10/no-regeneration hash | Expected: 10 match directories with identical source/class hashes | ⚠️ Partial | P0 | Reuse exists, but default/configured counts are 1 or 3 and no hash/call invariant test exists; G-05. |
| EVAL-04 | Each match has separate artifacts and a distinct persisted seed where supported | Spec §13 and §26; owner: [`evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md) | `eagle/evaluation.py`; `evaluation/microrts_runner.py` | `tests/test_eagle_pipeline.py` | Current per-match directories named with `seed_none`; expected `match_00`…`match_09` | ⚠️ Partial | P0 | Directories exist; seed/config support is absent and map is fixed; G-11/G-15. |
| EVAL-05 | Aggregate only 10 valid matches; partial/missing/unparseable batches fail while preserving evidence | Spec §13, §14.1, §14.8; owner: [`evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md) | `eagle/evaluation.py`; `evaluation/game_metrics.py`; `evaluation/microrts_runner.py` | `tests/test_eagle_pipeline.py` | Current match results; expected evaluation stage payloads | ⚠️ Partial | P0 | Current code averages successful matches and does not enforce a 10-result batch; G-05/G-11. |
| EVAL-06 | Any evaluation failure or fewer than 10 valid matches yields `game_performance = -1000` | Spec §14.1 and §14.8; owner: [`evaluation/failure_classification.md`](../evaluation/failure_classification.md) | `evaluation/nsga2_objectives.py`; `eagle/evaluation.py` | `tests/test_eagle_pipeline.py` | Current objectives in result/summary | ✅ Implemented | P0 | Failure constant exists; partial-batch detection itself remains EVAL-05. |
| EVAL-07 | Per-match `game_performance` uses ±100/0 plus bounded material/resource/survival shaping | Spec §14.2–14.7; owner: [`evaluation/game_performance.md`](../evaluation/game_performance.md) | `evaluation/game_performance.py`; `evaluation/game_metrics.py` | `tests/test_eagle_pipeline.py` | Current performance breakdown uses superseded fields | 🕰️ Legacy | P0 | Active formula has unbounded state/resource terms and a large survival reward; G-06. |
| EVAL-08 | Candidate `game_performance` is the 10-match mean with required aggregate statistics and formula version | Spec §14.8; owner: [`evaluation/game_performance.md`](../evaluation/game_performance.md) | `evaluation/game_metrics.py`; `evaluation/game_performance.py` | No canonical 10-match/statistics test | Expected: `evaluation/game_performance.json` | ❌ Missing | P0 | Current aggregation omits required statistics/version and accepts fewer matches; G-06. |
| EVAL-09 | Successful `code_quality` uses the selected `+500` base with warning, capability, and independent alignment components; range `[0, 610]` | Spec §17; owner: [`evaluation/code_quality.md`](../evaluation/code_quality.md) | `evaluation/code_quality.py`; `eagle/evaluation.py` | `tests/test_code_quality.py` | Current code-quality payload | 🕰️ Legacy | P0 | The canonical base is resolved; active scoring still uses marker validity and text metrics; G-07. |
| EVAL-10 | Failure-stage `code_quality` strictly orders generation/validation < compilation < integration < runtime < success | Spec §16; owner: [`evaluation/failure_classification.md`](../evaluation/failure_classification.md) | `eagle/evaluation.py`; `evaluation/code_quality.py`; `evaluation/nsga2_objectives.py` | No boundary hierarchy fixtures | Expected: `evaluation/code_quality.json`; stage results | ❌ Missing | P0 | Coarse categories and current totals do not implement required ranges; G-08. |
| EVAL-11 | Successful compilation score uses the canonical deduplicated-warning penalty and cap | Spec §17.1; owner: [`evaluation/code_quality.md`](../evaluation/code_quality.md) | `evaluation/compiler.py`; `evaluation/code_quality.py` | No canonical warning formula test | Expected: compiler diagnostics plus `evaluation/code_quality.json` | ❌ Missing | P0 | Current compiler/scorer uses a different status-based component; G-07/G-10. |
| EVAL-12 | Function capability score evaluates economy, production, combat, targeting, and state awareness without fixed method names | Spec §17.2; owner: [`evaluation/code_quality.md`](../evaluation/code_quality.md) | `evaluation/code_quality.py` | `tests/test_code_quality.py` tests current static metrics | Expected: capability breakdown in `evaluation/code_quality.json` | ❌ Missing | P1 | Current helper/call text metrics are not the five capability contract; G-07. |
| EVAL-13 | Independent Strategy Alignment LLM returns validated `score` 0–10 and `reason`, as a code-quality component only | Spec §17.3 and §20.4; owner: [`evaluation/code_quality.md`](../evaluation/code_quality.md) | `evaluation/code_quality.py`; `scripts/analyze_run.py`; `configs/` | Legacy migration test only in `tests/test_code_quality.py` | Expected: `strategy_alignment/request.txt`, `response_raw.txt`, `result.json` | ❌ Missing | P1 | Active evaluator is absent; legacy readers/config names are not implementation; G-16. |
| EVAL-14 | Optimizer output contains exactly `game_performance` and `code_quality` | Spec §1, §19, §29.15; owner: [`architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) | `evaluation/nsga2_objectives.py`; `eagle/selection.py`; `eagle/artifacts.py` | `tests/test_eagle_pipeline.py`; `tests/test_code_quality.py` | Current objectives/summary | ✅ Implemented | P0 | `strategy_alignment` is read-only legacy migration, not an active objective. |
| ART-01 | Run artifacts preserve input config, resolved config, run summary, generations, populations, and candidates | Spec §21 and §27; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `eagle/artifacts.py`; `eagle/search.py` | `tests/test_eagle_pipeline.py`; `tests/test_phase1_candidate_foundation.py` | Input `config.yaml`, `resolved_config.json`, flat summary/results, and Phase 1 candidate subtrees | ⚠️ Partial | P1 | Resolved config and canonical candidate state exist; the complete `generations/` and typed stage/match hierarchy remains G-12. |
| ART-02 | Generation artifacts preserve request, every raw response/retry, extracted Java, normalized Java, and errors | Spec §23; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `generation/backend.py`; `generation/java_agent_generator.py`; `eagle/artifacts.py`; `eagle/llm_logging.py` | `tests/test_llm_logging.py`; `tests/test_eagle_pipeline.py` | Current logs/result/debug files; expected `generation/` subtree | ⚠️ Partial | P0 | Evidence is split/duplicated and not canonical or complete for all backends/failures; G-12. |
| ART-03 | Mutation artifacts persist both requests/raw responses, models, attempts, status/errors, and explicit no-mutation metadata | Spec §22; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `eagle/mutation.py`; `eagle/artifacts.py` | No mutation artifact retention test | Expected: `mutation/metadata.json` and four request/response files | ❌ Missing | P0 | Mutation data is free-form candidate metadata and not durable per call; G-03/G-12. |
| ART-04 | Each match persists result, replay, round states, stdout/stderr, telemetry, performance, timing, and required metadata | Spec §26; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `evaluation/microrts_runner.py`; `eagle/evaluation.py` | `tests/test_eagle_pipeline.py` | Current per-match artifact directories | ⚠️ Partial | P1 | Current runner writes a subset and lacks seed/timing/schema/hash completeness; G-11/G-12. |
| ART-05 | Candidate, stage, LLM-attempt, and match UTC timestamps/monotonic durations follow one timing schema | Spec §25 and §29.25; owner: [`artifacts/timing_schema.md`](../artifacts/timing_schema.md) | `eagle/llm_logging.py`; `eagle/evaluation.py`; `evaluation/microrts_runner.py` | No unified timing tests | Expected: candidate and match `timing.json` | ❌ Missing | P1 | Only final-generation timestamps and limited match timing exist; G-13. |
| ART-06 | `lineage.json` losslessly records operator, parents, component sources, mutation, and source candidates | Spec §24 and §29.26; owner: [`artifacts/lineage_schema.md`](../artifacts/lineage_schema.md) | `eagle/candidate.py`; `eagle/crossover.py`; `eagle/artifacts.py` | `tests/test_phase1_candidate_foundation.py` | Versioned `lineage.json` for every candidate | ✅ Implemented | P0 | Exact seed/copy/crossover/mutation records and metadata-independent reconstruction are covered; G-14 closed. |
| ART-07 | `resolved_config.json` records actual operator/evaluation/LLM/retry/version/seed/Git values without silent overrides | Spec §27 and §29.28; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `eagle/artifacts.py`; `eagle/search.py`; `eagle/config.py` | `tests/test_phase1_candidate_foundation.py`; `tests/test_eagle_pipeline.py` | `resolved_config.json` | ✅ Implemented | P0 | Parsed/defaulted/forced/mock-overridden values are persisted; unsupported prompt version and match seeds are explicit nulls with reasons; G-15 closed. |
| ART-08 | Artifact schema is explicitly versioned and unknown versions are rejected or migrated | Spec §27 and §29.30; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `eagle/artifacts.py`; `scripts/analyze_run.py` | `tests/test_phase1_candidate_foundation.py` plus legacy reader tests | `artifact_schema_version` in resolved config and lineage-specific version | ⚠️ Partial | P1 | Phase 1 writes explicit versions; rejection/migration for unknown versions and all result payload versions remain G-12. |
| ART-09 | Objective formulas are explicitly versioned and identify the resolved successful-code-quality formula | Spec §17.4, §27, §29.30; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `evaluation/game_performance.py`; `evaluation/code_quality.py`; `eagle/artifacts.py` | `tests/test_phase1_candidate_foundation.py` | `objective_formula_version` in resolved config | ⚠️ Partial | P0 | The active legacy formula is truthfully identified; canonical G-06/G-07 formulas and per-objective payload versions remain open. |
| ART-10 | `candidate_result.json` indexes identity, lineage, terminal status, objectives, completed matches, and artifact references without replacing evidence | Spec §21; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `eagle/artifacts.py`; `eagle/evaluation.py` | `tests/test_eagle_pipeline.py` | Current duplicated `candidate_result.json` and `result.json` | ⚠️ Partial | P1 | Summary exists but lacks canonical references/versions and duplicates payload/source; G-12. |
| ART-11 | Validation, compilation, integration, alignment, and objective stages each persist typed result payloads | Spec §21 and §23; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `eagle/artifacts.py`; `eagle/evaluation.py`; `evaluation/compiler.py` | Current artifact smoke test only | Expected: `validation/`, `compilation/`, `integration/`, `strategy_alignment/`, `evaluation/` | ⚠️ Partial | P0 | Some results are nested in one summary; integration/alignment and canonical stage files are absent; G-12. |
| ART-12 | Generation zero and every later generation persist population manifests | Spec §21; owner: [`artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | `eagle/search.py`; `eagle/artifacts.py` | `tests/test_eagle_pipeline.py` | Current later-generation manifests | ⚠️ Partial | P1 | Generation zero is not written in the same manifest flow; G-17. |
| TEST-01 | Candidate tests cover all logical fields, pre/post Java separation, terminal retention, and state transitions | Spec §3 and §28; owner: [`testing/test_contracts.md`](../testing/test_contracts.md) | `tests/test_phase1_candidate_foundation.py`; `tests/test_eagle_pipeline.py`; `tests/test_function_module_contract.py` | Same | Test output only | ✅ Implemented | P0 | Focused tests cover distinct states, non-overwriting evaluation, inheritance, first-class lineage, deterministic provenance, and failure-stage retention. |
| TEST-02 | Mutation tests prove Reflection → Rewrite → final generation, evidence completeness, component isolation, and failure retention | Spec §7–10 and §22; owner: [`testing/test_contracts.md`](../testing/test_contracts.md) | `tests/test_eagle_pipeline.py`; `tests/test_function_module_contract.py`; `eagle/mutation.py` | Same | Test output only | ⚠️ Partial | P0 | Existing tests preserve current local/no-op behavior and do not prove three LLM stages. |
| TEST-03 | Generation/validation/compilation tests prove raw durability, arbitrary internals, security, diagnostics, compile-once, and no regeneration | Spec §11–13 and §23; owner: [`testing/test_contracts.md`](../testing/test_contracts.md) | `tests/test_function_module_contract.py`; `tests/test_eagle_pipeline.py`; `tests/test_llm_logging.py` | Same | Test output only | ⚠️ Partial | P0 | Complete-file/retry tests exist; current tests also enforce non-normative markers/helpers. |
| TEST-04 | Evaluation/objective tests prove 10 LightRush matches, canonical formulas, partial failure, stage hierarchy, capability, and alignment | Spec §13–19; owner: [`testing/test_contracts.md`](../testing/test_contracts.md) | `tests/test_eagle_pipeline.py`; `tests/test_code_quality.py` | Same | Test output only | ⚠️ Partial | P0 | Tests cover current formulas/protocol, not the canonical evaluation contracts. |
| TEST-05 | Artifact tests prove golden trees, schemas, hashes, timing, lineage, resolved config, reconstruction, and interruption safety | Spec §21–27; owner: [`testing/test_contracts.md`](../testing/test_contracts.md) | `tests/test_phase1_candidate_foundation.py`; `tests/test_eagle_pipeline.py`; `tests/test_llm_logging.py` | Same | Test output only | ⚠️ Partial | P1 | Phase 1 lineage, genotype/phenotype readback, and resolved config are covered; full golden trees, hashes, timing, migrations, and interruption safety remain. |
| TEST-06 | Regression includes a bounded current-source real Java/MicroRTS smoke and fences every supported legacy schema | Spec §29–30; owner: [`testing/test_contracts.md`](../testing/test_contracts.md) | `tests/`; `scripts/analyze_run.py` | No current complete-file real integration regression | Test output only | ❌ Missing | P1 | Old runs and mock search are not architecture proof; G-17/G-18. |
| IMPL-01 | Repository map assigns active modules to canonical responsibility owners | Maintenance contract; owner: [`repository_map.md`](repository_map.md) | `docs/implementation/repository_map.md` | Path-existence validation | `—` | ✅ Implemented | P2 | Active source/test/config/script paths are mapped. |
| IMPL-02 | Current-status document reports only active repository behavior and legacy evidence boundaries | Maintenance contract; owner: [`current_status.md`](current_status.md) | `docs/implementation/current_status.md` | Repository evidence review | `—` | ✅ Implemented | P1 | Snapshot matches inspected active code/config/tests. |
| IMPL-03 | Architecture gaps record every spec/implementation discrepancy and architecture decision | Maintenance contract; owner: [`architecture_gaps.md`](architecture_gaps.md) | `docs/implementation/architecture_gaps.md` | Cross-check against this matrix | `—` | ✅ Implemented | P0 | G-01–G-18 cover implementation gaps; A-01/A-02 preserve the resolved decision history. |
| IMPL-04 | Migration plan orders work by dependency and does not implement later layers on unstable foundations | Spec §30; owner: [`migration_plan.md`](migration_plan.md) | `docs/implementation/migration_plan.md` | Dependency-graph review | `—` | ✅ Implemented | P0 | Phases 0–8 follow the normative priority. |
| IMPL-05 | Legacy compatibility cannot override active complete-file, two-objective, 10-match LightRush contracts | Spec §29.29 and §30.18; owner: [`migration_plan.md`](migration_plan.md) | `scripts/analyze_run.py`; `scripts/play_candidate_gui.py`; `generation/parsing.py`; retained `runs/` | `tests/test_code_quality.py`; `tests/test_eagle_pipeline.py` | Historical unversioned/split artifacts | 🕰️ Legacy | P2 | Compatibility is still present and must be fenced by schema/version before removal; G-18. |
| OPS-01 | Run workflow is WSL-first and distinguishes current smoke from contract-conformant evaluation | Operational contract; owner: [`operations/running_eagle.md`](../operations/running_eagle.md) | `scripts/run_eagle.py`; `run.sh`; `configs/` | Manual preflight; unit suite | Run directory created only when intentionally executed | ✅ Implemented | P2 | Documentation accurately warns that checked-in configs are non-conformant. |
| OPS-02 | Analysis/debug workflow follows typed stage artifacts, formula/schema versions, and explicit legacy migration | Operational contract; owner: [`operations/inspecting_runs.md`](../operations/inspecting_runs.md) | `scripts/analyze_run.py`; `scripts/analysis/plot_game_performance_by_generation.py`; `scripts/play_candidate_gui.py` | `tests/test_eagle_pipeline.py`; `tests/test_code_quality.py` | Analysis outputs under selected run | ⚠️ Partial | P2 | Tools understand current/legacy flat data but cannot consume a canonical schema that does not yet exist; G-17/G-18. |
| TRACE-01 | This matrix gives every tracked contract one owner, evidence path, status, priority, dependency, and test/migration linkage | Documentation governance; owner: [`architecture_traceability_matrix.md`](architecture_traceability_matrix.md) | `docs/implementation/architecture_traceability_matrix.md` | Matrix validation checks below | `—` | ✅ Implemented | P0 | Update this row set whenever contracts, paths, tests, status, or documentation structure change. |
| DEC-01 | Select and version one successful `code_quality` base that guarantees success > runtime failure | Spec §17.4 and §29.20/33; owner: [`evaluation/code_quality.md`](../evaluation/code_quality.md) | `docs/eagle_architecture_spec.md`; `docs/evaluation/code_quality.md` | Required future cross-stage ordering/formula-version test | `objective_formula_version` currently identifies the active legacy formula | ✅ Implemented | P0 | Decision recorded 2026-07-14: use the explicit `+500` base with range `[0, 610]`; canonical formula implementation remains G-07/ART-09. |
| DEC-02 | Define exact Java package/class/superclass/constructor/method identity and ordered integration checks without fixed internals | Spec §12.1, §16.5, and §29.31–32; owner: [`architecture/java_generation.md`](../architecture/java_generation.md) | `docs/eagle_architecture_spec.md`; `docs/architecture/java_generation.md`; `docs/evaluation/evaluation_pipeline.md` | Required future validation/integration fixture set | Expected: validation/integration artifacts when implemented | ✅ Implemented | P0 | Decision recorded 2026-07-14: exact identity plus seven ordered pre-match checks; implementation remains G-09/G-11. |

## Dependency Graph

`Required Before` identifies the first downstream contracts that must wait. It is not a schedule estimate.

| Contract | Depends On | Required Before |
| --- | --- | --- |
| DEC-01 successful-code-quality base | Resolved by specification §17.4 | EVAL-09, EVAL-10, ART-09, objective tests |
| DEC-02 Java identity/integration checks | Resolved by specification §12.1 and §16.5 | VAL-02, EVAL-01, failure-boundary tests |
| CAND-04 lossless state transition | CAND-01, CAND-02 | CAND-03, EVO-04, ART-06, mutation state tests |
| CAND-06 / ART-06 lineage | CAND-04 | EVO-04, mutation feedback selection, artifact reconstruction |
| ART-07 resolved config | Contract values and version identifiers | EVAL-03, EVAL-04, ART-08, ART-09, reproducible runs |
| EVO-04 component provenance | CAND-03, CAND-06 | EVO-05 and provenance-aware feedback |
| EVO-07/EVO-08 Strategy Mutation calls | EVO-04, typed game evidence | EVO-06 completion, ART-03, TEST-02 |
| EVO-10/EVO-11 Code Mutation calls | typed failure evidence, EVAL-01 | EVO-09 completion, ART-03, TEST-02 |
| VAL-02 runtime-contract validation | DEC-02 | EVAL-01 and correct validation failure fitness |
| VAL-05 compiler diagnostics | VAL-02 | EVAL-11, EVAL-09, compilation failure tests |
| EVAL-01 integration stage | DEC-02, VAL-04 | EVAL-03, EVAL-05, EVAL-10 |
| EVAL-03 10-match protocol | EVAL-01, ART-07 | EVAL-05, EVAL-08, EVAL-09 |
| EVAL-07/EVAL-08 Game Performance | EVAL-03, EVAL-04 | objective-version artifacts and NSGA-II contract tests |
| EVAL-10 failure hierarchy | EVAL-01, VAL-05, DEC-01 | final objective assembly and failure regression |
| EVAL-12 function capability | EVAL-03 telemetry contract | EVAL-09 |
| EVAL-13 Strategy Alignment | EVAL-03, generation artifacts | EVAL-09 |
| ART-02/ART-03 raw LLM evidence | real mutation/generation stages | ART-05 timing and reconstruction tests |
| ART-05 timing | all stage boundaries and retry records | canonical artifact completion |
| ART-08/ART-09 versions | ART-07, DEC-01, stable schemas/formulas | analysis migration and legacy removal |
| TEST-06 real regression | all P0 runtime/evaluation contracts | IMPL-05 legacy removal |

## Suggested Milestones

1. **Normative blockers resolved:** DEC-01 and DEC-02 are recorded in the authoritative specification; dependent implementation remains open.
2. **Lossless state established:** Candidate genotype/phenotype separation, generated-Java inheritance, lineage, component provenance, and resolved configuration are active; G-12 retains the broader artifact completion work.
3. **Correct variation:** use latest evaluated Java, provenance-aware feedback, and real two-stage Strategy/Code Mutation with durable LLM evidence.
4. **Define executable boundaries:** replace fixed-internal validation, add structured compiler diagnostics, and implement a distinct integration stage.
5. **Enforce evaluation protocol:** run one compiled source for exactly 10 seeded LightRush matches with strict result validation and partial-batch failure.
6. **Implement objectives:** migrate bounded Game Performance, failure-stage fitness, capability scoring, and independent Strategy Alignment while retaining two NSGA-II objectives.
7. **Complete persistence:** write the canonical artifact/timing hierarchy, hashes, schema/formula versions, and readback reconstruction.
8. **Replace tests and operations:** add contract fixtures, a bounded real MicroRTS smoke, canonical readers, and schema-aware analysis.
9. **Remove legacy surfaces:** delete obsolete split/function-body, fixed-marker fitness, one-match, legacy alignment-objective, and unversioned compatibility paths after supported migrations exist.

## Missing Tests

This table lists absent or materially incomplete proof. A row may be removed only when the named contract test exists and passes.

| Contract | Required Test | Priority |
| --- | --- | --- |
| EVO-02 | Prove rank → crowding → random tie-break with no extra comparison. | P1 |
| EVO-07/EVO-08 | Assert Strategy Reflection → Rewrite → final generation call order, full evidence, prompt-only output, retry/failure retention. | P0 |
| EVO-10/EVO-11 | Assert Code Reflection → Rewrite → final generation call order, full failure evidence, prompt-only output, retry/failure retention. | P0 |
| GEN-04 / ART-02 | Prove raw responses are durable before parsing for every attempt/backend and survive every failure path. | P0 |
| VAL-02/VAL-03 | Accept arbitrary valid internals; reject each resolved external-contract and prohibited-capability violation. | P0 |
| VAL-05/EVAL-11 | Parse/deduplicate `-Xlint` diagnostics and prove warning penalty/cap. | P0 |
| EVAL-01 | Fixture each ordered integration check and distinguish integration from compilation/runtime. | P0 |
| EVAL-03/EVAL-04 | Assert one generation, one compile, identical source/class hashes, 10 LightRush calls, distinct directories/seeds. | P0 |
| EVAL-05 | Fail a nine-result batch while preserving all completed match evidence. | P0 |
| EVAL-07/EVAL-08 | Prove exact canonical components, `tanh` saturation, clamp/bands, 10-match mean, statistics, and player perspective. | P0 |
| EVAL-09/EVAL-10 | Prove every failure boundary and resolved successful formula preserve strict stage ordering. | P0 |
| EVAL-12 | Score all five capabilities from reachable static/runtime/telemetry evidence without method-name dependence. | P1 |
| EVAL-13 | Validate structured alignment response, bounds, reason persistence, retry/failure behavior, and two-objective boundary. | P1 |
| ART-01–ART-12 | Golden tree/schema/readback/hash/version/timing/interruption tests for seed, crossover, both mutations, and every failure stage. | P0 |
| TEST-06 | Bounded real complete-file Java/MicroRTS integration regression in WSL. | P1 |

## Legacy Mapping

| Current Component | Replacement Contract | Migration Status | Legacy Removal Condition |
| --- | --- | --- | --- |
| Fixed strategy/action markers and six helper declarations in `generation/agent_template.py` and `generation/java_agent_generator.py` | VAL-02 external runtime contract | Blocked by DEC-02 | Resolved identity/integration spec, validator fixtures, and valid arbitrary-internal agents pass. |
| Marker/static-text fitness in `evaluation/code_quality.py` | EVAL-11–EVAL-13 successful Code Quality | Blocked by DEC-01 and evaluation telemetry | Versioned canonical formula and cross-stage tests pass. |
| Local no-op `RuleBasedMutationBackend` | EVO-07/EVO-08/EVO-10/EVO-11 real LLM stages | Not started | Real staged calls, output validation, artifacts, timing, and failure tests pass. |
| Generic `behavior_parent` and prompt-equality feedback | EVO-04 + ART-06 component provenance | Completed in Phase 1 | Active writes and feedback routing use versioned first-class provenance; old artifacts remain legacy evidence only. |
| Flat run/candidate files and duplicate source/result payloads | ART-01–ART-12 canonical artifact schema | Phase 1 foundation | Canonical lineage/genotype/phenotype/config paths exist; complete stage trees, readers, and duplicate removal remain G-12. |
| Copied input config with silently forced opponent | ART-07 resolved configuration | Completed in Phase 1 | Input config remains preserved separately while resolved runtime values, versions, unsupported fields, and Git commit round-trip. |
| One/three-match checked-in configs | EVAL-03 10-match protocol | Not started | Architecture configs and call/hash tests enforce exactly 10. |
| `strategy_alignment` reader/config/help remnants | EVAL-13 as a Code Quality component only | Analysis-only compatibility | Active config/help/output are clean and supported legacy schema migration is version-gated. |
| Split/function-body and old generated-class run discovery | GOV-02 complete-file `CandidateAgent.java` boundary | Legacy compatibility | Supported legacy formats are explicitly versioned/migrated or their retention window ends. |
| Secondary bypassed `generation/parsing.py` | GEN-05 single active extraction contract | Review required | Confirm no supported reader imports it, then remove with regression coverage. |
| GUI default/alternate opponents in `scripts/play_candidate_gui.py` | OPS-02 manual viewer boundary; EVAL-02 evaluation remains LightRush | Transitional | Viewer reads canonical artifacts and clearly cannot write evolutionary fitness. |

## Cross References

Every active English documentation file is listed. “Owns” means the file is the single responsibility-focused owner for these matrix rows; supporting links do not transfer ownership.

| Document | Owned Contracts |
| --- | --- |
| [`docs/README.md`](../README.md) | GOV-01 task routing and maintenance policy |
| [`docs/eagle_architecture_spec.md`](../eagle_architecture_spec.md) | GOV-01 global normative source; all rows are subordinate to it |
| [`docs/architecture/overview.md`](../architecture/overview.md) | GOV-02, GOV-03 system boundary |
| [`docs/architecture/candidate_model.md`](../architecture/candidate_model.md) | CAND-01–CAND-05 |
| [`docs/architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) | EVO-01, EVO-02, EVO-12, EVO-13, EVAL-14 |
| [`docs/architecture/crossover.md`](../architecture/crossover.md) | EVO-03, EVO-04 |
| [`docs/architecture/mutation.md`](../architecture/mutation.md) | EVO-05–EVO-11 |
| [`docs/architecture/java_generation.md`](../architecture/java_generation.md) | GEN-01–GEN-06, VAL-01–VAL-05, DEC-02 |
| [`docs/evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md) | EVAL-01–EVAL-05 |
| [`docs/evaluation/game_performance.md`](../evaluation/game_performance.md) | EVAL-07, EVAL-08 |
| [`docs/evaluation/code_quality.md`](../evaluation/code_quality.md) | EVAL-09, EVAL-11–EVAL-13, DEC-01 |
| [`docs/evaluation/failure_classification.md`](../evaluation/failure_classification.md) | EVAL-06, EVAL-10 |
| [`docs/artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) | ART-01–ART-04, ART-07–ART-12 |
| [`docs/artifacts/timing_schema.md`](../artifacts/timing_schema.md) | ART-05 |
| [`docs/artifacts/lineage_schema.md`](../artifacts/lineage_schema.md) | CAND-06, ART-06 |
| [`docs/implementation/repository_map.md`](repository_map.md) | IMPL-01 |
| [`docs/implementation/current_status.md`](current_status.md) | IMPL-02 |
| [`docs/implementation/architecture_gaps.md`](architecture_gaps.md) | IMPL-03 and gap/decision linkage for all non-implemented rows |
| [`docs/implementation/migration_plan.md`](migration_plan.md) | IMPL-04, IMPL-05 |
| [`docs/implementation/architecture_traceability_matrix.md`](architecture_traceability_matrix.md) | TRACE-01 and current evidence/status roll-up |
| [`docs/operations/running_eagle.md`](../operations/running_eagle.md) | OPS-01 |
| [`docs/operations/inspecting_runs.md`](../operations/inspecting_runs.md) | OPS-02 |
| [`docs/testing/test_contracts.md`](../testing/test_contracts.md) | TEST-01–TEST-06 |

## Specification Coverage

This index proves that every normative specification section is represented without copying its complete formula or schema.

| Specification Section | Matrix Contracts |
| --- | --- |
| §1 Scope | GOV-01–GOV-03, EVAL-14 |
| §2 Core Model | CAND-01–CAND-04 |
| §3 Candidate Data Contract | CAND-05, CAND-06 |
| §4 End-to-End Pipeline | EVO-01, EVO-12, VAL-01–EVAL-05 |
| §5 Parent Selection | EVO-02 |
| §6 Uniform Crossover | EVO-03, EVO-04 |
| §7 Mutation Overview | EVO-06–EVO-13 |
| §8 Strategy Mutation | EVO-06–EVO-08 |
| §9 Code Mutation | EVO-09–EVO-11 |
| §10 Mutation Selection | EVO-05 |
| §11 Java Generation | GEN-01–GEN-06 |
| §12 Java Runtime Contract | VAL-01–VAL-03, DEC-02 |
| §13 Evaluation Protocol | VAL-04, EVAL-01–EVAL-05 |
| §14 Game Performance | EVAL-06–EVAL-08 |
| §15 Code Quality | EVAL-09, EVAL-10 |
| §16 Failure Hierarchy | EVAL-10 |
| §17 Successful Code Quality | EVAL-09, EVAL-11–EVAL-13, DEC-01 |
| §18 Objective Examples | EVAL-06, EVAL-10 |
| §19 NSGA-II Behavior | EVO-01, EVAL-14 |
| §20 LLM Call Accounting | EVO-13 |
| §21 Artifact Requirements | ART-01, ART-10–ART-12 |
| §22 Mutation Artifact Contract | ART-03 |
| §23 Generation Artifact Contract | ART-02 |
| §24 Lineage Contract | CAND-06, ART-06 |
| §25 Timing Contract | ART-05 |
| §26 Match Artifact Contract | ART-04 |
| §27 Reproducibility Contract | ART-07–ART-09 |
| §28 State Transition Examples | CAND-04, EVO-04, EVO-08, EVO-11 |
| §29 Implementation Invariants | GOV-02–GOV-03 and affected CAND/EVO/GEN/VAL/EVAL/ART rows |
| §30 Implementation Priority | IMPL-04, dependency graph, milestones |

## Matrix Validation Checklist

- [x] Every specification section has at least one matrix row.
- [x] Every row has exactly one responsibility-focused canonical owner.
- [x] Every implementation and test path in the matrix exists in the active repository; all behavior-bearing active modules are covered, package-only `__init__.py` files carry no architecture contract, and expected runtime artifacts are explicitly labeled `Expected:`.
- [x] Every active English documentation file appears in Cross References.
- [x] Formula details remain in their canonical formula documents; this matrix records responsibility/status only.
- [x] Missing behavior is linked to G-01–G-18; resolved decisions A-01/A-02 remain traceable to their dependent open gaps.
- [x] Legacy fixed-function, split-generation, one-match, RandomAI, separate-alignment-objective, no-Reflection, and direct-Java-mutation behavior is not presented as an active contract.

## Update Policy

Update this matrix whenever an architecture contract, implementation path, test, artifact schema, gap status, migration dependency, or active documentation file changes. A row moves to `✅ Implemented` only after implementation, required tests, artifacts/configuration, and affected canonical documentation agree.

Normal implementation tasks do not use `docs/architeture_specification_zh.md` as a source. Any architecture, formula, Candidate transition, mutation/evaluation protocol, artifact schema, or documentation-structure change must update the Chinese overview. Adding, removing, or renaming an active documentation file must also update its Documentation Map.
