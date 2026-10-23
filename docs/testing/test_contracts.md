# Test contracts

## Nearest-behavior mating (2026-10-23)

`tests/test_single_objective_selection.py` covers nearest distinct mates,
positive and zero distances, inclusive fitness-tier boundaries, seeded
order-independent distance ties, singleton reuse, missing/incompatible
signature fallback, and unchanged farthest-first survivor selection.
The focused WSL batch passes all 60 tests across that module,
`test_framework_slots`, `test_framework_slots_candidate_config`,
`test_framework_slots_integration`, `test_framework_coach_integration`, and
`test_offspring_concurrency`.

The new `1023_rich_framework_local_nearest_20x10_seed8_13_1run` YAML passes
`ExperimentConfig.validate()`. An assert-based check confirms its six-run seed
schedule (8–13), population 10, 20 generations, local mutation, and disabled
Commentator. Building its production search runtime with LLM preflight and
prompt-backend creation patched to fail succeeds with an empty mutation-LLM
mapping. No full suite or evolutionary experiment was run.

## Shared continuation and index isolation (2026-10-22)

`tests/test_search_loop.py` checks state propagation across generations,
early stopping from a checkpoint, and absence of successful finalization after
an interrupted/failed generation. `tests/test_evolution_reproducibility.py`
checks fresh/interrupted/resumed trajectory equality and stagnation replay
through the shared loop owner. `tests/test_gui_data.py` additionally checks in
a fresh interpreter that importing GUI data does not load experiment orchestration;
existing GUI/index tests retain malformed-index protection and legacy/versioned
batch behavior.

Final grouped WSL regression: 44 targeted evolution/replay/resume/self-play/
parent-evaluation/Coach-integration tests pass (715.980 seconds); the remaining
759 discovered tests pass with five skips (409.946 seconds). Together these
cover all 803 discovered tests, with 798 passes and no failures. The three
new loop tests also pass independently. Compileall, experiment/gui CLI help and
diff checks pass. Wheel validation remains unavailable because the existing
venv lacks `setuptools.build_meta`; no dependency was installed for this refactor.

## Dependency-driven scheduling validation (2026-10-21)

WSL full discovery exercised 796 tests (788 passed, five skipped, three stale
test expectations). The batch-function patch, list-only interrupted-candidate
fixture, and framework inactive-prompt expectation are updated; all three
isolated reruns pass. The final tree also passes 14 streaming/server-capacity
tests, 45 routing/runtime/final-test tests, compileall and diff checks. Full
discovery was not repeated after those repairs. Skips cover four native Windows
checks and one unavailable saved AllInBot regression class tree. Live multi-host
LLM execution and performance gains remain unmeasured.

## Local experiment GUI

`tests/test_gui_data.py`, `tests/test_gui.py`, and `tests/test_gui_match.py`
cover confined config paths, generated-index protection, exact YAML/unknown
field retention, validation-before-save, atomic replace failure, survivor
snapshot membership and retained parents, transient artifacts, materialized
other candidates, immutable launch inputs, canonical CLI flags, stop ownership,
bounded logs, observation command construction without fitness writes, and
loopback Host/Origin/token guards. Observation can read canonical historical
runs without applying current resume-only runtime validation. Adapter tests
cover WorkerRush and SafeAllInBot classpaths and temporary compilation wiring.
Platform checks cover POSIX session/stop behavior, Windows owned console group
creation and Ctrl+Break dispatch, UTF-8 child logs, and portable map paths.
`tests/test_interrupts.py` checks handler restoration and, from a Windows
console, waking a blocked child and completing cleanup. Native process tests
in `tests/test_runtime_windows.py` verify command quoting, creation-time
identity fences, liveness, termination, listener discovery, and exclusive
port checks. Real Java compile/integration tests exercise explicit UTF-8;
native GUI smoke verifies a 100-tick window match without changing the Run.

