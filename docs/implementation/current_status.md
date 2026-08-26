# Current implementation status

Snapshot: 2026-08-26. This file describes executable repository behavior.

## Active evolutionary contract

- `candidate_java_mode: generated_phenotype` preserves the two evolvable prompt
  components: `strategy_prompt` and `generation_prompt`; generated Java remains
  phenotype/evidence only. Opt-in `inherited_genotype` adds a complete Java
  component selected independently at crossover. The Generator revises that
  component, and a successful child phenotype becomes Java input for the next
  generation; this is explicit versioned state, not the removed legacy
  `previous_code` field.
- Automatically created candidate IDs use `gen_<zero-padded-generation>_<12-hex>`;
  explicitly loaded IDs remain unchanged for artifact and resume compatibility.
- The search roster is exactly seven fixed opponents: `lightrush`, `heavyrush`,
  `workerrush`, `allinbot`, `mayari`, `coac`, and `tma`. `PassiveAI`, `RandomAI`,
  and `RandomBiasedAI` remain available as definitions but are excluded from EA.
- Every candidate runs 126 matches: three maps × three rounds × both sides
  for each opponent.
- Match repetitions are identified by `round_index`. The obsolete
  `match_seeds` field, unread `eagle.match.seed` JVM property, and match-level
  seed artifacts are removed; MicroRTS matches do not claim seeded
  reproducibility.
- Candidate fitness is a seven-field opponent score mapping. Failed or
  incomplete candidates receive `-1000.0` for every case.
- Parent selection is seeded lexicase. Survivor selection repeatedly applies
  seeded lexicase without replacement to the joint parent-plus-offspring
  (`mu_plus_lambda`) pool until the fixed population is full; aggregate Game
  Performance and generation age are reporting-only.
- The reflection-operator controller supports exactly `static`, `aos_opponent`,
  and `aos_head2head`. Strategy/Code probabilities mean fixed probabilities in
  static mode and initial probabilities in AOS modes. Static performs no reward
  work. Opponent AOS restores execution-first seven-case W/D/L-rank change.
  Head-to-head AOS preserves the configured direct parent-A matrix and
  `(wins + 0.5 × draws) / valid matches`. Both adaptive modes share the alpha
  `0.20` EMA/probability-matching updater and configured minimum floor.
- The weighted aggregate Game Performance uses weights `1` for the three rush
  cases and `2` for AllInBot/Mayari/COAC/TMA, with denominator `11.0`, for
  reporting only.
- `code_quality` is a diagnostic and mutation-evidence signal, not an objective
  and not an AOS operator schedule.
- Previous-generation EAGLE self-play and dynamic opponent weights are absent
  from the active evaluation path.

## Active ownership

| Responsibility | Source |
| --- | --- |
| Fixed cases and reporting weights | `eagle/opponent_cases.py` |
| Candidate state and objective vector | `eagle/candidate.py` |
| Evaluation orchestration | `eagle/evaluation.py` |
| Match matrix | `evaluation/match_matrix.py` |
| Reflection selection, reward providers, shared AOS updater | `eagle/aos.py` |
| Head-to-head-only parent-vs-offspring evaluation | `evaluation/parent_offspring.py` |
| Match aggregation | `evaluation/game_metrics.py` |
| Objective construction | `evaluation/objectives.py` |
| Parent and survivor selection | `eagle/selection.py` |
| Evolution loop | `eagle/search.py`, `eagle/resume.py` |
| Experiment/model lifecycle | `eagle/experiment.py`, `eagle/runtime/processes.py` |
| Fully resolved experiment schema | `eagle/config.py`, run-local `config.yaml` |
| Per-opponent archive | `eagle/opponent_archive.py` |
| Run/generation artifacts | `eagle/run_artifacts.py`, `eagle/artifacts.py` |
| Offline analysis | `eagle/analysis/report.py` |

## Persisted per-generation evidence

Each `generations/generation_*.json` stores candidate IDs with seven-case
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
single-match distributions.

## Experiment lifecycle and run schema

