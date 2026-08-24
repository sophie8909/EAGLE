# EAGLE architecture specification

Status: authoritative current contract, 2026-08-19.

This document describes executable EAGLE behavior. Historical NSGA-II,
two-objective, ten-opponent, split-runtime, inline-prompt, and `eagle-run-v1`
contracts are intentionally absent; Git history is the archive for those designs.

## 1. System boundary

EAGLE evolves prompt-defined Java MicroRTS agents offline. An LLM may generate or
reflect on candidates before evaluation, but a running match never calls an LLM.
Each phenotype is one complete `ai.generated.CandidateAgent` Java source file.

EAGLE does not evolve patches, fixed method bodies, runtime LLM policies,
surrogate fitness models, or previous-generation self-play opponents.

## 2. Candidate model

The genotype has exactly two evolving prompt values:

1. `strategy_prompt` — the game-playing policy gene (`policy_prompt` conceptually)
2. `generation_prompt` — the reusable policy-to-Java translation gene (`code_generation_prompt` conceptually)

The phenotype is the latest complete generated Java source. Java source is
evidence, never an inherited genotype component. Child construction inherits
only the two prompt genes; evaluation does not overwrite either gene.

First-class candidate state includes identity, generation, direct parents,
operator, mutation type, component-source IDs, generated Java, validation and
compile status, seven-case fitness, diagnostics, failure state, artifact
references, and timing.

New candidate identities are generation-qualified as
`gen_<zero-padded-generation>_<random-suffix>` so run artifacts remain unique
and easy to navigate. Persisted IDs are opaque references and are never renamed
while loading or resuming a run.

## 3. Evolution lifecycle

Generation zero creates one candidate per configured seed policy file, pairs
each blank policy with the checked-in Java seed without calling the Generator,
and passes each seed through the canonical downstream evaluation boundary. It
does not replicate a seed merely to fill `population_size`. Each later
generation produces a fixed-size offspring population and performs:

1. seeded lexicase parent selection;
2. optional uniform two-component crossover;
3. optional Strategy or Code mutation;
4. final complete-file Java generation;
5. validation, compilation, integration, and evaluation;
6. optional AOS reward collection;
7. seeded lexicase survivor selection;
8. atomic generation persistence.

The fixed-size survivor population is selected from evaluated offspring, with
parent fallback only when the offspring set is insufficient.

## 4. Reproducibility

`random_seed` controls EA randomness, lexicase case ordering, operator choice,
crossover choices, and deterministic reflection sampling. Match repetitions are
identified by `round_index`; EAGLE does not claim seeded MicroRTS match
reproducibility and does not pass a match-seed JVM property.

## 5. Crossover and lineage

Uniform crossover independently selects `strategy_prompt` and
`generation_prompt` from the two parents. Lineage persists the direct parent IDs
and the source candidate ID for both prompt components, even when selected text
values are equal. It records no phenotype-parent component.

## 6. Mutation

The reflection operator is chosen by exactly one configured mode:

- `static`: fixed Strategy/Code probabilities and no reward work;
- `aos_opponent`: execution-first seven-case rank-change reward;
- `aos_head2head`: configured parent-A versus offspring match matrix reward.

Both adaptive modes use the same alpha-`0.20` EMA and probability-matching
updater with the configured minimum probability floor. AOS never changes the
seven-case lexicase fitness.

Strategy mutation performs Match Commentator sampling, Coach reflection, and a
Strategy Prompt rewrite before final Java generation. It changes only
`strategy_prompt`.
Commentator and Coach transport, parsing, and semantic validation use one
bounded attempt budget. Each attempt retains UTC boundaries and one run timing
event without duplicating candidate-owned prompt/response evidence. A validated
Coach result takes its parent policy from the authoritative input; any model
echo remains raw/parsed evidence only.

Code mutation compares the current policy with the current Java phenotype, then
performs Code Generation Prompt Rewrite before final Java generation. It changes
only `generation_prompt`; game logs are not Code Reflection evidence. The Code
Prompt Rewriter returns exactly `{"rewritten_prompt":"..."}` so the transport's
JSON-object mode and the parser enforce the same contract.

All executable prompt bodies live as individual UTF-8 text files under
`prompts/`. Python and YAML may reference, render, bound, transport, and validate
prompt resources but may not contain alternate executable prompt bodies.