Browser checks cover form/YAML round trips, rejected invalid values,
run/generation/candidate selection, and desktop/mobile layout. A bounded
non-headless MicroRTS game checks WSLg startup separately from mocked launch
tests; it does not establish full experiment/model or all-opponent coverage.

## LLM-mode DSL and pre-crossover source contract (2026-10-11)

Test canonical DSL validation, ordered rules, intrinsic legality guards, idle
empty rules, unknown-field rejection, and seed/LLM/rewrite boundaries. Verify each
contributor uses its own policy/exact Java before variation; defects/failed checks
yield one-parent unchanged-gene branches, and Code receives no AOS reward. Code
v6 tests cover defect/fidelity repair, ambiguous/all-pass no repair, cosmetic-field
rejection, retries/raw retention, generation-model correction without overwrite,
and incompatible resume rejection.

Tests must prove the normative architecture, not preserve accidental current structure. Read the canonical document for every changed responsibility.

## Standard command

Run from either native Ubuntu Linux or WSL2 Ubuntu, with the checkout inside the
Linux filesystem:

```bash
cd ~/EAGLE
python3 -m unittest discover -s tests
```

Use narrower test modules while iterating, then run the full suite. A real MicroRTS/Java check must be bounded and explicitly identified; do not run an evolutionary experiment as validation.

## Contract matrix

Fixed evaluation focused validation (2026-10-17):

```bash
.venv/bin/python -m unittest tests.test_fixed_evaluation tests.test_final_test tests.test_evaluation_reproducibility tests.test_experiment_launcher
```

All 52 tests pass in WSL, including two real Java compilations, seven Integration
checks per representative, and 12 paired-seed MicroRTS matches against PassiveAI.
External-opponent setup is stubbed in that smoke. This does not establish full
ten-opponent or historical-run benchmark results; full discovery was not run.

