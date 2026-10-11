# DSL policy and pre-crossover Code Reflection migration

Task date: 2026-10-11. Owner: primary controller.

## Requested contracts

1. Replace natural-language strategy genes with a validated domain-specific language.
2. Diagnose the reproduction source before crossover/mutation. A source needing correction produces a Code Reflection offspring and skips C/M. A healthy source continues normal C/M.
3. Code Reflection corrects defects and policy/Java mismatches only; simplification alone never triggers revision.
4. Preserve the one-worst-match Strategy Reflection selection, immutable prompt/Java provenance, root-seeded streams, failure evidence, and unrelated presentation work.

## Decisions

- DSL representation: confirmed versioned bounded JSON rule DSL with explicit conditions, actors, actions, and targets.
- Gate scheduling: confirmed check each selected reproduction source.
- Diagnosis contract: strategy fidelity and code correctness. Correctness covers compilation/API/game legality and actual reachable program defects; no aesthetic or simplicity dimension.
- Parent policy and Java must come from the same selected reproduction individual at the gate.

## Milestones

- [x] Narrow Code Reflection diagnosis and revision to defect correction and policy fidelity; focused tests.
- [x] Define versioned DSL grammar, validation, seed policies, and authoritative prompt boundaries; initialization/Strategy/Generator fixtures.
- [x] Move Code Reflection to the pre-C/M gate and preserve diagnosis, correction, normal path, failure, AOS, and seeded resume evidence.
- [x] Integrate persistence/config/docs/readers, full unit/contract validation, and bounded real Java integration.
- [x] Final diff review, scoped commit(s), and report.

## Verification and handoff

Budget controller is disabled (UNLIMITED), as confirmed earlier in this task session; do not reread telemetry.
Default shell sandbox initialization fails. Task-authorized exec_command with require_escalated works.
WSL/project venv is preferred for full validation; C:\Python312\python.exe works for local targeted tests.
Never stage the pre-existing Meeting/presentation modifications.

Validation uses bounded mock searches and unit/contract tests, plus real Java compilation and MicroRTS integration probes. No live LLM evolutionary experiment was run.

Final verification runs on a Linux source snapshot whose 295 implementation, prompt, seed, config, test, and script files were SHA-256 matched to the workspace. The snapshot uses the project virtual environment and the existing MicroRTS toolchain. This avoids Windows filesystem overhead without changing the tested code.

Changed components: strategy DSL grammar and seeds; Candidate/Generator policy boundaries; source Code gate and Strategy/Prompt selection; Code diagnosis/revision contracts; artifact lineage, timing and semantic-analysis readers; config/resume protocol fencing; corresponding prompts, fixtures, tests and architecture documentation.

Historical natural-language runs remain inspectable but cannot resume with the new DSL/pre-crossover protocol. DSL validation proves syntax and legal action relationships; future LLM-generated Java still requires fidelity diagnosis and runtime validation.


## Final validation

- Full unit/contract suite: 562 tests in 244.548 seconds; 561 passed, one skipped; no failures or errors.
- Real JVM checks passed, including MicroRTS integration, seeded random streams and match reproducibility across workers.
- DSL/gate/resume focused verification and semantic audit exclusion passed.
- All 295 implementation/prompt/seed/config/test/script files were SHA-256 matched before the full run; those workspace files remained unchanged during validation.
- Markdown UTF-8, fenced blocks and relative links passed; staged diff whitespace check passed.
- No live LLM experiment was run. Existing unrelated Meeting/presentation changes were excluded.

Command in the verified Linux snapshot:

```sh
/mnt/d/Project/EAGLE/.venv/bin/python -m unittest discover -s tests -v
```

## Files changed

Paths are relative to `D:/Project/EAGLE`:

```text
README.md
docs/README.md
docs/architecture/candidate_model.md
docs/architecture/crossover.md
docs/architecture/evolutionary_flow.md
docs/architecture/java_generation.md
docs/architecture/mutation.md
docs/architecture/overview.md
docs/architeture_specification_zh.md
docs/artifacts/artifact_schema.md
docs/artifacts/lineage_schema.md
docs/artifacts/timing_schema.md
docs/eagle_architecture_spec.md
docs/implementation/architecture_gaps.md
docs/implementation/architecture_traceability_matrix.md
docs/implementation/current_status.md
docs/implementation/dsl_pre_crossover_reflection_plan.md
docs/implementation/migration_plan.md
docs/implementation/repository_map.md
docs/operations/running_eagle.md
docs/strategy-reflection.md
docs/testing/test_contracts.md
eagle/analysis/semantics.py
eagle/artifacts.py
eagle/candidate.py
eagle/config.py
eagle/evaluation/decoding.py
eagle/evaluation/strategy_alignment.py
eagle/evolution/offspring.py
eagle/evolution/resume.py
eagle/evolution/runtime.py
eagle/operators/adaptive.py
eagle/operators/code.py
eagle/operators/initialization.py
eagle/operators/prompt.py
eagle/operators/reflection.py
eagle/operators/reflection_prompts.py
eagle/operators/strategy.py
eagle/operators/strategy_compliance.py
eagle/run_artifacts.py
eagle/strategy_dsl.py
eagle/timing.py
prompts/coach_alternative.txt
prompts/coach_counter.txt
prompts/coach_refine.txt
prompts/coach_structural.txt
prompts/code_reflection.txt
prompts/code_revision.txt
prompts/initial_policy_generation.txt
prompts/initial_strategy.txt
prompts/java_compile_repair.txt
prompts/java_compile_repair_inherited.txt
prompts/java_generation.txt
prompts/java_generation_inherited.txt
prompts/manifest.toml
prompts/prompt_reflection.txt
prompts/strategy_alignment.txt
prompts/strategy_contract_rewrite.txt
prompts/strategy_dsl_reference.txt
prompts/strategy_rewrite.txt
seeds/blank_policy.txt
seeds/random_policy.txt
seeds/worker_rush_policy.txt
tests/test_aos.py
tests/test_code_reflection.py
tests/test_eagle_pipeline.py
tests/test_evolution_reproducibility.py
tests/test_experiment_launcher.py
tests/test_function_module_contract.py
tests/test_generation_attempts.py
tests/test_genotype_evidence_separation.py
tests/test_inherited_java_genotype.py
tests/test_initial_population_generation.py
tests/test_phase1_candidate_foundation.py
tests/test_phase2b_prompt_rewrite.py
tests/test_phase2c_mutation_pipeline.py
tests/test_phase4_code_quality.py
tests/test_phase4_evaluation_pipeline.py
tests/test_phase4_runtime_evaluation.py
tests/test_pre_crossover_code_reflection.py
tests/test_prompt_resources.py
tests/test_reflection_context.py
tests/test_resume_workflow.py
tests/test_semantic_signatures.py
tests/test_strategy_compliance.py
tests/test_strategy_dsl.py
tests/test_strategy_reflection_pipeline.py
```

The temporary snapshot/log were no longer available in WSL after the test process completed; the returned unittest summary confirms the result.
