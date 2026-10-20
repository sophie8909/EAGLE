# Java generation, validation, and compilation

The processing details before "Deterministic DSL materialization" describe `java_materialization_mode: llm`. In that mode, the Generator is the normal genotype-to-phenotype decoder. A successful Code
Reflection is the one exception: its deferred revision returns a complete Java
phenotype and therefore enters validation/compilation directly. Both operations
run as soon as that child's own dependencies finish, overlapping preparation
and matches for other children.

`model` owns initialization and reflection/rewrite. Optional `generation_model`
permanently binds ordinary generation, Code revision and compile repair to its
own already running server. Without it, both roles share the primary server and
its two-request limit. There is no runtime model switching.

## Exact input and output

LLM materialization inputs:

- `strategy_prompt` as the authoritative `eagle-strategy-dsl-v1` JSON policy;
- `generation_prompt` as reusable DSL-to-Java translation instructions;
- the fixed checked-in Java scaffold, action API guide, and structural/security constraints.

Initial and rewritten generation meta prompts preserve DSL `actor`/`when`/`action`,
ordered legal-action fallthrough, idle semantics, observable metrics, target selection,
deterministic hashing and same-cycle reservations. Normative DSL semantics take priority
over reusable instructions and inherited Java. Compile-repair prompts preserve that same
contract; output remains complete Java with no runtime DSL interpreter.

Additional LLM input in `inherited_genotype` candidate mode:

- the complete Java component selected from the Java parent, or the configured
  no-op Java seed at generation zero.

The default candidate-state mode receives no parent Java. Inherited candidate mode receives the selected Java
component as revision context. Neither candidate-state mode receives game logs or may independently
improve the policy. Output is one complete `ai.generated.CandidateAgent` Java
source file; patches, methods, JSON, prose, and partial source are rejected.

Default-mode generation zero does not call the Generator LLM. In inherited
`configured_seeds` mode, one configured policy is copied to `population_size`;
every copy receives the complete source from `initial_java_seed_path` and makes
its own bounded Generator call. The seed-variant configs use the callable no-op
file as both inherited input and scaffold.

Inherited `llm_generated_policies` mode is not a decoder exception. One
configured policy is retained, the LLM fills the remaining policy genes, and
every candidate receives `initial_java_seed_path` as inherited revision context
in its own generation-zero Java request. The tracked configs use WorkerRush for
that context and the normal no-op file as the immutable generation scaffold.

Default mode creates one generation-zero candidate per seed file and records
checked-in-source evidence with no request. In inherited mode, the
pre-generation Java input is persisted for every candidate. Only
both inherited initialization modes own normal Java
request/raw-response/attempt/timing evidence; `llm_generated_policies` also owns
its preceding policy-generation evidence.

The raw response is persisted before extraction. The extracted response must
still be a structurally complete Java file. After its external envelope and
security checks pass, normalization deterministically combines the configured
canonical scaffold with only the extracted strategy region. Thus harmless model
rewrites or deletion of fixed code are retained as extracted evidence but never
enter validation, compilation, or the phenotype. Extracted/normalized generation
evidence remains under `generation/attempts/attempt_NNN/`; only a compilation success creates the
canonical `phenotype/CandidateAgent.java`.

For every Generator-decoded candidate, including both inherited generation-zero
initialization modes,
`generation_max_attempts` bounds compile-guided decoder
attempts. The repository default is one so old configs and resumes retain their
original semantics; the tracked `static_0824` production configs explicitly use
five. Attempt 1 uses the authoritative active-genotype generation request. If extraction
does not yield a complete source, the next attempt resamples that base request and
is marked `initial_decode_retry`. Once a complete source fails validation or
`javac`, the next attempt uses the separate `java_compile_repair` prompt with the
same authoritative genes, immutable scaffold/API guide, the immediately previous
complete source marked untrusted, and only that attempt's structured validation
and compiler evidence. Every actual post-truncation request is separately hashed.
Only default-mode fixed-Java generation zero records no Java LLM attempts.
`llm_generated_policies` records both policy initialization and subsequent Java
generation attempts.

A self-play fitness-refresh replica is another zero-LLM boundary: it validates
and compiles the existing canonical phenotype against itself as scaffold, then
reruns Integration and matches. Its generation operation is
`self_play_fitness_refresh`, with source provenance pointing to the source
parent phenotype and no decoder attempts.

Before actual crossover/mutation, every selected reproduction source independently sends the policy, selected parent Java, immutable gameplay
and action/API contracts, a concise interface/unit reference, canonical scaffold,
and source-matching validation/compiler diagnostics to a structured Reflector.
The v6 conclusion independently reports strategy fidelity and code correctness.
Only actual defects and policy/Java mismatches authorize repair; simplification
or cosmetic refactoring is forbidden. Ambiguous/correct needs no revision. At the final materialization boundary, when any dimension requires correction, a separate Java revision call
receives the parsed conclusion plus those same authoritative inputs; otherwise the
parent Java is retained without that call. Neither receives the reusable generation prompt, game performance,
opponent scores, W/D/L summaries, match results, traces, logs, aggregate fitness,
or other gameplay evidence. The revision's complete output is validated as attempt
1 under `code_reflection_output`; a validation or javac failure may enter the
same bounded compile-repair chain. Failed diagnosis cannot qualify as healthy
for variation. Failed/unextractable revision retains source evidence and never
falls through to ordinary Generator overwrite. Corrective children have one
source parent and unchanged policy/generation genes.