| Area | Required proof |
| --- | --- |
| Candidate | in `llm` mode, default two-prompt and opt-in prompt/prompt/Java modes; in deterministic mode, active policy-only genotype; generation-qualified seeded IDs, explicit-ID preservation, and fail-closed rejection of missing IDs; inherited Java versus generated phenotype separation; terminal failure retains state |
| Lineage | seed/copy/crossover/mutation schemas; active component parent IDs resolve for the selected materialization mode; graph acyclic |
| Crossover | in `llm` mode, independent whole-component choices for both prompts and, when enabled, Java; in deterministic mode, whole-policy only; exact provenance; equal-text case; default mode has no Java inheritance |
| Strategy Mutation | Strategy mutation in both modes; in `llm`, Commentator per selected match → Coach → final Java generation; in deterministic DSL mode → policy compiler; only policy changes; no Java/code-prompt evidence; in framework `llm_coach`, exactly one worst completed parent match → Commentator → Coach complete-genome response, with strict schema/hash/domain validation and failed-child pre-Coach genome retention |
| Prompt Mutation | in `llm` only: Strategy-region Policy-Code Reviewer → exact reusable-rule delta JSON → deterministic generation-prompt rendering → final Java generation; only code-generation prompt changes; no raw game logs |
| Independent Code source gate | in `llm` only: Policy + selected parent Java + immutable gameplay/API/scaffold context → structured diagnosis during reflection phase → deferred complete corrected Java during final materialization → direct validation/compilation; LLM-mode prompt genes and configured inherited Java input are preserved; no W/D/L, matches, traces, fitness, or reusable generation prompt; source-matching compiler diagnostics are allowed; successful output is not overwritten by Generator |
| Generation | in `llm`: each source-policy/Java check precedes actual crossover/mutation; all contributors must pass; each child's reflection/rewrite precedes its own materialization; permanent role endpoints replace generation-wide switching; resolved experiment seed is present in every OpenAI-compatible LLM request; default seed-phenotype initialization; inherited configured-seed replication with one decoder call per slot; mixed initialization with one configured policy, LLM-generated remaining policy genes, and one Java decode per policy with WorkerRush only as inherited context; active genes + fixed scaffold/API constraints; complete extracted envelope/security checks followed by deterministic canonical-scaffold-plus-strategy normalization; distinct extracted/normalized evidence; base retry only after extraction failure; compile-guided retry from the immediately previous normalized complete failed source and structured diagnostics; unchanged genes/lineage/AOS; per-attempt request hashes and interruption-safe evidence; deterministic non-diagnostic drift guard; first compile success selected; failed source is not phenotype; no game logs; in framework `llm_coach`, initial selection returns one exact complete bundle-hash-pinned genome per slot with raw-before-parse bounded attempts and no random fallback |
| Validation | exact `ai.generated.CandidateAgent` package/class/superclass, both constructors, required `getAction`/`reset`/`clone`, security restrictions, direct strategy-map reads rejected in favor of bounds-safe `isFreeCell`, and no fixed internal layout |
| Compilation | attempt-isolated output; each validated source compiled at most once; first success promoted without recompilation; warning flags; diagnostic parsing/deduplication |
| Integration | all seven ordered load/type/two-constructor/reset/clone/getAction/PlayerAction checks; two populated real 8×8 maps, independent one-argument instances/states for both sides, action integrity plus safe issuance/cycle; `passed`/`failed`/`blocked`; no match execution or decoder retry |
| Matches | one promoted source/class tree; complete configured matrix with resolved per-map tick caps in normal, AOS head-to-head, and final-test execution; a real distinct WorkerRush; pinned AllInBot original JAR/class plus separately compiled reflection adapter; a contained upstream fault remains `ok` but is a machine-readable neutral draw, never a candidate win/failure; population-summed generation counts; distinct directories and round indices; both sides; no fake match-seed property; no regeneration after Integration starts |
| Fixed cross-generation evaluation | completed-run and exact-snapshot requirements; default/explicit generations and config-derived seed; highest finite generation-local Game Performance among runnable survivors with deterministic ID ties; no summary-best or generation fallback; one frozen protocol and candidate-independent seed stream; separate compile/Integration; 600 matches per representative; explicit errors and retained partial evidence; exact combined filenames; new/empty output directory; unweighted benchmark mean distinct from search fitness; null aggregate score/win rate and nonzero exit for incomplete/error matrices; no LLM or search-artifact mutation |
| Game Performance | exact canonical component math, clamps, bands, aggregation, partial-batch failure |
| Code Quality | `[0,100]` simplicity score from four weighted complexity penalties, persisted details, diagnostic separation, and `-1000` failure sentinel for both objectives |
| Artifacts | run-v2/generation-v3, with LLM phase4-v6/candidate-v6 and deterministic phase4-v7/candidate-v7 contracts; v2 root allowlist; one resolved `config.yaml`; referenced generation/candidate reconstruction; interruption safety; absence of obsolete config, population, candidate-summary, and match-result duplicates |
| Timing | UTC fields, monotonic durations, LLM attempts or deterministic materialization timing, optional null stages, 180 match durations; match timing lives in `result.json`; deterministic-mode match seeds are stable and persisted; framework `llm_coach` initialization and Coach attempts are timed with one run event per actual request while Java `generation_llm` remains empty |
| Opponent-wise lexicase | exactly ten maximized opponent cases; seeded case-order filtering; joint parent-plus-offspring selection without replacement; failed offspring cannot displace completed parents; fixed-size survivor behavior |
| Self-play | Approved `tournament-v1` contract: exact policy-marker gating and legacy resume fence; capacity includes permanent protected four and rejects values below 10; seed-deterministic deduplication/admission; seeded one-incumbent tournament; 18-match W/D/L scoring, strict promotion, and incomplete/error non-promotion with retained evidence; generation-zero ten built-in sources under fixed slot IDs (protected actual IDs plus six diagnostic slots); refresh context uses four protected case IDs plus six sampled members in `self_play_000`…`self_play_005`; uniform slot weights; scalar Game Performance; context/configuration/case IDs persisted with cached scores; runtime/map asset identity verified before cache reuse; same-context parent refresh; pool checkpoint/restore before replay; v4 snapshot/context hash; prepared defender class-tree and available builtin hashes in tournament evidence; opponent-pool archive and timing event. Validated by 28 focused tests and a broader 105-test regression run (one skip), plus a separate 36-match real runtime smoke against LightRush and a saved generated defender. Full real evolutionary runs and the complete permanent roster were not exercised; historical cohort/FIFO results describe prior behavior only. |
| Semantic signatures | exactly three maps × early/mid/late states; full compiled agent actions; deterministic canonical hashes and cache hits; dataset-scoped exact equivalence; missing/incompatible fallback; artifact-only offline analysis |
| Reflection operator selection | Exactly `static`, `aos_opponent`, and `aos_head2head`; config validation and resume identity; fixed static probabilities with no credit matches; comparison parent follows policy/generation-prompt/Java mutation-evidence provenance after crossover; execution-first ten-case rank reward without direct matches; configured head-to-head matrix with `[0,1]` W/D/L reward; shared EMA/floor; common artifacts and mode-labelled analysis |
| Operations | shell positional mapping; sorted non-recursive directory batch; single YAML; direct-config replicates with incremented seeds or repeated `random_seeds`; ordered multi-replicate folder slots indexed by exact config filename; `eagle-experiment-index-v1` schema and absolute paths; legacy one-path mapping read and atomic upgrade; effective-seed validation; completed-slot skip; interrupted/final-test recovery before missing replicates; pre-generation-zero slot replacement retaining prior evidence; fresh index on fresh launch; `experiment-v2` filename preservation; fresh owned llama-server per run; final-test-only recovery avoids LLM startup; mock port isolation; runtime lifecycle, failure cleanup, foreign-process safety, stale-state reconciliation, experiment-state isolation, skip-final-test; mandatory GPU preflight plus fresh-child positive full `offloaded N/N layers to GPU` evidence; missing, stale, malformed, or partial evidence shuts down owned server and fails without CPU fallback; an optional managed primary (both runtime paths) or external primary (neither path), an externally started generation profile, plus at most one ordered additional `{base_url, model}` endpoint per profile; all-endpoint fail-closed chat preflight; RuntimeManager ownership limited to primary; fixed GPU layers `999`, model threads `8`, managed-local server slots `2`, LLM workers `2`, match workers `10` by default, persisted `evaluation.match_execution` round-trip with `serial` selecting one worker; per-request `context_size` passed as total managed-local server context `context_size × 2`; canonical-index endpoint binding, sticky retries, no failover, ordered result collection, queued-work cancellation, and active-request drain; per-child dependency order with permanent role clients, cross-stage server-origin request limits, streaming match/preparation overlap, canonical result reordering, and active-worker drain; serial ordered AOS reward application with unchanged formulas; no trace cleanup before dependent candidate work completes |
| Offline analysis | explicit/latest run resolution is deterministic; only direct canonical children are eligible; only `generation_####.json` survivor snapshots are loaded; self-play sidecars are excluded; partial/failed runs expose derived failure outputs; unsupported or historical schemas fail explicitly; per-agent/win-rate/match plot rows use survivor snapshot generation and retain candidate birth generation; `results.jsonl` is never read |
| LLM server lifecycle | missing executable/model; bounded readiness; occupied local port; primary plus additional endpoint identity/order; chat completion required from every endpoint; durable actual-route logs; no cross-endpoint failover; and stopping only the primary local process created by the experiment orchestrator |

