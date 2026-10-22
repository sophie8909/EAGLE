# Current implementation status

## Fixed server routing and streaming candidates (2026-10-21)

Functional clients stay bound to `model` and optional `generation_model`; no
phase-switch callback remains. Omit both primary runtime paths to call an
externally started primary. Generation servers are always external. A managed
primary is stopped before a batch transitions to an external profile.
Runtime startup rejects different models sharing one endpoint before preflight;
historical staged configs remain loadable for read-only analysis and final tests.

Canonical source-gated plans stream into two preparation workers. Ready
candidates run one ten-worker match matrix while later children continue
source checks, crossover, mutation and materialization. Server origins share a
two-request limit across roles. Results retain original ordinals, seeds and
candidate ordering. Cancellation closes the source, cancels queued work and
drains active gates/preparation; timing JSONL appends are synchronized.
Self-play context, parent-score refresh, AOS, survivor selection, checkpointing
and trace-retirement dependencies remain in place.

Validation: WSL discovery exercised 796 tests: 788 passed, five skipped, and
three stale test expectations failed (the renamed batch patch target, list
slicing in an interruption fixture, and the already-inactive framework Java
prompt). Those fixtures are corrected and all three isolated reruns pass,
including fixed-roster and self-play interrupted-work archive/resume replay.
After the last compatibility/wait changes, 14 streaming/capacity tests and 45
routing/runtime/final-test tests pass, as do compileall and diff checks.
Discovery was not repeated on the final tree. Four skips require native Windows;
one lacks the saved AllInBot regression classes. No live multi-host LLM run or
speedup benchmark was performed.

## Fixed cross-generation evaluation (2026-10-17)

The separate `eagle.fixed_evaluation` command compares runnable survivors from exact requested snapshots under one frozen final-test protocol. Selection uses the highest finite generation-local Game Performance with deterministic candidate-ID tie breaks; missing snapshots do not fall back. Each representative is separately recompiled and integrated, then receives 600 matches with candidate-independent seeds. Protocol, per-generation evidence, combined summaries, and partial progress live under `fixed_evaluation/` by default, outside canonical search artifacts. Combined filenames are `fixed_evaluation_summary.json`, `fixed_evaluation_results.csv`, and `fixed_evaluation_results.md`; explicit output directories must be new or empty. Mean match score is an unweighted benchmark mean, not search fitness; incomplete/error matrices have null aggregate score and win rate and exit nonzero. The live evaluation of `runs/20261015_003919_084002` completed on 2026-10-17 for generations 0, 5, 10, 15, and 20: all five 600-match matrices completed with zero errors. Results are under `runs/20261015_003919_084002/fixed_evaluation/`; generation 5 had the best fixed benchmark mean match score (-15.863318), while generation 20 scored -25.472979.

All 52 focused fixed-evaluation, final-test, reproducibility, and experiment-launcher tests pass in WSL. The bounded real smoke recompiles two preserved WorkerRush sources, passes seven Integration checks for each, and runs 12 paired-seed MicroRTS matches against PassiveAI across three maps and both sides. External-opponent setup is stubbed in that smoke. Compileall, CLI help, and diff checks pass; full discovery was not run, and the live 600-match-per-representative benchmark is recorded above.

## Local experiment GUI (2026-10-16)

`python -m eagle gui` provides config selection, enum/boolean form controls,
full YAML editing, validated atomic save, immutable launch snapshots, bounded
live logs, stop/resume controls, and automatically refreshed canonical
run/generation/candidate lists. Visual observation invokes the retained
temporary compile/integration/MicroRTS launcher and does not change fitness.
`gui.sh` launches on native Ubuntu; `gui.cmd` uses native Windows Python.
`gui-wsl.cmd` retains WSL launching and WSLg observation. Windows child jobs
use owned console groups and graceful Ctrl+Break handlers; Ubuntu retains
POSIX sessions and signals. Runtime assets and absolute config paths must
match the destination OS when migrating.
Runtime ownership supports native Windows creation-time/executable/command
identity and listener discovery alongside Linux `/proc`. Java compilers use
explicit UTF-8 on both platforms. Native Windows GUI HTTP, interrupt cleanup,
and a 100-tick WorkerRush window match were verified; an actual Windows
llama-server/GPU/model experiment remains unverified.
The visual launcher now prepares the existing WorkerRush and SafeAllInBot
adapters and uses the canonical `lightrush` default.

## DSL and pre-crossover source contract (2026-10-11)

Canonical `eagle-strategy-dsl-v1` policies are validated by `eagle/strategy_dsl.py`.
The checked-in WorkerRush seed is a closed canonical-reference policy. In
deterministic mode its CandidateAgent delegates to the vendored upstream
WorkerRush, replays the exact action vector, and persists the reference source
hash; LLM-generated and mutated policies remain finite-rule-only.
In LLM materialization mode, every reproduction source is independently gated before actual variation. Defects
yield corrective one-parent children; failed checks cannot enter variation. Normal
mutation/AOS covers Strategy/Prompt. Code v6 permits fidelity/correctness repair
only. Historical policies remain read-only; incompatible resume fails. See the
[integration plan](dsl_pre_crossover_reflection_plan.md) for verification.

