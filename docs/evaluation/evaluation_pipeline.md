# Evaluation pipeline

`eagle/evaluation/pipeline.py` owns the candidate evaluation boundary. Bounded decoder attempts live in `decoding.py`; opponent setup lives in `opponents.py`; ordered match dispatch lives in `matches.py`; shared typed results live in `records.py`. It performs Java
generation, validation, compilation, integration, the complete MicroRTS
matrix, diagnostics, objective construction, and candidate artifact writing.

## Active stages

| Stage | Success output | Failure evidence |
| --- | --- | --- |
| Java generation | complete `CandidateAgent.java` | generation response and validation failure |
| Source validation | validated source | validation diagnostics |
| Compilation | isolated class directory | compiler stdout/stderr and structured errors |
| Integration | loadable MicroRTS agent | seven integration checks |
| Match execution | 180 matches across ten active cases | retained match results and runtime failure |
| Semantic probing | nine canonical action hashes in self-play | diagnostic unavailable record; fitness unchanged |
| Objective construction | ten fixed-roster cases or one self-play Game Performance score | matching `-1000.0` fitness on failure |

`decode_validate_compile_candidate` is the single production boundary for the
first three rows and can be called by a decoder smoke without launching
Integration or the 180-match matrix. `evaluate_candidate` consumes that helper;
it does not maintain a second retry implementation. Attempt 1 uses the active
genotype request (two prompts, plus inherited Java when configured); extraction
failures may repeat that request, while a complete
source's validation/javac failure produces the next compile-repair request from
that source and only its structured diagnostics. Every attempt has an isolated
source/classes workspace and compiles each validated source no more than once.
Only the first compilation success is promoted. Exhaustion classifies the final
attempt's generation, validation, or compilation failure; an Integration failure
never re-enters the decoder.

Inherited `configured_seeds` generation zero uses this same bounded decoder for
every replicated population slot, so a population of ten records ten separate
requests/responses and can produce ten different Java phenotypes. In inherited
`llm_generated_policies` mode, policy-only initialization calls occur before
this boundary, then every policy is independently decoded to Java. WorkerRush
Java is inherited request context and is never substituted for that policy's
generation-zero phenotype.
Later generations pass the independently selected Java component into the base
and compile-repair requests without mutating that stored input during evaluation.

The seven-check Integration probe is deliberately smaller than a match but is
not an empty-state smoke: it loads separate populated 8×8 bases/workers maps,
invokes independent one-argument agent instances for the two player sides, and
rejects null or integrity-invalid `PlayerAction` values before safe issuance and
one cycle per state. This exposes map-coordinate and cross-side state faults
before the 180-match matrix without treating an Integration failure as a decoder
retry signal.

## Match protocol

`evaluation.mode: fixed_roster` is the default protocol below. With
`evaluation.mode: self_play`, the evaluator materializes the immutable active
context from the run-local opponent library as ten equally weighted
`self_play_000`…`self_play_009` slots. Only candidates with a successful compile,
no failure stage/reason, and a complete match batch may enter the library. If
generation zero has no such candidate, the run fails before creating a context.
The library is seeded at generation zero
and merged/reselected only at `self_play_refresh_interval` (five generations in
the minimal protocol); a short library selection is cycled deterministically and
self-matches remain valid. Every match records the context ID plus source
candidate/generation. Refresh first re-evaluates phenotype-preserving parent
replicas, so selection never mixes old-context parents with new-context
offspring. Resume reloads the last committed active-context sidecar; the
library is consulted only for a subsequent refresh.

The fixed roster is defined by `eagle/opponent_cases.py` and resolved by
`eagle/opponents.py`. Each opponent receives three configured maps, three
rounds, and both candidate player positions. The matrix is owned by
`eagle/evaluation/match_matrix.py`; execution is owned by
`eagle/evaluation/runtime_evaluation.py`. A map entry may carry a positive `tick_limit`;
otherwise it inherits the legacy top-level `tick_limit`. The matrix attaches
the resolved limit to every match specification, so search, AOS head-to-head,
and final-test matches use the same cap for a given map.

Normal matrix execution uses ten bounded match workers by default, based on the
bundled MicroRTS benchmark on the development host. `evaluation.match_workers`
can override that value or restore serial execution with `1`; each match still
owns an isolated artifact directory and results are returned in canonical
`match_index` order.
`scripts/benchmark_match_workers.py` can compare worker counts over the mock
artifact path or the real bundled MicroRTS matrix; benchmark results are
machine-dependent and are not written back into experiment configuration.

