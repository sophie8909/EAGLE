# Migration plan

This plan moves active code toward the normative architecture without redefining it. Read [`architecture_gaps.md`](architecture_gaps.md) before selecting work. Do not implement later stages on unstable candidate/artifact contracts.

## Phase 0: resolve blocking architecture decisions — complete

Resolved on 2026-07-14:

1. `A-01`: successful `code_quality` uses the explicit `+500` base and range `[0, 610]`.
2. `A-02`: generated Java has the exact external identity/constructor/method contract in specification section 12, followed by seven ordered pre-match integration checks.
3. The authoritative specification, affected canonical docs, Matrix, project-local guidance, and Chinese overview record the decisions.

Exit satisfied: downstream implementation does not need to guess either decision. No implementation gap was closed by this documentation decision.

## Phase 1: Candidate, lineage, and configuration foundation — complete

Completed on 2026-07-14:

1. Added first-class candidate genotype, generated phenotype, failure, artifact, timing, operator, mutation, and component-provenance fields.
2. Preserved pre-generation `previous_code` and post-generation `generated_java` separately in memory and canonical candidate files.
3. Wrote versioned `lineage.json` for every candidate shape plus immediate crossover provenance.
4. Wrote actual resolved runtime configuration with explicit null/unsupported values where the runtime has no prompt version or match seeds.
5. Added focused serialization/readback, seeded provenance, all-eight-combination, equal-text, and runtime-value tests.
6. The user-requested Phase 1 scope explicitly included generated-Java inheritance and Uniform Crossover provenance, so those foundation items were pulled forward without implementing mutation, scoring, validation, integration, or match-protocol work.

Closes: G-01, G-02, G-14, G-15; establishes the Phase 1 portion of G-12.

Exit satisfied: evaluated candidates retain both Java states; inheritance uses `parent.generated_java`; lineage and resolved configuration are reconstructable from current artifacts; focused and full-suite module validation passes.

## Phase 2: inheritance and Uniform Crossover — folded into the explicit Phase 1 scope

The four originally planned items are complete as Phase 1 foundation work: generated-Java inheritance, three component source IDs, provenance-aware feedback-parent routing, and all parent-choice/equal-text tests. No later mutation or evaluation behavior was implemented.

Phase 2A Reflection Framework, Phase 2B Prompt Rewrite, and Phase 2C Full Mutation Pipeline are complete. Phase 3 Java boundaries and the complete Phase 4 Evaluation Layer are also complete.

## Phase 2: complete two-stage mutation (complete)

1. Phase 2A: typed Strategy and Code Reflection evidence, independent Reflection transport/stage, reflection-only output validation, bounded retries, raw artifacts, and UTC attempt timing.
2. Phase 2B: Strategy Prompt Rewrite and Generation Prompt Rewrite with prompt-only validation, original prompt retention, bounded retries, raw artifacts, and timing.
3. Phase 2C: final Java Generation consumes the rewritten genotype plus inherited previous_code; generation request/raw/extracted/normalized artifacts and independent generation timing are persisted for success and failure.
4. Strategy state transitions are A1+B2+C1 -> A2+B2+C1 -> A2+B3+C1; Code transitions are A1+B2+C1 -> A1+B2+C2 -> A1+B3+C2.
5. Phase 2 tests cover both mutation types, call order, component isolation, lineage, candidate state, canonical artifacts, timing, and terminal generation failure retention.

Closes the Phase 2 mutation pipeline portion of G-03, EVO-06-EVO-13, ART-02/ART-03, and TEST-02. G-04, G-12, and G-13 retain only the later evaluation/stage portions documented in the gap table.

## Phase 3: Java boundary and stage classification (complete)

1. Separate seed-template validation from generated-candidate validation.
2. Implement the resolved external Java runtime/security contract.
3. Add `javac -Xlint` and structured/deduplicated diagnostics.
4. Add explicit MicroRTS integration checks and typed terminal stages.
5. Test every failure boundary before running matches.

Closes: G-09, G-10, and the integration portion of G-11. G-08 scoring hierarchy remains for the later objectives milestone.

Exit satisfied: source validation accepts arbitrary valid internals while enforcing the external identity/security contract; compilation emits structured deduplicated diagnostics; integration persists seven ordered checks and stops before matches on failure. Validation, compilation, and integration result/timing artifacts remain inspectable on every terminal path.