## Failure fixtures

Maintain deterministic fixtures for:

- backend/empty/extraction failure;
- source validation failure;
- compilation failure with controlled error counts;
- each of the seven integration-check failures and prerequisite-blocked states;
- runtime failure after 0, 5, and 9 matches;
- original AllInBot failing phenotype versus reflection-adapter recovery, one-time marker persistence, and neutralized candidate score;
- successful win/draw/loss batches;
- mutation Reflection failure, Rewrite failure, and final generation failure;
- artifact write interruption where supported.

Each fixture asserts both objectives, terminal stage, retained artifacts, and timing closure.

## Test quality rules

- Prefer typed fixtures and exact persisted payloads over checking console prose.
- Do not make fixed helper names, strategy markers, code length, or function count a contract unless the normative spec is changed.
- Mock LLM calls must record stage/order/attempts and return realistic raw payloads.
- Mixed initialization tests must prove one configured Worker Rush policy, nine
  independent non-`RandomAI` policy-only calls for a population of ten, raw
  response persistence before parsing, duplicate retry evidence, and identical
  generation-zero Worker Rush Java hashes.
- Test no-regeneration by counting backend calls and comparing source hashes across matches.
- Test compile-guided decoding as a chain: extraction-only retries preserve the
  base request, while validation/javac failures produce distinct requests that
  contain both authoritative genes, immutable API/scaffold, only the immediately
  previous source and diagnostics, and matching request/source hashes. Exhaustion
  must leave `selected_attempt: null` and no phenotype.