The evaluator groups match results by opponent in
`eagle/evaluation/game_metrics.py`. It retains per-opponent, per-map, per-side, and
per-match summaries, then computes the weighted aggregate only for reporting.
The aggregate denominator is the fixed weight sum `12.5`.

AllInBot remains the pinned upstream implementation: preflight verifies its
original class and JAR hash.  Real search and final-test matches instantiate a
separately compiled reflection-only `ai.eagle.SafeAllInBot` adapter, which does
not enter candidate source/class hashing or strategy complexity.  If the
upstream delegate throws an `Exception`, returns null, or returns an invalid
action, it emits one `EAGLE_SAFE_ALLINBOT_FALLBACK` stderr marker and permanently
issues legal passive actions.  A recovered marker leaves the match `ok=true`
but is recorded as `fault_scope="opponent"`, `opponent_fault_contained=true`,
`opponent_fault_recovered=true`, and `scoring_neutralized=true`; the candidate
contribution is a zero-score draw. Raw result and telemetry evidence are kept,
so an upstream defect can neither crash the JVM nor become a candidate win.

## Objective and diagnostics

`eagle/evaluation/objectives.py` returns ten scores in fixed-roster mode. Self-play
stores only aggregate `game_performance` as fitness. `code_quality`, compiler diagnostics, and runtime failure details remain diagnostics; normal evaluation does not call Function Capability or Strategy Alignment or write their files or timing. Standalone helpers remain available to explicit tooling.

## Artifacts

Per-candidate evaluation artifacts include:

- `evaluation/game_performance.json`: aggregate Game Performance, opponent
  score mapping, opponent summaries, map/side summaries, and match summaries;
- `evaluation/objectives.json`: active-mode objective mapping;
- `evaluation/semantic_signature.json`: candidate provenance, compatible
  dataset identity, cache reference, global hash, and timing/status;
- `evaluation/code_quality.json`: code-quality diagnostics;
- `evaluation/matches.json`: compact individual match records.

Each run-level generation JSON stores objective statistics for every
opponent case and the per-opponent reporting summaries used by analysis.
Final-test JSON/CSV/Markdown also count contained upstream-opponent faults
separately (`OF` in the Markdown table); they are not candidate runtime
failures.

## `aos_head2head`-only parent-vs-offspring evaluation

After normal evaluation succeeds for a mutated offspring,
`eagle/evaluation/parent_offspring.py` reuses the offspring and comparison parent's
compiled class directories. It uses `eagle/evaluation/match_matrix.py` with the same
three configured maps, three round indices, and both player positions, producing
18 direct matches. `ComparisonParentAgent` isolates the parent's already
compiled same-named `ai.generated.CandidateAgent`; it does not regenerate or
recompile either generated source.

Every MicroRTS match derives a stable seed from the EA root `random_seed`
and immutable match identity, passes it as `-Deagle.match.seed`, and persists
it in results and trace metadata. Repetitions use `round_index`. Worker counts
may differ: seed assignment and aggregation follow canonical matrix order.
Candidate compilation includes the seeded runtime source overlay ahead of stale
vendored bytecode. Integration and semantic probes receive derived root seeds;
semantic dataset/signature caches include the root and runtime source identity.
Final tests recompile preserved source into a separate final-test classes directory.
Vendored stochastic sources consume the seed, while external opponent binaries
and wall-clock search/timeout budgets can still be nondeterministic.

The direct W/D/L summary is consumed only by AOS. It is not added to the ten
opponent objectives, Game Performance, lexicase, or the opponent archive. An
offspring that fails generation, validation, compilation, integration, or its
normal runtime matrix does not launch this evaluator.

`aos_opponent` launches no direct matches: its credit provider reuses the ten
completed opponent summaries from normal evaluation. `static` calculates no
reward at all. Both adaptive providers feed the updater in `eagle/operators/adaptive.py` and
do not alter the normal evaluation vector.

## Final-test candidate recovery

The production final test accepts only candidates whose status is not failed
and whose canonical Java phenotype and compiled `CandidateAgent.class` are both
present. If the terminal generation has no runnable candidate, it searches
completed generations newest-first and tests the newest available runnable
representative. An explicitly requested candidate ID never falls back to a
different candidate.
