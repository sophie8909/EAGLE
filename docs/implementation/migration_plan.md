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

The next active milestone is Phase 3.

## Phase 3: real two-stage mutation

1. Define typed Strategy and Code feedback payloads.
2. Add independent Reflection and Rewrite LLM transports/stages.
3. Validate rewrite-only outputs.
4. Persist requests, raw responses, retries, failures, and timings.
5. Keep the final Java generation call separate and mandatory.

Closes: G-03, G-04; advances G-12/G-13.

## Phase 4: Java boundary and stage classification

1. Separate seed-template validation from generated-candidate validation.
2. Implement the resolved external Java runtime/security contract.
3. Add `javac -Xlint` and structured/deduplicated diagnostics.
4. Add explicit MicroRTS integration checks and typed terminal stages.
5. Test every failure boundary before running matches.

Closes: G-08, G-09, G-10, integration part of G-11.

## Phase 5: 10-match LightRush evaluation

1. Enforce `matches_per_candidate = 10` and LightRush in architecture configs.
2. Resolve map/cycles/seeds into runtime configuration.
3. Add process timeouts and strict result validation.
4. Prove one source hash/compile serves all 10 matches with no generation calls.
5. Retain partial match evidence and runtime-progress classification.

Closes: G-05 and G-11.

## Phase 6: objectives

1. Implement and version the bounded `game_performance` formula.
2. Implement warning, capability, and independent Strategy Alignment components.
3. Implement the resolved successful `code_quality` formula.
4. Implement all failure-stage formulas and cross-stage ordering tests.
5. Keep exactly two NSGA-II objectives.

Closes: G-06, G-07, remaining G-08, active portion of G-16.

## Phase 7: artifact and timing completion

1. Write the canonical run/generation/candidate/stage/match hierarchy.
2. Add atomic writes, schema versions, hashes, attempt records, and unified timing.
3. Remove duplicate current artifacts or document temporary compatibility aliases.
4. Add schema migration/readback tooling and golden-tree tests.

Closes: G-12, G-13, G-15.

## Phase 8: operations, tests, and legacy removal

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