Snapshot: 2026-10-15. Unless explicitly marked, implementation details below describe LLM materialization. Deterministic DSL materialization is implemented; verification evidence is recorded in `../testing/test_contracts.md`.

## Active evolutionary contract

- The resident `python -m eagle monitor --runs-root runs` command exposes a
  read-only detailed `eagle-monitor-status-v1` HTTP snapshot for every
  canonical run below the root, automatically discovering runs created later
  by `experiment`. `/status.json` and the derived JSON snapshot use the compact
  `eagle-monitor-summary-v1` schema with run/generation/PID/liveness fields.
  Active runs whose recorded PID disappeared are reported as
  `unexpected_termination`, distinct from normal `complete` runs and from
  explicit `interrupted`/`failed` manifests. The monitor reads only atomic
  manifest/latest generation artifacts, includes host resource telemetry and
  bounded failure summaries in the detailed endpoint, defaults to loopback,
  and optionally accepts a token for non-loopback binds. It has no
  experiment-control operations.

- `candidate_java_mode` controls Java phenotype versus inherited-Java state;
  `java_materialization_mode` independently selects `llm` (the backward-
  compatible default), `deterministic_dsl`, or `framework_slots`. Deterministic
  DSL activates only `strategy_prompt`; framework slots activate only
  `control_genome`. Framework evolution defaults to seeded local operators;
  opt-in `framework.evolution_mode: llm_coach` uses the experiment model only for
  initial full-genome selection and the existing Commentator/Coach Strategy
  path. Both framework policies retain the frozen bundle and
  `eagle-framework-slots-v1` materializer. Java Generation and repair remain off.
- EA factories derive candidate IDs as
  `gen_<zero-padded-generation>_<12-hex-deterministic-suffix>` from stable
  seeded lineage identity; `Candidate` rejects missing or blank IDs instead of
  using process-random UUIDs. Explicitly loaded IDs remain unchanged for
  artifact and resume compatibility.
- `initial_population_mode: llm_generated_policies` keeps one configured policy
  and fills the remaining population slots with independent policy-only LLM
  calls. The tracked mixed config therefore produces one Worker Rush policy plus
  nine generated RTS policy prompts. First-wave policy requests use one configured-seed snapshot with distinct task
  seeds. Policy transport is stateless; only Java-generation request context is
  thread-local. Results and duplicate retries resolve in candidate order, with
  an artifact for each bounded attempt. In LLM mode every
  policy independently enters the Java Generator; WorkerRush Java is inherited
  request context, not the phenotype.
- Default evaluation uses exactly ten fixed opponents: `passive`, `random`,
  `randombias`, `lightrush`, `heavyrush`, `workerrush`, `allinbot`, `mayari`,
  `coac`, and `tma`.
- Every candidate runs 180 matches: three maps × three rounds × both sides
  for each opponent. Evaluation maps may define independent positive tick caps;
  string-only map entries retain the top-level `tick_limit` fallback. Normal,
  AOS head-to-head, and final-test matrices share the resolved per-map caps.
- Match execution uses one ten-worker matrix at a time. Two source-gate workers
  release canonical plans; two preparation workers execute per-child mutation,
  revision/generation and compilation while ready candidates run matches.
  Canonical indices preserve endpoint routes, seeds, ordinals and final result
  order. All roles share two active requests per server origin; different servers
  proceed independently. AOS choices/rewards stay serial. Compact artifacts skip
  XML replay; full artifacts retain replay and round states.

- Controllable randomness is always seeded from the EA root `random_seed`.
  Stable task streams cover initialization, selection, operators, crossover,
  mutation, LLM requests, and all evaluation matrices. Parallel LLM and match
  work returns in input order and uses stable task/match seeds. Failed or
  interrupted phases cancel queued calls and wait for active requests before
  returning. GPU layers are fixed to `999`, model threads to `8`, LLM workers to `2`, and
  match workers to `10`. Runtime fixes `--log-verbosity 4` so core model
  offload evidence is visible, and `--fit off` disables automatic memory fitting.
  GPU preflight and fresh-child positive
  `offloaded N/N layers to GPU` evidence are mandatory. Missing, stale,
  malformed, or partial evidence shuts down the owned process and fails the run;
  there is no CPU fallback. LLM
  temperatures remain configurable; external backends and wall-clock budgets
  can still introduce nondeterminism.
- A direct config or folder batch may set `runs` to execute independent
  replicates. Without an explicit list, each run uses the base `random_seed`
  plus its zero-based replicate index. With `random_seeds`, `runs` repeats each
  listed seed in order. Every run writes a separate run directory; folder batches
  retain ordered replicate slots per config in `experiment.yaml`, keyed by
  zero-based replicate index and validated against each slot's effective seed.
- A task-specific seed derived from the resolved replicate root is propagated
  to every OpenAI-compatible LLM request as `seed` and recorded as `sampling_seed` in LLM timing/log metadata.
  `scripts/test_llm_stability.py` repeats one exact prompt and persists raw
  responses plus SHA-256 hashes for backend stability checks.
- Formal experiment runs restart the owned llama-server at every run/replicate
  boundary when local runtime paths are configured; external primaries have no process ownership.
  `RuntimeManager` manages only this primary local process. Every configured
  endpoint, including an additional external endpoint, must pass a fail-closed
  chat-completion preflight before candidate requests begin; external endpoints are
  never adopted, switched, signalled, or stopped.
