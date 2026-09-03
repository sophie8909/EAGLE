# Java generation, validation, and compilation

The Generator is a genotype-to-phenotype decoder.

## Exact input and output

Input in every mode:

- `strategy_prompt` as the game-playing policy;
- `generation_prompt` as reusable policy-to-Java translation instructions;
- the fixed checked-in Java scaffold, action API guide, and structural/security constraints.

Additional input in `inherited_genotype` mode:

- the complete Java component selected from the Java parent, or the configured
  no-op Java seed at generation zero.

Default mode receives no parent Java. Inherited mode receives the selected Java
component as revision context. Neither mode receives game logs or may independently
improve the policy. Output is one complete `ai.generated.CandidateAgent` Java
source file; patches, methods, JSON, prose, and partial source are rejected.

Default-mode generation zero does not call the Generator LLM. In inherited
`configured_seeds` mode, one configured policy is copied to `population_size`;
every copy receives the complete source from `initial_java_seed_path` and makes
its own bounded Generator call. The seed-variant configs use the callable no-op
file as both inherited input and scaffold.

Inherited `llm_generated_policies` mode is a second explicit decoder exception:
one configured policy is retained, the LLM fills the remaining policy genes, and
every candidate directly uses the same `initial_java_seed_path` source as its
generation-zero phenotype. The tracked `0903_llm_initial_population` config uses
the checked-in `java_seeds/worker_rush/CandidateAgent.java` for that source and the normal no-op
scaffold for generation 1 onward.

Default mode creates one generation-zero candidate per seed file and records
checked-in-source evidence with no request. In inherited mode, the
pre-generation Java input is persisted for every candidate. Only
`configured_seeds` generation zero owns normal Java
request/raw-response/attempt/timing evidence; `llm_generated_policies` owns
policy-generation evidence instead.

The raw response is persisted before extraction. The extracted response must
still be a structurally complete Java file. After its external envelope and
security checks pass, normalization deterministically combines the configured
canonical scaffold with only the extracted strategy region. Thus harmless model
rewrites or deletion of fixed code are retained as extracted evidence but never
enter validation, compilation, or the phenotype. Extracted/normalized generation
evidence remains under `generation/`; only a compilation success creates the
canonical `phenotype/CandidateAgent.java`.

For every Java-LLM-generated candidate, including inherited `configured_seeds`
generation zero,
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
Default-mode and `llm_generated_policies` generation zero record no Java LLM
attempts. The latter separately records its policy-only initialization attempts.

## Processing sequence

1. Persist the unchanged active genotype and lineage, including inherited Java
   input and Java-parent provenance when enabled.
2. Render the active genotype with canonical scaffold/API constraints for the
   initial decode.
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
   project the final source only under `generation/` as failure evidence; do not
   create a canonical phenotype.
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