## 7. Java generation and validation

Generation 0 is the one explicit decoder exception: every seed candidate has a
blank `strategy_prompt` and uses `initial_java_seed_path` as its fixed phenotype,
without an LLM call. The checked-in seed is validated, compiled, integrated, and
evaluated through the same downstream boundary as every generated phenotype. It
is generation-zero evidence only and is never inherited as a third gene. Seed
loading records checked-in source provenance but no generation request, raw LLM
response, or LLM attempt.
The seed file is distinct from the checked-in offspring scaffold, so decoder
safety hardening cannot silently change the historical seed source or hash.

Final generation consumes the two prompt genes plus the fixed checked-in Java
scaffold/API constraints and returns exactly one complete Java source file. It
does not receive parent Java or game logs. Raw response, extracted source, normalized source,
attempts, model identity, errors, and timing are persisted.

Offspring decoding may use up to `generation_max_attempts`. Attempt 1 consumes
the authoritative two-gene generation request. An extraction failure may repeat
that base request. After a complete source fails validation or compilation, the
next attempt consumes the separate compile-repair prompt containing the unchanged
authoritative genes, immutable scaffold/API guide, the immediately previous
complete source as untrusted phenotype evidence, and only that attempt's
structured validation/compiler diagnostics. Compile repair changes no gene,
lineage, AOS state, selection case, or strategy intent and is distinct from Code
Reflection. Each actual request and source owns its hash and evidence. The first
validation+compilation success is the sole canonical phenotype. If all attempts
fail, the final attempt owns the candidate failure classification and remains
generation evidence rather than a canonical phenotype. Generation zero loads
once regardless of this setting.

Validation requires:

- package `ai.generated`;
- public final class `CandidateAgent`;
- superclass `AbstractionLayerAI`;
- required one- and two-argument constructors;
- `getAction`, `reset`, and `clone` contracts;
- token-equivalent checked-in source outside the single editable strategy
  region;
- strategy-helper scope and array-shape constraints, including an explicit
  `AgentContext context` parameter for every helper that reads `context`, local
  or parameter ownership for `gameTime`, and `int[][]` for nested coordinate
  pairs; direct strategy-region `GameState.free(...)` and
  `PhysicalGameState.getTerrain(...)` reads are rejected in favor of the fixed
  bounds-safe `isFreeCell(context, x, y)` helper;
- no network, process execution, unauthorized file I/O, runtime modification,
  or unavailable dependencies.

Internal helper names and implementation inside the editable strategy region
remain flexible within those deterministic Java/API constraints.

## 8. Compilation and integration

Each decoder-attempt Java source that passes validation is compiled at
most once in an attempt-isolated class directory with the MicroRTS classpath and
`-Xlint:all`. Structured, deduplicated errors and warnings are persisted. The
first successful class tree is promoted without recompilation and is the only
tree visible to Integration. Integration or runtime failure does not trigger a
new decoder attempt.

Before matches, the standalone integration probe performs seven ordered checks:
class loading, AI inheritance, constructors, reset, clone, getAction, and valid
PlayerAction. The `getAction`/`PlayerAction` checks load the populated real
8×8 bases/workers map into independent states, exercise both candidate sides
with independent one-argument instances, and verify action integrity, safe
issuance, and one cycle. A failed prerequisite blocks later checks and prevents
matches. Integration failure does not re-enter the decoder.

`evaluation/microrts_runner.py` owns only this integration probe.
`evaluation/runtime_evaluation.py` is the sole match-execution owner.

## 9. Evolution evaluation

The fixed search roster is:

1. LightRush
2. HeavyRush
3. WorkerRush
4. AllInBot
5. Mayari
6. COAC
7. TMA

Every runnable candidate uses the same source and compiled classes for 126
matches: seven opponents × three maps × three rounds × two player sides.

Fitness is a maximized mapping with exactly the seven opponent IDs. Failed or
incomplete candidates receive `-1000.0` for every case. Aggregate Game
Performance is reporting-only, using weights `1` for the three rush opponents
and `2` for AllInBot, Mayari, COAC, and TMA.

Code Quality is a diagnostic and mutation-evidence signal, not a selection
objective. Successful Code Quality is:

`100 - (40C + 25N + 20L + 15F)`