- `scripts/test_llm_seed_restarts.py` provides the stronger diagnostic: it
  fully restarts the owned llama-server between seeds and records the server
  lifecycle alongside per-seed raw responses and hashes.
- Fixed-roster candidate fitness is a ten-field opponent score mapping.
  Self-play candidate fitness contains only `game_performance`. Failed or
  incomplete candidates receive `-1000.0` for the active objective(s).
- The approved self-play contract uses a capacity-bounded tournament pool,
  permanent protected opponents, seeded nonprotected duels, and immutable
  contexts using the protected four actual case IDs plus six diagnostic slots
  (all ten built-in sources at generation zero). Its artifact, resume-marker, and evaluation
  rules are owned by [`eagle_architecture_spec.md`](../eagle_architecture_spec.md#9-evolution-evaluation).
  The v4 snapshot validates configured runtime/map asset hashes before cached
  fitness reuse; `game_performance.json` retains context identity. Tournament
  evidence includes prepared defender class-tree hashes and available builtin
  source/resolved-class hashes.
  Tournament-v1 validation: 28 focused pool/config/context/resume tests passed;
  a broader 105-test regression run passed with one skip. A separate WSL runtime
  smoke completed 36 actual matches against LightRush and a saved generated
  defender, including compilation and Integration. Compileall and diff checks
  passed. A complete real evolutionary run and the full permanent roster were
  not exercised; this checkout lacks the AllInBot JAR.
- Fixed-roster parent/survivor selection is seeded lexicase. Self-play maximizes
  Game Performance, treats scores within `1.0` of a tier maximum as tied, and
  uses nine-probe full-agent behavior distance to preserve different semantics
  inside the tied tier. Survivor selection always uses the joint
  parent-plus-offspring (`mu_plus_lambda`) pool.
- Survivor selection keeps failed candidates in the diagnostic parent-plus-
  offspring pool but excludes them from survivor choice when completed
  candidates can fill the population; a failed offspring batch therefore keeps
  valid parents. It rejects pools with fewer than the configured number of
  completed survivors, and a run with no valid final population is persisted as
  `failed`, never `complete`.
- `parent_evaluation_mode: reuse_cached` is the canonical default and never
  regenerates surviving parents. The non-canonical
  `regenerate_same_genotype` diagnostic is limited to inherited Java plus
  static reflection; it evaluates fresh-ID, same-genotype parent replicas and
  selects from replicas plus offspring while retaining immutable source-parent
  artifacts and a generation audit sidecar.
- In LLM mode every selected source passes its own policy/Java gate before actual variation; deterministic mode disables this Java source gate.
  Healthy contributors undergo Strategy/Prompt variation; defects/failures yield
  one-parent diagnosed children. Each child's reflection/rewrite precedes its own
  materialization; corrective Java bypasses ordinary Generator overwrite.
- Fresh search and v2 resume now execute that generation lifecycle through the
  same `eagle.evolution.search.run_generation_step` owner; only initialization, snapshot
  loading, and finalization remain entrypoint-specific.
- The required `model` owns initialization and reflection/rewrite calls. An
  optional `generation_model` owns final Java materialization and compile repair;
  each functional profile may include one ordered `{base_url, model}` additional
  endpoint. Clients stay permanently bound; distinct generation servers remain
  externally managed. An external primary omits both local runtime paths.
  There are no generation-wide model switches.

- The reflection-operator controller supports exactly `static`, `aos_opponent`,
  and `aos_head2head`. Strategy/Prompt probabilities mean fixed probabilities in
  static mode and initial probabilities in AOS modes. Static performs no reward
  work. Opponent AOS uses execution-first ten-case W/D/L-rank change.
  Head-to-head AOS preserves the configured direct comparison matrix and
  `(wins + 0.5 × draws) / valid matches`. Both adaptive modes compare against
  the mutation-evidence parent resolved from policy, generation-prompt, or Java
  provenance, then share the alpha `0.20` EMA/probability-matching updater and
  configured minimum floor.
- The weighted aggregate Game Performance uses weights `0.5` for the three
  baseline cases, `1` for the three rush cases, and `2` for
  AllInBot/Mayari/COAC/TMA, with denominator `12.5`, for
  reporting only.
- `code_quality` is a diagnostic and mutation-evidence signal, not an objective
  and not an AOS operator schedule.
- Self-play never mutates fixed-opponent weights or the fixed-opponent archive.

## Active ownership

| Responsibility | Source |
| --- | --- |
| Fixed cases and reporting weights | `eagle/opponent_cases.py` |
| Candidate state and objective vector | `eagle/candidate.py` |
| Evaluation orchestration | `eagle/evaluation/pipeline.py` |
| Self-play opponent library, snapshots, and context validation | `eagle/self_play.py` |
| Match matrix | `eagle/evaluation/match_matrix.py` |
| Reflection selection, reward providers, shared AOS updater | `eagle/operators/adaptive.py` |
| Head-to-head-only parent-vs-offspring evaluation | `eagle/evaluation/parent_offspring.py` |
| Match aggregation | `eagle/evaluation/game_metrics.py` |
| Objective construction | `eagle/evaluation/objectives.py` |
| Parent and survivor selection | `eagle/operators/selection.py` |
| Evolution loop | `eagle/evolution/search.py`, `eagle/evolution/resume.py` |
| Generation-zero policy construction | `eagle/operators/initialization.py` |
| Experiment/model lifecycle | `eagle/experiment.py`, `eagle/runtime/processes.py` |
| Local experiment monitoring | `eagle/monitoring.py`, `eagle/cli/monitor.py` |
| Fully resolved experiment schema | `eagle/config.py`, run-local `config.yaml` |
| Per-opponent archive | `eagle/opponent_archive.py` |
| Run/generation artifacts | `eagle/run_artifacts.py`, `eagle/artifacts.py` |
| Offline analysis | `eagle/analysis/report.py` |

## Persisted per-generation evidence

Each `generations/generation_*.json` stores candidate IDs with ten-case
fitness vectors, one aggregate `metrics` object, and the generation AOS record.
Candidate state lives once in `candidates/<id>/candidate.json`; specialized
opponent evidence remains in `evaluation/game_performance.json`.
The analysis command turns these records into
`agent_win_rate.csv`, `match_game_performance.csv`,
`opponent_game_performance.csv`, individual-agent per-opponent win-rate/Game
Performance plots, per-opponent generation plots with single-match score
violin distributions, and AOS operator statistics/probability plots. The v2 loader
materializes bounded candidate analysis views from referenced candidate and
evaluation artifacts, so compact v3 generation snapshots do not discard the
single-match distributions. Derived analysis schema `eagle-analysis-v2` places
every selected candidate and its match evidence at the generation of the
survivor population snapshot; `birth_generation` separately preserves when the
candidate was created.

## Experiment lifecycle and run schema

`./experiment.sh CONFIG_TARGET [OPTIONS...]` translates its positional target
to Python `--config-dir`. Python discovers sorted top-level YAML files once,
loads each config once, and lets the batch owner validate the runtime and manage
its cleanup. Every run or replicate restarts the owned llama.cpp process at
the run boundary. Role clients remain permanently bound within that run. Mock mode never constructs a runtime
manager or inspects a port. Runtime state records PID plus process start time,
exact executable/command, launcher, owner token, and resolved spec; foreign port
owners are never killed.
Separate runtime/run compatibility commands are not part of production. The
dispatcher exposes only `experiment` and `analyze`.

Directory batches maintain an atomic `experiment.yaml` index in the selected
config directory. Its `eagle-experiment-index-v1` schema maps each exact config
filename to an ordered list of absolute run-directory paths; list positions are
zero-based replicate indices. The generated index is excluded from config
discovery. Legacy filename-to-path mappings are read as one-item lists and
upgraded atomically on the next run record. A legacy `experiment-v2` config
named `experiment.yaml` remains a config and is never replaced; that directory
cannot also hold the generated index.

`./experiment.sh --resume CONFIG_FOLDER` reads the existing index as a batch
checkpoint and validates each indexed run's effective seed against its scheduled
slot. Interrupted search runs and runs missing a required final-test summary are
processed first. Complete slots are skipped, then missing replicates are created.
A fresh launch starts a fresh index. If interruption happened before generation
zero was recorded, that slot receives a replacement run and prior evidence
remains on disk. Direct `--resume RUN_DIR` remains the single-run interface.
Final-test-only recovery does not start llama.cpp unless a later config still
needs LLM work.

For indexed folder resume, the exact config filename in `experiment.yaml`
anchors run identity. A corrected display-only `experiment_name` is accepted;
all execution-affecting fields remain strict. Direct config-plus-run resume
continues to compare the name as well.

New `eagle-run-v2` runs persist one fully resolved `config.yaml`; generation snapshots remain `eagle-generation-v3`, while candidate records use `eagle-candidate-v6` (`phase4-v6`). Subschemas are `reflection-v3`, `phase2b-v3`, `eagle-code-reflection-v6`, `strategy-reflection-v7`, and `eagle-llm-call-v2`. The root has
only manifest/config/summary/timing plus canonical directories. Candidate,
generation, match, archive, and config compatibility duplicates have been
removed. Analysis and resume both require v2 and use the run-local model and
experiment definition.

## Prompt ownership

All executable prompt bodies live under `prompts/`, with exactly one UTF-8
`.txt` file per prompt. `prompts/manifest.toml` stores only prompt metadata and
placeholder contracts. This includes the reusable generation prompt, Code
Reflection, the library Strategy Reflection/Rewrite
path, Match Commentator, all four Coach intents, generation,
the compile-guided Java repair decoder, the action-API guide, and endpoint
preflight. The manifest also owns one immutable strategy-level MicroRTS gameplay
contract shared by policy generation and strategy-facing roles. Experiment YAML files reference
`prompts/initial_generation.txt`; inline prompt/template fields are rejected.
The `static_0826` experiment references blank, Worker-rush, and deterministic
random seed policies in one three-candidate run. The
`static_0826_seed_variants` batch stores the same three initial-policy choices
as separate one-seed configs for independent `10 + 10` experiments. Each config
uses `inherited_genotype`, replicates its single policy and callable no-op Java
to ten generation-zero individuals, and performs ten independent Generator
calls. Python modules
only load, render, bound, transport, and validate executable prompt resources.
In the default mode one configured seed file creates one generation-zero
candidate. In inherited `configured_seeds` mode exactly one seed is required and
replicated to the configured population; the no-op source may also be selected
as the immutable Generator scaffold. In inherited `llm_generated_policies` mode
that one seed remains in slot one and policy-only LLM calls fill the other slots.
Empty-policy
candidates cannot enter Prompt Reflection. Normal evaluation does not call Function
Capability or Strategy Alignment or write their diagnostic files or timing.

The `0903_llm_initial_population` config uses the separately checked-in
`eagle/java_seeds/worker_rush/CandidateAgent.java`. It preserves one configured Worker Rush policy,
generates nine policy prompts through `initial_policy_generation.txt`, each with
a stable slot-specific strategy identity from `initial_policy_variants.txt`, then
generates Java independently for all ten policies with WorkerRush as inherited
context. Each generated policy call owns candidate-local request, raw
response, validation, retry, and timing evidence. Initial policy generation uses
the shared immutable MicroRTS gameplay contract, allowing strategically diverse
policies while limiting conditions, entities, and actions to the executable game
world.

## Reflection boundary

Reflection context construction remains shared, but each operator projects a
strictly scoped evidence view. Strategy Reflection consumes policy plus game
evidence and changes only policy. Prompt Reflection consumes policy plus Java
and optional source-matching validation/compiler diagnostics, then rewrites only
the code-generation prompt. Code Reflection receives the policy, selected parent
Java, immutable contracts, and the same class of source-matching diagnostics,
then directly returns corrected complete Java. Neither Prompt nor Code Reflection
receives game performance, opponent scores, W/D/L, match results, traces, logs,
aggregate fitness, or other gameplay evidence. Strategy-facing roles also receive the
immutable `microrts_gameplay_contract` as fixed domain context. It defines the
complete entities, production relations, legal actions, and observable state,
so a replacement may change strategy type without inventing non-game mechanics.
Strategy Reflection resolves evidence through recorded `strategy_parent_id`
and selects exactly one worst completed match: lowest finite numeric per-match
`performance`, with missing/non-finite values ranked by loss `-100`, draw `0`,
win `100`; ties use stable `match_id` order independent of seed, and failed
matches are excluded. Legacy positive `sample_count` and `sample_budget` values
remain accepted, but the effective selection count is one. One Commentator
diagnoses the selected match. The Coach receives the all-match global evaluation
summary plus exactly that diagnosis. An unavailable selected trace or exhausted
commentary retries follows the existing failure path and preserves the parent
policy without choosing another match. This does not add a fitness objective or
change AOS. Each Strategy Reflection candidate retains the exact parent strategy
prompt, the selected match and its parsed Commentator diagnosis, structured and
rendered Coach input, raw and parsed Coach output, normalized child strategy
prompt, and the strategy value passed to the Generator. Per-generation policy sidecars reference every population member's
canonical `genotype/policy_prompt.txt`, including candidates produced by other
operators; no policy text is duplicated in the sidecar.
Parent match traces remain available while all same-generation siblings are
created, then retired/discarded traces are removed only after atomic survivor
persistence. Commentator and Coach semantic failures participate in bounded
attempt retries; zero valid Commentator analyses preserves the parent policy.
Every role attempt has UTC boundaries in its candidate artifact and one compact
run timing event, without duplicating prompts/responses under `llm_logs/`.
Validated Coach results use the authoritative input parent policy; the model's
echo is retained only in raw/parsed evidence.

Coach and strategy-contract-rewriter output now prefers rule-per-line JSONL.
Every `strategy_rule` record carries one complete rule and the role-specific
child-policy field. Rules are validated independently and accepted in physical
line order; malformed lines and entire illegal rules are recorded and omitted.
Any non-empty legal subset becomes the canonical child policy, so the role
fails only when all proposed rules are unusable. The parser never prunes a
condition, action, or field inside a rule. A whole echoed parent policy does not
match the rule-record schema. Extraction evidence is persisted beside the
parsed output, while the prior whole-object/string-field format remains readable
with all-or-nothing validation.

Prompt Reviewer/Rewriter evidence is stored under `mutation/prompt_reflection/`.
The Reviewer sees only the editable strategy region plus the immutable API
guide, so fixed scaffold fields/helpers cannot be mistaken for reachable
candidate behavior. The Rewriter returns exactly `remove_rule_ids` and
policy-agnostic `add_rules`; each mutation adds exactly one compact rule and may
remove at most one existing rule. Runtime validates and deterministically
renders a bounded canonical generation prompt with stable derived rule IDs.
Concrete strategy/unit/Java instructions are rejected. A bounded retry receives
the exact prior validator error instead of blindly repeating the same request,
and legacy free-form prompts are not copied into the canonical rule set on
their next successful Prompt Rewrite.
The canonical generated Java phenotype is `phenotype/CandidateAgent.java`.
Default mode uses only the checked-in scaffold. In inherited mode the Generator
also receives `genotype/inherited_java.java`; Prompt Reflection reviews the
child's current policy against that exact Java component and records its Java
parent/artifact provenance. This explicit mode does not restore the removed
unversioned `previous_code` field.
Code Reflection stores a separate diagnosis request/raw response/parsed
conclusion, followed by the conclusion-guided Java revision request/raw
responses, parent source, and extracted reflected source under
`mutation/code_reflection/`. Its immutable context now explicitly lists every
available action/lookup interface and every available entity/unit. The parsed
conclusion separately reports strategy fidelity, code correctness. A revision call runs only when one of those dimensions requires a
correction; otherwise the parent Java is preserved with
ot_required` status.
Neither call receives the reusable generation prompt, W/D/L, matches, traces, or fitness;
only source-matching validation/compiler diagnostics are allowed. A complete
reflected source bypasses final Java generation and enters
validation/compilation directly; bounded compile repair remains available only
after a structurally complete source fails. A failed diagnosis or
unextractable revision preserves the selected parent Java.
The immutable API guide is rendered after the evolvable decoder gene, and
validation requires token-equivalent fixed scaffold source outside the strategy
markers. Fixed action helpers reject wrong-owner and invalid-type commands.
The production decoder now checks that each extracted response is a complete,
safe CandidateAgent envelope and then deterministically builds the normalized
source from the configured scaffold plus only the extracted strategy region.
Raw/extracted evidence still exposes model drift, while deletion of unused fixed
methods such as `applyAutoDefense` no longer consumes all compile-repair attempts
or produces a scaffold-only `-1000` failure.

The `workerrush` case compiles the vendored upstream
`third_party/microrts/src/ai/abstraction/WorkerRush.java`; it is a distinct
worker-rush implementation, not a LightRush subclass identity adapter.

Structured-output parsing keeps raw responses losslessly while normalizing only
known local-model shape variants into canonical artifacts: Commentator
`match_analysis/key_observations.time` and Reviewer textual correction arrays.
Semantic requirements, numeric tick evidence, classification, role boundaries,
and required fields remain hard failures.

## Verification

The required checks are:

```bash
python3 -m compileall eagle
python3 -m unittest discover -s tests
git diff --check
```

The test suite uses mocked generation/matches and does not constitute a full
MicroRTS evolutionary experiment.

## static_0824 repair ledger

This ledger records production stop/fix/restart cycles. A cycle is counted only
after an implementation change is followed by a fresh production restart. One
failed evolutionary candidate is normal; the run is stopped for a repeated
shared root cause, a broken pipeline/artifact contract, or no viable path to an
evaluated generation. The early Java-decoder health window is the first four
offspring, with at most one validation/compilation failure allowed.

If ten repair cycles complete without a healthy restart, cycle 11 must not be
started. The handoff must instead list each remaining root-cause hypothesis,
supporting and refuting evidence, solution options, architectural impact, cost,
and the smallest discriminating experiment.

The pre-cycle baseline, `runs/20260824_170942_291008`, was interrupted after
generation 15. It exposed duplicated generation-zero seeds, fabricated seed LLM
evidence, unnecessary blank-policy Alignment calls, sibling trace consumption,
zero-analysis Coach calls, and a 94/150 offspring compilation-failure rate. The
bootstrap and evidence fixes are recorded in commit `e187732b2c7`.

Cycle 1 used `runs/20260824_204255_208585`. Generation 0 correctly evaluated
one seed over 126 matches with no generation LLM attempt, and all ten
generation-1 Strategy Reflection children completed 10 Commentator analyses and
one Coach call with non-empty policies. The run was stopped during offspring 5
because three of the first four generated sources failed javac: an out-of-scope
`gameTime`, two helpers using undeclared `context`, and an `int[]` initialized
with nested coordinate pairs. The manifest is `interrupted`, and the server
process stopped. Follow-up inspection also found a stale dead-process ownership
record, null `opponent_id` in canonical per-match results, missing UTC/run-level
mutation-role timing, and untrusted Coach parent-policy echoes. These items are
the scope of cycle 2; the Strategy Reflection state transition itself passed its
real-run checks.

Cycle 2 preflight first replayed the same four representative policies through
the real Ministral decoder after the scope/type prompt hardening. Only one of
four compiled; the new failures were an undefined helper and general Java type
inconsistencies, while another source was rejected by deterministic API
validation. This ruled out continued special-case validation as a sufficient
solution. Cycle 2 therefore added bounded decoder sampling with
attempt-isolated source/classes and durable evidence. The global and legacy
default remains one; only the four tracked `static_0824` configs opt into five
attempts.

The cycle 2 bounded production smoke at
`/tmp/eagle-static0824-bounded-smoke-juhoh9` then exhausted all five samples for
each of the first two policies and was stopped during policy 3.
Repeated failures included undefined helpers, incompatible Java return/value
types, incorrect `pgs.free` calls, and fixed-scaffold violations. Cycle 3 keeps
attempt 1 as the authoritative two-gene decode and uses a separate
compile-guided decoder request after a complete source fails validation or
javac. That request contains the unchanged authoritative genes, immutable API
guide and scaffold, the immediately previous source marked untrusted, and only
its structured diagnostics. Extraction failures still resample the base
request. Each actual request has its own hash and evidence. This does not add a
third gene, mutate lineage/AOS state, alter selection, or retry Integration or
matches; it is also distinct from Code Reflection.

The cycle 3 real Ministral smoke at
`/tmp/eagle-static0824-guided-smoke-round3-hyr0_m36` replayed the same four
policies and passed 4/4 validation+javac. Policies 1 and 3 compiled on the
initial decode; policies 2 and 4 compiled on attempt 2 after the repair request
received the prior `PhysicalGameState.free` diagnostics. The bounded chain
stopped at each first success, retained per-attempt evidence, and the owned
model server stopped cleanly after the smoke. This clears the documented 3/4
gate for restarting the production batch.

Cycle 4 addresses the first restarted-batch runtime fault: candidate
`gen_0001_95374445025a` compiled after decoder repair but its strategy called
`GameState.free` with coordinates outside the real 8×8 map, producing
`ArrayIndexOutOfBoundsException` from `PhysicalGameState.getTerrain`. The fixed
offspring scaffold now exposes bounds-safe `isFreeCell(context, x, y)` and
guards `commandMove`/`commandBuild` against coordinates outside the active
`GameState`; reset and clone leave no active-state reference. The action guide
and deterministic strategy validator prohibit direct strategy-region
`GameState.free`/`PhysicalGameState.getTerrain` calls so their structured
validation failure can guide the existing decoder repair loop. Integration now
uses two populated 8×8 bases/workers maps plus independent one-argument agent
instances/states for both sides, action integrity, safe issuance, and one cycle.
It remains a terminal Integration boundary rather than a decoder retry path.

The cycle 4 real smoke at
`/tmp/eagle-static0824-runtime-smoke-round4-_3aftcth` replayed the production
runtime-failing policy plus the four earlier decoder policies. All 5/5 reached
validation+javac and the populated 8×8 two-instance/two-side Integration probe;
their selected attempts were 2, 2, 2, 3, and 4. The production-failing policy
was rejected at validation for unsafe direct map access, repaired on attempt 2,
and passed Integration. The owned model server and ownership record were
cleaned after the smoke, clearing the runtime restart gate.

Cycle 5 addresses a separate pinned-upstream opponent fault in restarted batch
`runs/20260824_233743_100100`: candidate `gen_0001_9215463a6e5d` reached
AllInBot on 24×24 map 3 as p0 (matches 66/68/70) and the upstream
`ai.abstraction.submissions.allibot.alli` crashed in
`WorkerRush -> Harvest.execute` because its target was null. This is not a
candidate phenotype fault. EAGLE now preflights that same pinned original class
and JAR hash, but compiles `eagle/opponent_adapters/SafeAllInBot.java` in a
dedicated adapter tree outside candidate source/class hashing and complexity.
The adapter reflection-loads the original delegate without a compile-time JAR
dependency, catches only recoverable `Exception` paths (including reflection
lookup/constructor failures), logs one
`EAGLE_SAFE_ALLINBOT_FALLBACK` marker, then permanently returns legal passive
actions. Reflection lookup failures are contained, while linkage and other
serious JVM errors are not swallowed.

Successful containment keeps the match and raw evidence, but canonical
`result.json`/trace metadata report `fault_scope=opponent`, contained/recovered
state, marker/reason, and `scoring_neutralized=true`. Its candidate score and
W/L/D contribution are a zero-score draw, never an accidental candidate win;
final-test JSON/CSV/Markdown count these upstream-contained matches separately.
The targeted real regression first reproduces the original 24×24 crash, then
proves wrapper completion, one-time marker persistence, and neutral scoring.

## Maintainability refactor (2026-10-02)

Operators now have separate owners under `eagle/operators`; fresh/resume share `eagle/evolution/generation.py`, with offspring planning and parent refresh separated. Generation and evaluation are subpackages of `eagle`; evaluation separates records, decoding, opponents, matches and pipeline orchestration. Offspring planning calculates generation-best evidence once per generation. See the [plan and verification](maintainability_refactor_plan.md) and [repository map](repository_map.md). Evolution/artifact protocols are unchanged.


## Historical two-endpoint phase dispatch (2026-10-15)

Phase barriers and switching below are superseded by dependency-driven execution.

The accepted runtime contract keeps one managed local primary for each model
phase and permits at most one ordered unmanaged OpenAI-compatible endpoint in
`additional_endpoints`. The resolved config retains the list and order, resume
treats both as immutable execution identity, canonical input index controls
slot assignment, and request logs/timing identify the endpoint and model that
actually served each request. All endpoints must pass chat preflight; the pool
fails closed and never performs request failover. Runtime ownership and GPU
offload proof apply only to the local primary.

Focused config, routing, concurrent transport, runtime propagation, and
all-endpoint preflight coverage passes. The configured LAN endpoint also passed
`/v1/models` and a bounded `/v1/chat/completions` request on 2026-10-15. This
documentation does not claim a completed live two-host overlap experiment; that
operational smoke remains before the runtime change is fully verified.


## Deterministic Java materialization (2026-10-14)

Dual materialization is implemented. `java_materialization_mode: llm` remains
the backward-compatible default. `deterministic_dsl` uses a policy-only active
genotype, disables Java-generation and repair LLM roles, and records protocol
`eagle-dsl-compiler-v1` plus compiler version `eagle-dsl-java-v1`. Compiler goldens, artifact/timing and resume contracts, real integration, and
the bounded self-play smoke pass. See `../testing/test_contracts.md` for recorded
commands, evidence, and the fixed-roster asset limitation.

## Groq framework and finite-slot evolution (2026-10-15)

The explicit two-stage `framework_slots` mode is implemented. The shared
framework bootstrap path supports bounded attempts, raw-before-parse evidence,
timing/hashes, and normalized bundle publication; Groq uses `GROQ_API_KEY` and
the Mistral experiment backend reads `api_key/mistral`. The Groq JSON Schema
request uses `strict: false`
because `report.slot_rationale` has dynamic keys. Provider enforcement is
best-effort; local exact validation remains authoritative. Its exact schema is
`eagle-framework-bundle-v1`; the generated report and
`slot_generation_prompt` remain audit/provenance inputs rather than candidate
genes.

Config resolution validates and exact-byte-hashes the bundle. Fresh runs freeze
it at `framework/bundle.json`; manifest/config, candidate schema v8, lineage 4.0,
materialization evidence, and resume readback enforce version/hash/genome/source
identity. Generation zero samples finite typed genomes. Offspring use seeded
per-slot crossover with exact slot provenance and at-most-one-slot local
mutation. `expression_choice` selects only a bundle-frozen Java expression.

The candidate-time path has no LLM runtime, policy/prompt genes, reflection,
source gate, or repair. It renders complete Java deterministically and reuses
the existing validation, javac, Integration, semantic-probe, and evaluation
pipeline without changing the 180-match fixed-roster matrix or objective and
selection formulas. The Groq bootstrap, framework core/config/artifact/integration,
and prompt-resource contracts pass in the project WSL venv (49 tests). No live
Groq request, full repository suite, or bounded Java/MicroRTS smoke was run.


## Framework Coach selection (2026-10-16)

`framework.evolution_mode: llm_coach` is implemented with strict complete-genome
JSON, frozen-bundle hash checks, candidate-owned raw attempts and role timing,
worst-match Commentator evidence, legal no-op handling, and mode-aware resume.
Seventeen focused Coach tests pass, including a complete one-generation mock
search and resume, failure sentinels, and artifact readback. A selected genome
also passed real javac and the seven-check two-side MicroRTS Integration probe.
No live provider bootstrap or full evolutionary experiment was launched.

Validation boundary: full unittest discovery completed 670 tests with one skip
before the concurrent multi-endpoint update was integrated. After resolving that
update's two overlapping conflicts, 142 focused endpoint, concurrency, LLM,
runtime, prompt, framework, Coach, and legacy Strategy tests passed, together
with compileall. Full discovery was not repeated after that integration.

## Inline framework startup (2026-10-16)

Fresh framework-slot runs accept `framework.design_brief` and optional bootstrap
`model`, then generate and freeze the framework inside run startup before EA.
Operators no longer need to create a separate bundle or execute the standalone
bootstrap command. Existing external bundles remain supported for controlled
reuse across seeds. Resume uses the frozen run bundle and checks brief, model,
and evolution-mode identity without another Groq request.

Failed startup retains bootstrap evidence, requested config, and a failed or
interrupted manifest without binding a folder-batch index slot. Mock mode
requires an existing bundle. Seven startup tests pass, including the complete
startup-to-EA handoff with the provider, runtime, and evaluation mocked.
The focused framework/Groq/Coach/batch regression suite passes all 90 tests.
Another 86 direct search/resume, reproducibility, initial-population, parent-
evaluation, and candidate-foundation tests pass. Compileall and diff checks pass. Full discovery was stopped after a prolonged
run without completion, so it is not reported as globally passing.
No live Groq framework generation was performed for this change.

## Rich checked-in framework control surface (2026-10-18)

The checked-in `fixed_worker_combat` framework now exposes 27 finite controls
instead of the previous two. The complete scaffold keeps the Java safety and
materialization boundary fixed while allowing EA to recombine resource
assignment, Barracks construction, worker expansion, production priority,
combat-unit choice, army size, attack timing, target ranking, focus fire,
rallying, fallbacks, and automatic defense. The default genome renders and
compiles successfully, passes the seven-check MicroRTS Integration probe, and
the focused framework/Coach/startup regression suite passes 57 tests.

## Exclusive framework Coach offspring route (2026-10-22)

The specified `llm_coach` extension adds optional
`framework.coach_offspring_probability` to select Coach or traditional
crossover/local-mutation offspring before crossover. `null` preserves legacy
Coach behavior; explicit numeric values are resume-fenced, with a missing field
in older manifests treated as `null`. Initial genomes remain Coach-selected,
and the traditional route retains the existing crossover and mutation rates.
The 50/50 experiment config retains population 10, 20 generations, seeds 8–13,
`crossover_rate: 0.75`, and `mutation_rate: 1.0`. Candidate artifacts retain
`framework_reproduction_route` for both branches. All 67 focused WSL tests pass,
including exclusive-route dispatch, preserved local crossover, candidate
persistence, a mixed one-generation mock search/resume, and resume-tamper
rejection; compileall and diff checks also pass. A broader regression batch was
interrupted during real MicroRTS matches and did not complete. No live Coach
experiment or full-suite validation was performed.