- Test canonical scaffold normalization with a realistic model deletion or
  rewrite of fixed source: the extracted artifact retains the drift, the
  normalized source restores the configured scaffold, the strategy region is
  unchanged, and compilation occurs without a scaffold-only repair attempt.
- Use sentinel-based structural tests to prove Commentator/Coach exclude Java,
  Prompt Reviewer excludes raw game logs, Code Reflection excludes the reusable
  generation prompt and match evidence, and all operators preserve fields they
  do not own.
- Keep regression fixtures for observed structured-output variants: wrapped
  Commentator analyses with tick ranges and Reviewer generation corrections
  split into arrays. Assert their canonical parsed form as well as rejection of
  missing evidence and responsibility-boundary violations.
- Test formulas only in their canonical test module; other tests assert references/results, not copied arithmetic.
- Unsupported run schemas must fail explicitly; no legacy reader may silently activate.
- Indexed folder resume may accept only an `experiment_name` metadata correction;
  direct resume and every execution-affecting config field remain strict.
- Compact v3 analysis fixtures must prove candidate references recover
  `opponent_results.match_scores` from the canonical evaluation artifact as
  narrow per-generation violin distributions while
  leaving bulky raw per-match payloads out of the in-memory analysis view.
- Reproducibility checks compare repeated seeded mock EA trajectories, one versus
  multiple match workers, deterministic tie-breaking under reordered inputs,
  interruption/resume, root-seed changes, independent request/retry seeds, and
  stable canonical-index endpoint assignment under out-of-order completion.
  Endpoint-pool unit coverage uses slot, backend, and preflight mocks to prove
  route selection, sticky dependent retries, no rerouting after failure, and
  input-ordered results without claiming a live two-host concurrency result.
  Java seed-source checks validate repeatability in the actual JVM; seeded
  evaluator tests force out-of-order completion and compare canonical results.
- A mock search is a smoke test, not proof of real Java/MicroRTS integration.
- Java seed text hashes normalize checkout line endings; shell scripts use LF.
- AlliBot metadata pinning tests use isolated fixtures and compile the real reflection adapter. Historical runtime regression requires its actual candidate and upstream assets.

## Documentation completion