## Phase 4: complete Evaluation Layer (complete 2026-07-16)

1. Enforce `matches_per_candidate = 10` and the fixed Evolution Evaluation roster in architecture configs.
2. Resolve map/cycles/seeds into runtime configuration.
3. Add process timeouts and strict result validation.
4. Prove one source hash/compile serves all 10 matches with no generation calls.
5. Retain partial match evidence and runtime-progress classification.

Closes: G-04 through G-08 and G-11. Exit satisfied: exactly 10 seeded roster matches (3 external, 5 basic, 2 historical self) reuse one source/class set; runtime failures are typed; canonical Game Performance and Code Quality (including Function Capability and Strategy Alignment) feed exactly two objectives; evaluation artifacts and timing pass focused and full-suite tests.

## Phase 5: objectives (completed inside the Phase 4 Evaluation Layer milestone)

1. Implement and version the bounded `game_performance` formula.
2. Implement warning, capability, and independent Strategy Alignment components.
3. Implement the resolved successful `code_quality` formula.
4. Implement all failure-stage formulas and cross-stage ordering tests.
5. Keep exactly two NSGA-II objectives.

Completed as part of the user-scoped Phase 4 milestone. G-16 retains only version-gated legacy reader/help cleanup; canonical Strategy Alignment is active solely inside Code Quality.

## Phase 6: remaining artifact and timing completion

1. Preserve the completed Phase 4 match/alignment/evaluation/objective hierarchy and finish the broader run/generation population hierarchy.
2. Preserve Phase 4 schema/formula versions, hashes, alignment attempts, and evaluation timing; add candidate-total plus selection/crossover timing.
3. Remove duplicate current artifacts or document temporary compatibility aliases.
4. Add remaining schema migration/readback tooling and full-run golden-tree tests; Phase 4 evaluation artifact/timing tests are complete.

Closes: G-12, G-13, G-15.

## Phase 7: operations, tests, and legacy removal

1. Update all checked-in configs and CLI help.
2. Update analysis/plot/GUI tools for the current schema and fixed `CandidateAgent` boundary.
3. Replace tests that enforce non-normative markers/static scoring with contract tests.
4. Run WSL unit tests plus a bounded real integration smoke; do not treat old runs as proof.
5. Remove obsolete alignment configuration, split/function-body readers after their migration window, surrogate/runtime-LLM residue, and unused parsers/helpers.

Closes: G-17, G-18, remaining G-16.

## Change completion checklist

- Affected normative/canonical docs updated.
- Current status and gap table updated.
- Unit/contract tests pass in WSL.
- Artifact schema/readback validation passes where affected.
- No historical compatibility path overrides active contracts.
- Chinese overview updated only when architecture/formulas/state/protocol/schema/docs structure changed.
## Initial dual-host LLM deployment assignment

The initial deployment uses two logical profiles and one centralized endpoint handoff file. Machine A runs only the coder model and exposes it over the private LAN; Machine B runs the general model locally and runs EAGLE.

- Reflection -> general / qwen3.5-9b on Machine B.
- Rewrite -> general / qwen3.5-9b on Machine B.
- Generation -> coder / qwen2.5-coder-7b on Machine A.
- General defaults to http://127.0.0.1:8080/v1; coder defaults to port 8081 and publishes Machine A's detected private address.
- Both profiles default to context size 32768, with launcher overrides for hardware and quantization differences.
- scripts/llama_launcher.py requests the actual .gguf path, uses the explicitly configured alias, does not download models or rebuild llama.cpp, and atomically updates only the selected section of config/llm_endpoints.toml.
- The repository config contains no model paths, server paths, API keys, or placeholder Machine A address. The launcher stores machine-local settings under ~/.config/eagle-llm/ with restrictive permissions.
- Stage code depends on general and coder, not on these initial model names. Future replacement is a launcher/configuration change.

The operational workflow and artifact metadata contract are documented in [../operations/dual_host_llm.md](../operations/dual_host_llm.md).
## General-only topology variant

The same profile abstraction also supports a single-machine Machine B run. Set llm_topology: "general_only" in configs/eagle_general_only.yaml; only [general] is required, and Reflection, Rewrite, Strategy Alignment, and final Generation all resolve to the general endpoint. This mode does not require Machine A or a coder endpoint.
