# Evaluation pipeline

`eagle/evaluation/pipeline.py` owns the candidate evaluation boundary. LLM decoding lives in `decoding.py`; deterministic Java materialization uses the versioned DSL compiler. Opponent setup lives in `opponents.py`; ordered match dispatch lives in `matches.py`; shared typed results live in `records.py`. Both modes share validation, compilation, integration, semantic probes, matches, diagnostics, objective construction, and candidate artifact writing.


## Active stages

| Stage | Success output | Failure evidence |
| --- | --- | --- |
| Framework genome selection | complete validated `control_genome` in `llm_coach` initialization or Strategy mutation | candidate-owned raw-before-parse attempts; `initialization` or `reflection` failure with the canonical objective sentinels |
| Java materialization | complete `CandidateAgent.java` from LLM decoding, deterministic DSL compilation, or frozen framework rendering | mode-specific generation/compiler evidence |
| Source validation | validated source | validation diagnostics |
| Compilation | isolated class directory | compiler stdout/stderr and structured errors |
| Integration | loadable MicroRTS agent | seven integration checks |
| Semantic probing | nine canonical action hashes in self-play | diagnostic unavailable record; fitness unchanged |
| Match execution | 180 matches across ten active cases | retained match results and runtime failure |
| Objective construction | ten fixed-roster cases or one self-play Game Performance score | matching `-1000.0` fitness on failure |

`decode_validate_compile_candidate` is the shared production boundary for materialization, validation, and compilation; in LLM mode, a decoder smoke can call it without launching Integration or the match matrix. It owns bounded generation and compile-repair attempts and promotes only the first successful compilation. A validation or javac failure may inform another decoder request; Integration failures never re-enter LLM decoding.

In deterministic mode, the typed-IR compiler emits complete Java and compiler evidence without an LLM or repair request. Validation or javac failure is terminal and retains stage diagnostics. Both modes continue through Integration, self-play semantic probes, and configured match evaluation.

In LLM mode, inherited `configured_seeds` generation zero uses the bounded decoder for every replicated population slot, so each records a separate request and can produce its own Java phenotype. In LLM-mode `llm_generated_policies`, policy-only initialization calls occur before decoding; every policy is then independently decoded to Java. WorkerRush Java is inherited request context, never the policy's generation-zero phenotype. Later LLM generations pass the independently selected Java component into base and compile-repair requests without mutating that stored input during evaluation.
The seven-check Integration probe is deliberately smaller than a match but is
not an empty-state smoke: it loads separate populated 8×8 bases/workers maps,
invokes independent one-argument agent instances for the two player sides, and
rejects null or integrity-invalid `PlayerAction` values before safe issuance and
one cycle per state. This exposes map-coordinate and cross-side state faults
before the 180-match matrix without treating an Integration failure as a decoder
retry signal.

## Match protocol

`evaluation.mode: fixed_roster` is the default protocol below. With
`evaluation.mode: self_play`, generation zero is evaluated against the fixed
`PassiveAI` baseline so independently generated candidates receive a meaningful
score spread before candidate opponents exist. The completed generation-zero
candidates are persisted as an exact birth-generation cohort. Generations 1
through `self_play_refresh_interval` use that cohort as the immutable ten-slot
context; at generation `self_play_refresh_interval + 1`, the context switches
to the generation-one cohort, and the same delayed schedule continues. Only
candidates with a successful compile, no failure stage/reason, and a complete
match batch may enter a cohort. The semantic opponent library remains as a
bounded deduplicated archive, but it is not used to replace the exact
generation-cohort schedule. Every match records the context ID plus source
candidate/generation. Refresh first re-evaluates phenotype-preserving parent
replicas, so selection never mixes old-context parents with new-context
offspring. Resume reloads the latest delayed snapshot and resolves its exact
cohort references.

The fixed roster is defined by `eagle/opponent_cases.py` and resolved by
`eagle/opponents.py`. Each opponent receives three configured maps, three
rounds, and both candidate player positions. The matrix is owned by
`eagle/evaluation/match_matrix.py`; execution is owned by
`eagle/evaluation/runtime_evaluation.py`. A map entry may carry a positive `tick_limit`;
otherwise it inherits the legacy top-level `tick_limit`. The matrix attaches
the resolved limit to every match specification, so search, AOS head-to-head,
and final-test matches use the same cap for a given map.

Normal matrix execution always uses ten bounded match workers, based on the
bundled MicroRTS benchmark. Match count is fixed and is not configurable. Each
match owns an isolated artifact directory, and results return in canonical
`match_index` order. Worker count is fixed by `eagle/execution.py`; there is no
serial mode or experiment override.

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

## Fixed cross-generation evaluation

`python -m eagle.fixed_evaluation --run-dir runs/<run>` evaluates exact generation snapshots under one frozen protocol. Optional `--generations`, `--seed`, and `--output-dir` override defaults. It requires a completed run and each requested snapshot; it never substitutes a generation. Per snapshot it selects the runnable survivor with the highest finite generation-local `game_performance`: self-play fitness objective `game_performance` takes precedence, otherwise the value is `game_eval_result.game_performance`. Candidate ID breaks ties deterministically. A run-wide summary best is not used.

Each representative is separately recompiled and integrated from preserved Java, without an LLM or search-artifact changes. All representatives share the existing final-test ten-opponent roster, configured three maps and tick caps, and ten games per side per map (600 matches each). Seeds use one stream derived from the protocol root seed, independent of candidate ID and birth generation. The protocol records the seed scheme, roster, map hashes and tick caps, scoring, and runtime opponent source identities. Failed matches remain explicit errors, not zero-win results; partial progress is retained. Per-generation normal final-test JSON/CSV/Markdown files and combined `fixed_evaluation_summary.json`, `fixed_evaluation_results.csv`, and `fixed_evaluation_results.md` include W/L/D/E, mean match score, and selection source. `mean_match_score` is the unweighted mean of benchmark match scores, separate from canonical search fitness. An explicit output directory must be new or empty; reruns need another directory to preserve prior evidence. An incomplete or error-containing matrix has null aggregate score and win rate and causes a nonzero exit. Output defaults to separate `fixed_evaluation/`; ordinary `eagle.final_test` behavior is unchanged.