`./experiment.sh CONFIG_TARGET [OPTIONS...]` translates its positional target
to Python `--config-dir`. Python discovers sorted top-level YAML files exactly
once, loads each exactly once, and invokes one batch owner that validates and starts the configured llama.cpp model,
waits for health, runs search and the production final test, and stops only its
owned process. Folder batches start an identical resolved runtime once and reuse
it directly for later configs using every launch-critical field; a changed runtime profile is stopped and replaced. Mock mode never constructs the runtime manager or inspects a port. Runtime state records PID plus process start time, exact executable/command, launcher, owner token, and resolved spec; foreign port owners are never killed.
Separate runtime/run compatibility commands are not part of production. The
dispatcher exposes only `experiment` and `analyze`.

Directory batches also maintain an atomic `experiment.yaml` index in the
selected config directory. Each entry maps the config filename to its absolute
run folder at run-creation time; the generated index is excluded from later
config discovery. A legacy `experiment-v2` config with that filename is
preserved rather than replaced.

`./experiment.sh --resume CONFIG_FOLDER` reads that index as a batch checkpoint.
Indexed entries with incomplete search or missing required final-test output are
prioritized and resumed, fully completed entries are skipped, and remaining
unindexed configs run fresh in filename order. Direct `--resume RUN_DIR` remains
the single-run interface. Search-complete/final-test-only recovery does not start
llama.cpp unless a later config still needs LLM work.

New `eagle-run-v2` runs persist one fully resolved `config.yaml`. The root has
only manifest/config/summary/timing plus canonical directories. Candidate,
generation, match, archive, and config compatibility duplicates have been
removed. Analysis and resume both require v2 and use the run-local model and
experiment definition.

## Prompt ownership

All executable prompt bodies live under `prompts/`, with exactly one UTF-8
`.txt` file per prompt. `prompts/manifest.toml` stores only prompt metadata and
placeholder contracts. This includes the reusable generation prompt, Code
Reflection, the library Strategy Reflection/Rewrite
path, Match Commentator, all four Coach intents, generation, Strategy Alignment,
the compile-guided Java repair decoder, the action-API guide, and endpoint
preflight. Experiment YAML files reference
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
candidate. In inherited mode exactly one seed is required and replicated to the
configured population; the no-op source may also be selected as the immutable
Generator scaffold. Empty-policy
candidates cannot enter Code Reflection, and Strategy Alignment is not
applicable to them.

## Reflection boundary

Reflection context construction remains shared, but each operator projects a
strictly scoped evidence view. Strategy Reflection consumes policy plus game
evidence and changes only policy. Code Reflection consumes policy plus Java and
optional structural/compiler diagnostics, then rewrites only the code-generation
prompt; it receives no raw game logs. Strategy Reflection samples up to 10 matches with opponent/map-aware
coverage, calls one Commentator per selected log, and gives the Coach a
deterministic all-match global summary. Coverage and fully-beaten diagnostics are
stored under `mutation/strategy_reflection/`; this does not add a fitness objective
or change AOS. Each Strategy Reflection candidate also retains the exact parent
strategy prompt, selected matches in Commentator call order, individual parsed
Commentator results, structured and rendered Coach input, raw and parsed Coach
output, normalized child strategy prompt, and the strategy value passed to the
Generator. Per-generation policy sidecars reference every population member's
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

Code Reviewer/Rewriter evidence is stored under `mutation/code_reflection/`.
The Rewriter uses the exact JSON object contract with the sole field
`rewritten_prompt`.
The canonical generated Java phenotype is `phenotype/CandidateAgent.java`.
Default mode uses only the checked-in scaffold. In inherited mode the Generator
also receives `genotype/inherited_java.java`; Code Reflection reviews the
child's current policy against that exact Java component and records its Java
parent/artifact provenance. This explicit mode does not restore the removed
unversioned `previous_code` field.
The immutable API guide is rendered after the evolvable decoder gene, and
validation requires token-equivalent fixed scaffold source outside the strategy
markers. Fixed action helpers reject wrong-owner and invalid-type commands.

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