## Processing sequence

1. Persist the unchanged active genotype and lineage, including inherited Java
   input and Java-parent provenance when enabled.
2. Render the active genotype with canonical scaffold/API constraints for the
   normal initial decode, or accept the complete Code Reflection result as the
   direct initial source.
3. Before each request, persist its candidate-owned attempt envelope, then
   persist the raw response before extraction.
4. Extract each complete source, reject an invalid external/security envelope,
   then rebuild the normalized complete source from the configured scaffold and
   extracted strategy region. Validate that normalized source; after failure
   render the bounded compile-repair request without changing either gene,
   lineage, AOS state, or strategy intent. Invoke `javac` at most once for a
   normalized source that passes validation.
5. Stop at the first validation+compilation success and promote its isolated
   classes and source as the only canonical phenotype. If all attempts fail,
   point `generation/result.json` at the representative failed attempt; for
   source_without_generation failures persist `generation/failed_candidate.java`;
   do not create a canonical phenotype.
6. Run Integration once for the canonical success, then reuse the identical
   source/classes for every evaluation match. Its bounded probe loads the real
   populated `basesWorkers8x8.xml` map twice, exercises both player sides with
   independent one-argument agent instances and independent states, then checks
   `PlayerAction` integrity before `GameState.issueSafe` and one cycle.
   Integration/runtime failures do not trigger decoder attempts.

Validation enforces package `ai.generated`, public class `CandidateAgent`,
`AbstractionLayerAI`, required constructors/lifecycle methods, available APIs,
the token-equivalent fixed scaffold outside the editable strategy markers, and
prohibited network/process/file/runtime-modification capabilities. Inside the
editable region, deterministic strategy-contract checks reject Java shapes that
the immutable prompt explicitly forbids: a helper using `context` without an
`AgentContext context` parameter, a helper reading an undeclared `gameTime`,
one-dimensional arrays initialized with nested coordinate pairs, and unavailable
`getUnitAt` lookups. Strategy code must use the fixed bounds-safe
`isFreeCell(context, x, y)` helper for occupancy checks; direct
`GameState.free(...)` or `PhysicalGameState.getTerrain(...)` reads are rejected.
The fixed `commandMove` and `commandBuild` helpers also reject coordinates
outside the active `GameState` before issuing an abstraction action. These
checks classify invalid generation before `javac` and provide structured
evidence to the next bounded decoder repair attempt.

Compile repair is not Code Reflection: it cannot rewrite a gene or improve the
policy. A deterministic delta guard requires fixed-scaffold-only repairs to keep
the strategy region token-identical and rejects other repairs below `0.45`
strategy-token similarity. This bounds broad drift but does not prove semantic
equivalence; the immutable prompt and subsequent evaluation remain responsible
for intent fidelity.

Hard tests prove the default request uses the checked-in scaffold rather than
`parent.generated_java`, the inherited request includes its explicit Java
component, and Generator/Evaluation preserve every active genotype input.


## Deterministic DSL materialization

`java_materialization_mode: deterministic_dsl` compiles normalized
`eagle-strategy-dsl-v1` through `eagle/generation/dsl_java_compiler.py` and the
canonical scaffold. Its active inputs are normalized policy, compiler version
`eagle-dsl-java-v1`, and scaffold; `generation_prompt` and inherited Java are
inactive. Protocol is `eagle-dsl-compiler-v1`. The typed-IR emitter is fixed and
must produce byte-identical complete Java for the same normalized policy,
compiler version, and scaffold. It calls no Java Generation, Code Reflection,
Prompt Reflection, or compile-repair LLM. The resulting full source continues
through normal Java validation, one javac attempt, Integration, semantic probe,
and evaluation. Compiler/validation/javac failure stays at its actual failure
stage with source, hashes, diagnostics, and canonical fitness sentinel; no LLM
fallback is allowed. Unknown compiler versions fail resume explicitly.

The configured WorkerRush seed is a closed reference-policy exception rather
than an approximation in ordinary DSL rules. Its generated CandidateAgent owns
a vendored `ai.abstraction.WorkerRush` delegate and replays the delegate's full
action vector. Compiler evidence pins `WorkerRush.java` by SHA-256. Generated
initial policies and Strategy rewrites reject `reference_agent`, so this escape
hatch is limited to the checked-in seed.

## Framework-slot materialization

`java_materialization_mode: framework_slots` consumes one run-frozen validated
`eagle-framework-bundle-v1` and the candidate's complete `control_genome`.
Materialization validates every exact key and typed value, replaces every
`{{EAGLE_SLOT:<slot_id>}}` marker once, verifies no marker remains, and records
the bundle, template, canonical-genome, and rendered-source SHA-256 values.
Numeric values are rendered only from declared finite lattices. An
`expression_choice` genome value is a declared `choice_id` whose immutable
bundle-owned `java_expression` is substituted; arbitrary formula source is not
a gene.

The rendered complete source follows the same external/security validation,
isolated `javac`, Integration, semantic probe, and match evaluation as other
modes. It does not use the LLM Generator, Code Reflection/source gate, Prompt or
Strategy Reflection, or compile-guided repair. Render, validation, or javac
failure retains exact stage evidence and never falls back to Groq or another
LLM. The one-time Groq creation step and exact bundle schema are owned by
[framework slots](framework_slots.md), not by candidate decoding.
