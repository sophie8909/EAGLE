# Migration plan

## Framework reflection (2026-10-24)

The additive `framework.evolution_mode: reflection` policy leaves existing
`local`/`llm_coach` runs compatible. Initial run config/bundle identity remains
immutable; accepted whole-framework revisions gain versioned bundles selected
by completed generation snapshots. A separate batch Coach reflection fills every
prior individual's complete new-framework genome following a separate
performance-driven strategy-description revision, before creating fresh replicas,
preserving prior candidate and evaluation evidence. Coach failure shares the
outer repair budget; exhaustion retains old framework/descriptions/population together.
Existing experiments opt in
through a new config/run; changing evolution mode during resume is rejected.

## LLM-mode DSL and pre-crossover source contract (2026-10-11)

The [integration plan](dsl_pre_crossover_reflection_plan.md) migrates policy seeds
and producers to canonical JSON DSL, gates every source before variation, preserves
one-worst-match Strategy Reflection, limits normal mutation/AOS to Strategy/Prompt,
and rejects incompatible resume. Corrective Java preserves source genes and
bypasses ordinary Generator. Historical artifacts are not converted.

## Dependency-driven scheduling (2026-10-20)

Role clients replace phase switching. Independent generation servers must be
started externally and configured at distinct hosts/ports for different models.
Omit `generation_model` for shared-model parallel calls. Stream source-gated
plans and per-child mutation/materialization into bounded preparation while ready
candidates run matches. Retain seeded choices, canonical results, immutable
opponents, AOS/selection barriers and atomic checkpoints.

## Completed prior migrations

- 2026-10-22: one shared fresh/resume continuation loop and result owner;
  neutral experiment-index recognition/validation removes the GUI-data dependency
  on experiment orchestration. Existing initialization, resume fences and formats
  remain unchanged; see the [refactor plan](maintainability_refactor_plan.md).

- complete-file candidate model and first-class lineage;
- Strategy/Prompt Reflection → Rewrite → Generation mutations and diagnosis-guided direct-Java Code Reflection;
- ten-opponent, 180-match evaluation and seeded lexicase selection;
- three reflection-operator modes with one AOS updater;
- unified experiment/model lifecycle;
- one-file-per-prompt resources;
- removal of fake match seeds;
- compact `eagle-run-v2` artifacts;
- one canonical match runner and match trace;
- one canonical Code Quality module;
- file-only prompt configuration and one `execution_mode`;
- shared fresh/resume search bootstrap;
- removal of obsolete run/runtime CLI wrappers and `eagle-run-v1` analysis.
- removal of inherited `previous_code` and phenotype-parent provenance;
- two-gene crossover, fixed-scaffold generation, and separated Strategy/Prompt/Code evidence;
- genotype/phenotype and responsibility-specific mutation artifact layout.
- resumable config-folder batches driven by atomic `eagle-experiment-index-v1` indexes with ordered replicate slots and legacy single-path readback.
- joint parent-plus-offspring `(mu + lambda)` lexicase survivor selection;
- heterogeneous generation-zero policy genes sharing one callable no-op Java seed.
- explicit `candidate_java_mode` with backward-compatible two-prompt default and
  opt-in inherited Java third component;
- inherited-mode single-policy generation-zero replication, independent Java
  generation, three-component crossover provenance, and resumable Java genotype artifacts.
- mutation-evidence-parent provenance for opponent and head-to-head AOS credit.
- mixed generation-zero initialization with one configured policy, LLM-generated
  remaining policies, fixed shared Worker Rush Java, and candidate-owned policy
  generation evidence.

## Remaining optional hardening

Fine-grained selection/crossover timing may be promoted to dedicated timing
events if future analysis requires it. It has no dependency on current search,
fitness, artifacts, or runtime behavior.

## Migration policy

New migrations update source, tests, configuration, artifacts/readers, the
Chinese overview, current status, repository map, and canonical spec together.
Unsupported historical formats are removed rather than retained as silent
compatibility layers.

## Maintainability migration (2026-10-02)

The [refactor plan](maintainability_refactor_plan.md) precedes implementation. Python owners are consolidated under `eagle`; each EA operator remains independent, and generation/search/evaluation phase owners are split without a compatibility layer. Callers, test patch targets, packaging and resource roots migrate together. Verification is recorded in the plan.


## Deterministic DSL materialization migration

This migration adds `deterministic_dsl` while preserving historical `llm`
materialization as the missing-field default. It versions policy-only active
genotype state, compiler/source evidence and timing, and mode/compiler resume
fences. It is complete only after the compiler golden suite, artifact/timing and
resume contracts, bounded real Java/MicroRTS integration, and deterministic smoke
run all pass. These checks pass for the implementation; results are recorded in
`../testing/test_contracts.md`. No full evolutionary experiment is part of this migration.