When tests reveal a code/spec discrepancy, update [`../implementation/architecture_gaps.md`](../implementation/architecture_gaps.md). When documented behavior changes by explicit decision, update the authoritative/canonical docs and the Chinese overview according to [`../README.md`](../README.md).
Focused runtime tests must prove that the selected experiment GGUF is passed to
llama.cpp, an identical folder-batch runtime is started only once, A/A/B/B/A
switching is exact, PID reuse cannot satisfy ownership, unrelated processes are
never stopped, verified stale state is cleaned, only the primary local process
is lifecycle-managed, and every EA LLM operation records its actual resolved
endpoint/model identity. Config and resume tests must preserve the endpoint list
and order exactly. Actual shell and direct-Python mock commands remain required
workflow checks in addition to unit tests.

The focused multi-endpoint suite and full repository suite pass. On 2026-10-15,
`http://192.168.1.136:1234/v1/models` and a bounded
`/v1/chat/completions` request for `qwen/qwen3.5-9b` both returned HTTP 200 with
valid OpenAI-compatible response structure. Full operational verification still
requires one bounded experiment smoke demonstrating overlapping local/remote
requests with both routes visible in artifacts.

```bash
python3 -m unittest tests.test_multi_endpoint_llm tests.test_llm_client \
  tests.test_execution_concurrency tests.test_llm_task_seeds \
  tests.test_offspring_concurrency tests.test_runtime_workflow \
  tests.test_experiment_launcher tests.test_llm_logging \
  tests.test_generation_attempts
# Ran 95 tests ... OK

python3 -m unittest discover -s tests
# Ran 660 tests ... OK (skipped=4)
```


## Deterministic Java materialization

Prove byte-identical output for equal normalized policy/compiler/scaffold inputs;
all DSL actor, condition, metric, selector, action, ordering, fallthrough,
reservation, hash-index (including signed long overflow), and return semantics; validation/javac of golden sources;
no generation, Code Reflection, Prompt Reflection, or compile-repair backend call;
stage-correct failure with compiler evidence and no LLM fallback; exact active
genotype metadata; empty/null `generation_llm`; child-total inclusion of
`java_materialization`; hash readback; and explicit mode/compiler resume rejection.
Bounded real validation covers WorkerRush, adjacent/distant return, and
choose/hashed behavior plus a deterministic smoke run with zero Java LLM calls,
reconstructible source, complete semantic probe, and executable matches. Do not
run the full evolutionary experiment for this contract.

WorkerRush validation additionally runs the compiled generation-zero reference
and vendored `ai.abstraction.WorkerRush` in lockstep on all three canonical maps,
both player sides, and compares every issued unit action across multiple cycles.
It also verifies Gen 0 selects the reference policy and persists the exact
vendored source hash. Match W/D/L is supplementary evidence, not the parity
oracle.

### Verification recorded on 2026-10-14

Use the existing project virtual environment for repository validation:

```bash
.venv/bin/python -m compileall -q eagle
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m eagle experiment \
  --config-dir configs/experiments/1018_rich_framework_local_20x10_seed8_1run/qwen3_5_9b_rich_framework_local_20x10_seed8_1run.yaml \
  --skip-final-test
git diff --check
```

| Evidence | Result |
| --- | --- |
| DSL compiler contracts | 9 tests pass, including every comparison/metric, field-order invariance, current WorkerRush policy, legal selector/choose indices, busy-unit rank, priority/fallthrough, reservations and explicit no-op idle. |
| Real golden source checks | Empty, WorkerRush and full-grammar snapshots each pass source validation, javac and all 7 Integration checks. |
| Dedicated return and seed scaffolds | 4 tests pass; adjacent return transfers a carried resource, distant return moves, no nullable Harvest is constructed, and both existing seed scaffolds compile/integrate. |
| Materialization, launcher and resume | 35 targeted tests pass, including legacy manifests without protocol fields, unknown versions/schema/hash rejection, one javac and zero Java-backend calls. |
| Prompt resources and analysis | 26 tests pass in the project environment. Explicit WorkerRush seed configs remain supported; inactive deterministic generation prompts are not asserted as active. |
| Stage ordering and timing | Integration precedes the diagnostic probe, then matches. Simulated 3-second probe + 5-second matches remain in the 8-second evaluation span and child total. |
| Final repository regression | 585 tests complete with zero failures/errors and one existing skipped GUI match test; see `runs/deterministic_full_regression_final.log`. |