where the terms are normalized cyclomatic complexity, nesting, logical LOC, and
longest-function LOC. Failure Code Quality is `-1000.0`. Compiler diagnostics,
Function Capability, and Strategy Alignment are persisted diagnostics only.
Strategy Alignment is not applicable to an empty policy prompt and is persisted
as skipped with a null score and no LLM attempt.

## 10. Match evidence

Each match owns one directory and one compressed tick stream:
`match_trace.jsonl.gz`. The trace contains structured state, source tick text,
fallback result evidence when no round-state file exists, metadata, result, and
an integrity report. Strategy Reflection consumes this same trace. A second
`match_log.jsonl.gz` format is prohibited.

Compact mode may remove replay and raw round-state files after canonical
telemetry and trace persistence. Parent traces remain available until every
same-generation sibling has been constructed. Only after atomic survivor
persistence may traces for retired parents and discarded offspring be removed;
survivor traces remain available to the next generation.

## 11. Run schema

New and supported runs use only `eagle-run-v2`:

- `manifest.json`
- fully resolved `config.yaml`
- `timing.jsonl`
- `summary.json`
- `generations/`
- `candidates/`
- `generated_agents/`
- `classes/`
- `archives/`
- `llm_logs/`
- `final_test/`

Generation files contain compact candidate references, metrics, AOS state, and
timing references. Each generation also has a policy JSONL sidecar containing
artifact references for every population member with a non-empty
`strategy_prompt`; it does not duplicate strategy text. Candidate state lives once under
`candidates/<id>/candidate.json`, with `genotype/policy_prompt.txt`,
`genotype/code_generation_prompt.txt`, `phenotype/CandidateAgent.java`, and
specialized generation, validation, compilation, integration, evaluation,
mutation, lineage, and timing artifacts beside it.

Strategy Reflection candidates additionally retain under
`mutation/strategy_reflection/` the exact parent strategy
prompt, ordered selected-match records, each parsed Commentator response, the
structured and rendered Coach input, raw and parsed Coach output, the normalized
child strategy prompt, and the strategy value supplied to Generator. These are
observability artifacts only and do not introduce a separate policy state.

`resolved_config.json`, `generation_metrics.jsonl`, `final_population.json`,
root `errors.jsonl`, duplicate match results, and `eagle-run-v1` readers are not
supported.

## 12. Experiment lifecycle

The production entrypoint is:

```bash
./experiment.sh CONFIG_FOLDER_OR_YAML [--mock] [--skip-final-test]
./experiment.sh --resume RUN_DIR_OR_CONFIG_FOLDER [--mock] [--skip-final-test]
```

It delegates to `python -m eagle experiment`. Python owns sorted config
discovery, model validation, llama.cpp start/reuse/switch/health checks, search,
resume, final test, and owned-process cleanup. An occupied foreign endpoint is
never adopted or killed. Mock mode does not construct a runtime manager.

For a directory batch, the selected config directory owns `experiment.yaml`, an
atomically updated mapping from each config filename to its absolute run folder.
The index is updated as soon as a run is created, is excluded from config
discovery, and therefore preserves resumable partial runs. A pre-existing
`experiment.yaml` with `schema_version: experiment-v2` remains a config and is
never overwritten by the index writer.

When `--resume` targets such a config directory, Python reads the existing
index instead of resetting it. Indexed runs that have not completed their
required lifecycle are processed first: interrupted/failed search resumes from
its latest atomic generation, while a search-complete run without a required
final-test summary resumes at final testing. Fully completed indexed configs
are skipped. The remaining unindexed configs then start as fresh runs in
filename order, with every new run added atomically to the same index. A direct
run-directory target retains the single-run resume behavior. If interruption
occurred before generation 0 was atomically recorded, folder resume starts a
replacement run for that config and updates the index because no resumable
population exists.

`python -m eagle analyze` and `analyze.sh` are the only offline analysis
entrypoints. Separate `run`, `runtime`, `run.sh`, and `run_env.sh` compatibility
surfaces are prohibited.

## 13. Verification

Behavior changes require focused contract tests followed by:

```bash
python3 -m compileall eagle evaluation generation
python3 -m unittest discover -s tests
git diff --check
```

A bounded real Java/MicroRTS integration probe may supplement unit tests. A full
evolutionary experiment is never required for repository validation unless the
operator explicitly requests it.