Real smoke evidence lives in `runs/20261014_144034_023082`, with
`deterministic_smoke_audit.json` recording two evaluated candidates, 180 real
matches per candidate, 7 passed Integration checks, 9 complete semantic probes,
zero LLM request events, and byte-identical reconstruction from the saved policy
and scaffold. Both sources hash to
`011184423f80f3465bbd45e5c928fbecd0ff216f3609e6e82d9a4e30c04f0ffb`.
Run outputs are local evidence, not tracked historical artifacts.

The smoke uses the existing self-play library because this local checkout lacks
`third_party/gui_opponents/jars/allibot.jar`. Fixed-roster contracts remain covered
by unit/regression tests; a real fixed-roster smoke requires that existing asset.
The 1- and 10-tick trial caps were too short for three distinct actionable phases;
the committed smoke uses 100 ticks. No 20×10 evolutionary experiment was run.

## Groq framework and finite slots

Inline startup tests cover design-brief/model config round trips, generation before
population initialization, failure evidence without binding a batch-index slot,
mock-mode rejection without network calls, and frozen-bundle resume with source
identity checks. Stubbed evaluation covers the complete startup-to-EA handoff.

For `framework.evolution_mode`, test that omission resolves to `local`,
`llm_coach` is opt-in, and resume rejects a mode mismatch while keeping the
materializer version unchanged. Local mode retains seeded sampling/per-slot
variation and zero candidate-time LLM calls. Coach mode tests exact response
keys, frozen byte hash, complete slot coverage, numeric lattices, declared
expression choices, duplicate-key and non-JSON-wrapper rejection, raw-before-parse persistence, bounded attempts, attempt/run
timing, one-worst-match Commentator→Coach context, parent-genome retention on
failed mutation, and absence of Java Generation/repair requests.

Tests must prove the bootstrap sends user-message content, model, temperature,
and `max_completion_tokens` to the Groq Chat Completions endpoint; requests
`response_format` JSON Schema named `eagle_framework` with `strict: false`; and
persists credential-free requests and raw bytes before parsing. A provider
`json_validate_failed` response is a retryable bootstrap attempt; the next
request uses JSON Object Mode and still passes local exact validation. Tests
also cover failed attempts, bounded provider diagnostics and retry
classification, exact bundle/report/marker validation, normalized bundle
selection, and that provider credentials (`GROQ_API_KEY` and `api_key/mistral`)
are never persisted. Provider schema
enforcement is best-effort; local exact validation, CLI dispatch, and
non-overwrite behavior are contracts.

Core tests must cover exact-key rejection, finite numeric lattices, enumerated
expression choices, canonical hashes, insertion-order-independent rendering,
unresolved/duplicate marker rejection, seeded generation-zero sampling,
deterministic per-slot crossover/provenance, and one-slot mutation to a different
legal value. Candidate/config tests must prove `control_genome` is the only
active component and exact bundle bytes/version/hash are fenced.

Pipeline/artifact/resume tests must prove the run-owned
`framework/bundle.json` is immutable; candidate inputs precede materialization;
source is reconstructible from bundle plus genome; framework evidence contains
all hashes; validation/javac/Integration/matches are unchanged; render or compile
failure has no LLM fallback; local mode has empty reflection/generation timing streams;
and drift, unknown versions, incomplete slot provenance, or mismatched hashes
fail before replay. The focused command is:

```bash
python3 -m unittest \
  tests.test_groq_framework \
  tests.test_framework_slots \
  tests.test_framework_slots_candidate_config \
  tests.test_framework_startup \
  tests.test_framework_slots_artifacts \
  tests.test_framework_slots_integration \
  tests.test_framework_coach \
  tests.test_framework_coach_integration
```
