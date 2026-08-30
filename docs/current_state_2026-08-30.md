# EAGLE Current State — 2026-08-30

This is a repository-grounded audit of **EAGLE: Evolutionary Algorithm for
Game-playing with LLM-Enabled Agents**. It does not describe GEPA, ACE, MIPRO,
CAPO, or generic context optimization.

Audit baseline: local `master` at `af2c9f5d583` plus the working-tree experiment
configuration and run indexes visible on 2026-08-30. Source code is treated as
authoritative. Run artifacts are authoritative for what a historical run did,
but not for what current source would do. The run manifests do not persist a Git
commit, so source-revision claims about old runs are limited to differences that
can be established from their artifact schemas, timestamps, and Git history.

## 1. Executive Summary

| Question | Repository-grounded answer |
|---|---|
| 1. What exactly is EAGLE evolving now? | The default mode evolves two text genes: `strategy_prompt` and `generation_prompt`. The newest local experiments opt into `candidate_java_mode: inherited_genotype`, which adds a third complete-Java genotype component, `inherited_java`. Crossover independently chooses the source parent for each component. |
| 2. What exactly is the phenotype? | The complete generated, validated, compiled, and evaluated `CandidateAgent.java`. Inherited Java is an input genotype component in the opt-in mode; it is not the newly generated phenotype. |
| 3. What mutation/reflection operators are active? | Current source has **Strategy Reflection**, **Code Reflection**, and **Balance Reflection**. The active 0829 config assigns probabilities `0.20 / 0.20 / 0.60`. Balance Reflection is therefore the dominant operator in the newest run and changes both prompt genes atomically. |
| 4. What selection algorithm is active? | Exact opponent-wise lexicase for every parent request and for `(mu + lambda)` survivors. It has seven cases, random case order, no epsilon, exact-score filtering, random residual tie breaking, and survivor selection without replacement. NSGA-II, tournament, and uniform-random selection are not active. |
| 5. How is game performance represented? | Each of seven opponent cases is the arithmetic mean of 18 shaped match scores (3 maps × 3 rounds × 2 sides). The seven values are the fitness representation. A weighted scalar is reporting-only. Code quality is diagnostic-only. |
| 6. Is AOS changing operator behavior? | It can in source, but no locally preserved current run uses an adaptive mode: every inspected run records `static`, zero operator rewards, and unchanged probabilities. Thus there is no local empirical evidence that AOS has changed probabilities. |
| 7. Are Game and Code Reflection behaviorally distinct? | **Yes.** Strategy Reflection changes only policy; Code Reflection changes only code-generation instructions; both regenerate Java afterward. Code Reflection now reviews only the editable strategy region and rewrites a deterministic policy-agnostic rule set, preventing the fixed-scaffold misdiagnosis observed in the historical 0829 run. |
| 8. Do policies show meaningful strategy diversity? | Some do: worker rush, worker-first macro, early barracks/mixed-unit pressure, defensive/reactive, and harassment policies are distinguishable. However late populations often collapse to a few policy hashes, many policies are variations on worker/economy timing, and the newest Balance run contains impossible MicroRTS concepts. Text diversity therefore overstates executable strategic diversity. |
| 9. Why do recent agents fail strong opponents? | The strongest evidence is a combination of weak/invalid phenotype strategies, severe seed dependence, semantically ungrounded reflection, deterministic and often low-information match repetition, and specialist-preserving lexicase pressure. Corrected blank-seed runs won zero games against the seven search opponents in final test; a worker-rush seed recovered wins against rush opponents but still went 0/60 against Mayari and TMA. |
| 10. What is the most important next verification? | Run a paired, single-parent Strategy-vs-Code lineage assay and inspect the exact generator request and resulting Java behavior. It directly tests whether each gene delta reaches and meaningfully changes the phenotype before selection can confound the result. |

The most important current finding is that **the current experimental system is
not merely the intended two-gene/two-operator design**. The 0829 experiment uses
a three-component inherited genotype and spends 60% of mutation choices on
Balance Reflection, which changes both prompt genes. A representative Balance
lineage changed a valid worker-rush policy into a policy requiring unsupported
Walls, Doors, Armories, Guards, Siege Units, and “Mayari tech”; its Java maps
those ideas onto Barracks and also uses incorrect map-size tests. The pipeline
compiles such code but does not validate semantic feasibility.

```text
Implementation:
eagle/candidate.py::Candidate
eagle/crossover.py::crossover()
eagle/search_runtime.py::build_search_runtime()
eagle/rewrite.py::BalanceReflectionMutation

Config:
configs/experiments/0829_3_reflection/
  ministral3_8b_static_0.2_0.2_0.6_worker_rush.yaml

Observed behavior:
runs/20260829_221010_299914/candidates/
  gen_0009_575da8baea59/genotype/policy_prompt.txt
runs/20260829_221010_299914/candidates/
  gen_0017_a6a08dfd4931/phenotype/CandidateAgent.java
```

## 2. Current Architecture

### End-to-end lifecycle

`experiment.sh` changes to the repository root and invokes
`python -m eagle experiment` inside the `eagle` Conda environment. A config
folder is processed in sorted order; a generated `experiment.yaml` maps each
config name to its run directory. Production runs start/reuse the configured
llama.cpp server, run search, then automatically run the final test unless
`--skip-final-test` was supplied.

```text
Implementation:
experiment.sh
eagle/experiment.py::ExperimentOrchestrator.run()
eagle/experiment.py::resolve_experiment_configs()
```

The current pipeline is:

```text
seed prompt(s) + generation prompt [+ initial Java component]
    ↓ initialize_population()
generation-0 Java seed or Generator call
    ↓ validation → javac → integration
126 MicroRTS search matches
    ↓ 18-match mean per opponent
seven opponent fitness cases
    ↓ lexicase parent selection
component-wise crossover/copy
    ↓ static or adaptive mutation-operator choice
Strategy Reflection OR Code Reflection OR Balance Reflection
    ↓ new genotype
Generator (with bounded repair attempts)
    ↓ new CandidateAgent.java phenotype
validation → javac → integration → 126 matches → seven cases
    ↓ optional AOS credit
(mu + lambda) opponent-wise lexicase survivors
    ↓ repeat generations
reporting-best member of final population
    ↓ 600-match final test
```

### Stage contract

| Stage | Input | Output | Responsible source | Persistent artifacts | LLM / role |
|---|---|---|---|---|---|
| Config/runtime | YAML or folder | Validated resolved config and model server | `eagle/config.py::ExperimentConfig`; `eagle/experiment.py`; `eagle/runtime/` | `runs/<id>/config.yaml`, `manifest.json`, batch `experiment.yaml` | Endpoint preflight only |
| Initialization | Seed policy files, generation prompt, mode, optional Java seed | Generation-0 candidate genotype(s) | `eagle/search.py::initialize_population()` | Candidate genotype and lineage after evaluation | Default mode uses no Generator for gen0; inherited mode does |
| Parent selection | Current population and seven fitness cases | Two selected parents | `eagle/selection.py::select_parent()` | Component parent IDs in lineage/crossover provenance | No |
| Crossover/copy | Two parents | Unevaluated child genotype | `eagle/crossover.py::crossover()`; `eagle/search.py::create_offspring()` | `lineage.json`, `crossover/provenance.json` | No |
| Operator selection | Mode probabilities/credits and eligible operators | Strategy, code, or balance operator ID | `eagle/aos.py` controller classes | Generation AOS record; per-child AOS metadata/reward | No |
| Strategy mutation | Evaluated strategy parent, 126 results and selected traces, child policy gene | Revised policy; other genes preserved | `eagle/strategy_reflection.py::StrategyReflectionPipeline` | `mutation/strategy_reflection/` | Commentator once per selected trace, then Coach |
| Code mutation | Current policy, selected/inherited Java, diagnostics, current generation prompt | Revised generation prompt; policy preserved | `eagle/reflection_prompts.py::build_code_reflection_prompt_bundle()`; `eagle/rewrite.py::PromptRewriteMutation` | `mutation/code_reflection/` | Alignment Reviewer, then code-prompt Rewriter |
| Balance mutation | Opponent × map × side W/D/L table and both prompt genes | Both prompts revised atomically | `eagle/reflection_prompts.py::build_balance_reflection_prompt_bundle()`; `eagle/rewrite.py::BalanceReflectionMutation` | `mutation/balance_reflection/` | Balance reflector, strategy rewriter, code rewriter |
| Java generation | Active genotype, immutable API guide and scaffold | Complete Java attempt(s) | `eagle/candidate.py::generation_input()`; `generation/java_agent_generator.py`; `eagle/evaluation.py::decode_validate_compile_candidate()` | `generation/`, `validation/`, `compilation/`; successful `phenotype/CandidateAgent.java` | Generator; later attempts may be compile-repair calls |
| Integration | Compiled candidate | Seven contract-check results | `evaluation/microrts_runner.py::integrate_microrts_agent()` | `integration/` | No |
| Search evaluation | Same compiled phenotype, seven opponents, maps/rounds/sides | 126 results and seven opponent means | `eagle/evaluation.py::evaluate_candidate()`; `evaluation/runtime_evaluation.py`; `evaluation/game_metrics.py` | `matches/`, `evaluation/game_performance.json`, `evaluation/objectives.json` | Strategy Alignment diagnostic only, when policy is nonblank |
| AOS reward | Evaluated child and recorded comparison parent | Operator reward and updated global probabilities | `eagle/aos.py`; `evaluation/parent_offspring.py` | `aos/reward.json`, generation AOS state | No |
| Survivor selection | Current parents + evaluated offspring | Fixed-size next population | `eagle/selection.py::select_next_generation()` | `generations/generation_NNNN.json` | No |
| Final test | Final selected runnable candidate | 600 W/L/D/error results | `eagle/final_test.py`; invoked by `eagle/experiment.py` | `final_test/final_test_summary.json`, CSV and matches | No |

Generation zero differs by genotype mode. In `generated_phenotype`, one candidate
is created per seed file and the fixed `initial_java_seed_path` supplies the
phenotype without a Generator call. In `inherited_genotype`, exactly one seed
policy is replicated to `population_size`, the same Java seed is placed in each
genotype, and each replicate makes an independent Generator call. Later
generations always use the Generator.

```text
Implementation:
eagle/search.py::_run_search_impl()
eagle/search.py::initialize_population()
eagle/evaluation.py::decode_validate_compile_candidate()
```

Generation has up to `generation_max_attempts`. Attempt one uses the active
genotype. Extraction/validation failures retry from the same genotype request;
compile failures can invoke a repair prompt using the failed source and compiler
diagnostics. Evaluation asserts that generation did not mutate the stored
genotype. A repair can nevertheless alter the phenotype strategy region, subject
to scaffold preservation and a token-similarity delta guard; it is not recorded
as an evolutionary gene mutation.

## 3. Genotype and Phenotype

### Actual representation

`Candidate` stores:

- `strategy_prompt`: the policy/strategic-intent text;
- `generation_prompt`: reusable policy-to-Java instructions;
- `inherited_java`: an optional complete Java genotype component;
- `generated_java`: the new phenotype;
- `strategy_parent_id`, `generation_prompt_parent_id`, optional
  `java_parent_id`, and `parent_ids` for lineage.

```text
Implementation:
eagle/candidate.py::Candidate
eagle/candidate.py::Candidate.generation_input()
eagle/candidate.py::Candidate.lineage_to_json_dict()
eagle/crossover.py::crossover()
```

The conceptual equation is therefore exact only in default mode:

```text
generated_phenotype mode:
genotype = policy + code-generation instructions
phenotype = generated CandidateAgent.java
```

For the newest experiments it is incomplete:

```text
inherited_genotype mode:
genotype = policy + code-generation instructions + inherited complete Java
phenotype = newly generated CandidateAgent.java
```

Crossover selects the policy parent and generation-prompt parent independently;
in inherited mode it independently selects a Java parent as well. The child does
not initially carry a generated phenotype. The generator request includes both
prompt genes, the immutable action/API guide, the canonical scaffold, and—when
present—the complete inherited Java component. Neither prompt is reconstructed
or discarded during normal generation.

### Mutation independence

- Strategy Reflection asserts `generation_prompt` is unchanged.
- Code Reflection asserts `strategy_prompt` is unchanged.
- Balance Reflection intentionally changes both, and applies neither if either
  rewrite stage fails.
- Java crossover is independent of both prompt-parent choices in inherited mode.

Artifact hash checks confirm the primary separation in real runs:

| Run | Strategy mutations: policy changed / generation prompt preserved | Code mutations: policy preserved / generation prompt changed | Balance mutations: both changed |
|---|---:|---:|---:|
| `20260825_003735_743397` | 41/41; 41/41 | 125/125; 118/125 | n/a |
| `20260825_130915_559782` | 71/71; 71/71 | 91/91; 91/91 | n/a |
| `20260829_221010_299914` through gen18 | 39/39; 39/39 | 25/25; 24/25 | 58/87 |

Counts below the mutation total mean the reflection/rewrite failed or produced no
gene delta; current failure paths retain the original genes even though the
selected `mutation_type` remains inspectable.

### Persistence and lineage

Current candidates persist policy and code-generation prompts at
`genotype/policy_prompt.txt` and `genotype/code_generation_prompt.txt`, optional
Java at `genotype/inherited_java.java`, the successful phenotype at
`phenotype/CandidateAgent.java`, and component provenance at `lineage.json`.
`candidate.json` contains compact references and objective data. Generation
snapshots reference candidate IDs rather than duplicating bodies. This is enough
to recover parent → child and component-source lineage in current artifacts.

```text
Implementation:
eagle/artifacts.py::write_candidate_inputs()
eagle/artifacts.py::write_candidate_snapshot()
eagle/run_artifacts.py::record_generation()

Current schemas:
eagle-candidate-v5
lineage schema 3.0
```

The 2026-08-20 run predates this contract. Its genotype path contains
`strategy_prompt.txt`, `generation_prompt.txt`, and `previous_code.java`; the
phenotype is under `generation/normalized_candidate.java`, and its IDs are old
12-hex IDs. Current writers never emit `previous_code`. Current loaders keep
isolated compatibility reads but discard the old implicit Java gene.

## 4. Evaluation and Fitness

### Search matrix

The fixed search roster and lexicase order are:

1. LightRush (`lightrush`, weight 1)
2. HeavyRush (`heavyrush`, weight 1)
3. WorkerRush (`workerrush`, weight 1)
4. AllInBot (`allinbot`, weight 2)
5. Mayari (`mayari`, weight 2)
6. COAC (`coac`, weight 2)
7. TMA (`tma`, weight 2)

Every runnable candidate plays each opponent on
`basesWorkers8x8.xml`, `basesWorkers16x16.xml`, and
`basesWorkers24x24.xml`, for three rounds and both candidate sides:

```text
18 matches/opponent = 3 maps × 3 rounds × 2 sides
126 matches/candidate = 7 opponents × 18
```

The match matrix is deterministic and opponent-major, then map-major,
round-major, with p0 then p1. No per-match random seed is passed. Identical
deterministic agents and starting states can therefore make the three nominal
rounds redundant; the repository does not establish that every external
opponent is deterministic.

```text
Implementation:
eagle/opponents.py::SEARCH_OPPONENT_REGISTRY
eagle/opponent_cases.py::LEXICASE_CASES
evaluation/match_matrix.py::build_match_matrix()
eagle/config.py::ExperimentConfig.validate()
evaluation/runtime_evaluation.py::run_microrts_match()
```

PassiveAI, RandomAI, and RandomBiasedAI remain defined but are excluded from the
search roster. They appear only in the expanded final test and GUI/compatibility
paths. They cannot inflate evolutionary fitness.

WorkerRush needs a historical warning. Commit `e31c94ad067` on 2026-08-24
replaced the earlier compatibility class that merely extended LightRush with a
vendored distinct WorkerRush implementation. Consequently, results from
`20260820_020955_479858` labelled WorkerRush were effectively a second
LightRush case, while the corrected 0824 and later runs use distinct WorkerRush.

### Match formula

For a candidate-side match:

```text
result_score = +100 win, 0 draw, -100 loss
material = 5 × tanh(mean_t(player material - enemy material) / 10)
resources = 3 × tanh((final player resources - final enemy resources) / 10)
survival = 2 × end_tick/max_tick                     on a loss
         = 2 × (1 - end_tick/max_tick)               on a win
         = 0                                         on a draw
shaping = clamp(material + resources + survival, -10, +10)
match_score = result_score + shaping
```

Material values are Base 10, Barracks 5, Worker 1, Light 2, Heavy 4, Ranged 2,
and Resource 0. Thus shaping cannot flip the W/D/L ordering: wins are 90–110,
draws -10–10, losses -110–-90.

```text
Implementation:
evaluation/game_performance.py::compute_performance_breakdown()
evaluation/game_performance.py::GamePerformanceConfig
Config defaults: eagle/config.py::ExperimentConfig
```

Each opponent fitness value is the arithmetic mean of its 18 match scores. If
even one expected match is missing, that opponent score is `-1000`; at the
candidate boundary any generation, validation, compilation, integration, or
runtime failure causes **all seven evolutionary objectives** to be `-1000`.
Per-map and per-side means, W/L/D counts, final resources, units, and dispersion
are saved diagnostics but are not separate selection cases.

The reporting scalar is:

```text
GP = (LR + HR + WR + 2·AllIn + 2·Mayari + 2·COAC + 2·TMA) / 11
```

Weights affect reporting only. `best_candidate()` uses this scalar only to pick
a convenient representative from the final surviving population.

### Code quality and failures

Successful code quality is diagnostic-only:

```text
CQ = 100
     - 40·clamp((cyclomatic - 1)/39, 0, 1)
     - 25·clamp((nesting - 1)/9, 0, 1)
     - 20·clamp((logical LOC - 1)/299, 0, 1)
     - 15·clamp((longest function LOC - 1)/119, 0, 1)
```

Failed code quality is `-1000`. Function capability and LLM Strategy Alignment
are also diagnostics. None is passed to lexicase.

```text
Implementation:
evaluation/game_metrics.py::_summarize_opponent_group()
evaluation/objectives.py::build_objectives()
eagle/opponent_cases.py::aggregate_game_performance()
evaluation/code_quality.py::_complexity_details()
evaluation/code_quality.py::build_successful_code_quality()
eagle/evaluation.py::evaluate_candidate()
```

### Final test

The final test uses the seven search opponents plus PassiveAI, RandomAI, and
RandomBiasedAI. It plays 10 games per side on each of three maps:
`10 opponents × 3 maps × 10 games × 2 sides = 600`. It reports W/L/D/errors
and does not feed back into search. The orchestrator normally runs it after
search. Final-test candidate selection first tries the summary-best runnable
member of the latest generation; compatibility fallback selects a runnable
candidate by lexicographic seven-objective tuple.

```text
Implementation:
eagle/final_test.py::FINAL_TEST_OPPONENTS
eagle/final_test.py::_run_final_matrix()
eagle/final_test.py::_select_candidate()
eagle/experiment.py::ExperimentOrchestrator.run()
```

## 5. Selection

`lexicase_select()` shuffles all seven opponent cases using the seeded EA RNG.
For each case it retains candidates whose floating-point score is exactly the
current maximum. There is no epsilon or tolerance. If more than one candidate
remains after all cases, `rng.choice()` breaks the tie.

Every parent request uses this function. Two parent requests are made per child,
so the same individual may be selected repeatedly and both selected parents may
be the same. This is selection with replacement at reproduction time.

Survival is `(mu + lambda)`: unique current parents and offspring are pooled;
lexicase repeatedly chooses one survivor, then removes it, until
`population_size` is reached. There is no explicit scalar elite. A parent can
survive as a lexicase specialist, but the aggregate-best candidate is not
guaranteed survival. There are no duplicate IDs among survivors.

```text
Implementation:
eagle/selection.py::lexicase_select()
eagle/selection.py::select_parent()
eagle/selection.py::select_next_generation()
eagle/search.py::create_offspring()
```

### Effective selection pressure

The cases are opponent means, not individual matches or maps. The first randomly
ordered opponent often decides selection immediately because exact floating
scores rarely tie. This favors candidates that are best on at least one
opponent, even if they are poor on the other six. Maps, sides, W/L/D, material,
and resources affect selection only after being collapsed into the opponent
mean. The reporting weights do not strengthen pressure on AllInBot, Mayari,
COAC, or TMA.

The artifacts show the expected specialist pattern. In the 0.2/0.8 corrected
run, different candidates achieved the recorded maxima on LightRush, HeavyRush,
WorkerRush, AllInBot, Mayari, COAC, and TMA. Its best aggregate candidate
appeared in generation 12 (`-74.152099`) but the final representative was worse
(`-95.759376`). In the 0.4/0.6 run, the best aggregate candidate appeared in
generation 4 (`-63.651066`) but the final representative was `-100.361131`.
This is not evidence that lexicase is inactive; it is evidence that its actual
objective is niche preservation, not monotonic scalar progress.

No active source path implements NSGA-II, tournament, or uniform-random
selection. `tests/test_eagle_pipeline.py` still has a misleading test name
`test_selection_binary_tournament_returns_candidates`, but the body calls
`select_parent()` and only checks membership; it does not test a tournament.

## 6. Game Reflection

The current “Game Reflection” operator is named Strategy Reflection in source.
Its actual flow is:

1. Use the evaluated **strategy-component parent** as evidence source.
2. Deduplicate eligible matches by match ID.
3. Select up to the configured sample budget (normally 10) with deterministic
   seeded ties.
4. Prefer opponent coverage, then map coverage, then outcome priority
   `loss > draw > win`; side and opponent×map×side coverage are tracked.
5. Send each selected match separately to Commentator with the candidate policy,
   opponent identity/class, map, side, outcome, compact record, and full raw
   trace.
6. Save each validated diagnosis.
7. Build a deterministic global summary from all evaluated match records; there
   is **no separate summary LLM**.
8. Send parent policy, diagnoses, global summary, selection metadata, parent
   comparison, and commentary failures to one Coach intent: REFINE 0.40,
   COUNTER 0.25, STRUCTURAL 0.20, or ALTERNATIVE 0.15.
9. Validate and store `new_strategy_prompt`; preserve generation prompt and Java
   genotype component.
10. The shared evaluation boundary passes the revised policy into the Generator
    and regenerates Java.

```text
Implementation:
eagle/strategy_reflection.py::select_reflection_matches()
eagle/strategy_reflection.py::build_global_evaluation_summary()
eagle/strategy_reflection.py::StrategyReflectionPipeline.run()
eagle/strategy_reflection.py::_commentator_prompt()
eagle/strategy_reflection.py::_coach_payload()
prompts/match_commentator.txt
prompts/coach_refine.txt (and counter/structural/alternative variants)
```

It selects exactly 10 only when at least 10 eligible matches exist. Missing or
failed traces reduce actual commentary count; if no valid diagnoses remain, the
mutation fails and preserves the parent policy. Duplicated match IDs cannot
dominate, and the coverage phases deliberately represent all seven opponents
and three maps when possible. Nevertheless, repeated deterministic rounds can
remain behaviorally redundant, and once coverage is satisfied several samples
may still come from the same opponent/map outcome class.

A real 0.2/0.8 generation-1 selection drew 10 losses from 126 losses, covered all
seven opponents and all three maps, and covered 10 distinct
opponent×map×side combinations. Its artifacts include all 10 individual
commentator results, global summary, Coach input/output, parent and child policy,
and `generator_strategy_input.txt`.

```text
Observed behavior:
runs/20260825_003735_743397/candidates/gen_0001_9e3647f4dec3/
  mutation/strategy_reflection/match_selection.json
  mutation/strategy_reflection/commentary/*/match_analysis.json
  mutation/strategy_reflection/global_evaluation_summary.json
  mutation/strategy_reflection/coach_output.json
  mutation/strategy_reflection/generator_strategy_input.txt
```

Propagation does not silently discard the new policy: `write_candidate_inputs()`
records the exact stripped value supplied to `Candidate.generation_input()`, and
evaluation asserts genes remain unchanged. The unresolved issue is semantic:
the Coach can infer brittle or unimplementable policies from losses. The code
has no policy capability validator analogous to Java API validation.

## 7. Code Reflection

Code Reflection does not consume match logs or game outcomes. In default mode it
compares the evaluated evidence parent's policy with its generated phenotype. In
inherited mode it compares the **child's current policy** with the child's
selected inherited Java component; structural/compiler diagnostics come from
the selected Java evidence parent and are dropped if they describe a failed
attempt rather than the inherited fallback source.

The reviewer must classify the relation as policy-clear/Java-violating,
policy-ambiguous, or faithful, with at most five mismatches. It receives only
the Java between the strategy markers; the immutable API guide is separate and
fixed scaffold source is excluded. A second LLM call returns a structured
`remove_rule_ids`/`add_rules` delta. Runtime rejects concrete strategy/unit/Java
instructions, derives stable IDs, and deterministically renders the bounded
reusable generation prompt. Only `generation_prompt` is replaced; policy
remains byte-identical. The normal evaluation boundary then regenerates a
complete Java phenotype.

```text
Implementation:
eagle/reflection_prompts.py::build_code_reflection_prompt_bundle()
eagle/rewrite.py::PromptRewriteMutation.mutate()
eagle/mutation.py::parse_reflection_response()
prompts/code_reflection.txt
prompts/code_rewrite.txt
eagle/candidate.py::Candidate.generation_input()
```

Artifacts distinguish it from Strategy Reflection:
`mutation/code_reflection/reflector_request.txt`, raw response, rewriter request
and response, metadata, and original prompt files. Current `candidate.json`
does not add a dedicated code-reflection artifact reference, but `mutation_type`
and the directory make the operation recoverable.

The historical 0829 artifacts exposed a review-quality failure. For
`gen_0001_df8fedf49520`, the reviewer received the worker-rush policy and full
inherited Java. It then incorrectly called the immutable
`barracksType` field and generic helper support a behavioral violation, claimed
queue semantics the API does not expose, and the rewriter proposed
`context.player.getResources()` even though `context.player` is an integer.
Current source addresses that failure mode by excluding fixed source and by
accepting only policy-agnostic reusable-rule deltas. The old run remains valid
historical evidence and is not retroactively rewritten.

```text
Observed behavior:
runs/20260829_221010_299914/candidates/gen_0001_df8fedf49520/
  mutation/code_reflection/reflector_request.txt
  mutation/code_reflection/reflector_response_raw.txt
  mutation/code_reflection/rewriter_response_raw.txt
```

Therefore the intended semantic split is implemented at the data-flow level:

```text
Strategy Reflection → changes strategic intent
Code Reflection     → changes instructions intended to improve fidelity
```

It is not yet demonstrated that Code Reflection consistently improves fidelity.

## 8. Game vs Code Reflection Comparison

| Aspect | Game / Strategy Reflection | Code Reflection |
|---|---|---|
| Input evidence | Up to 10 individual match traces plus deterministic all-126 summary and parent comparison | Policy + editable generated/inherited Java strategy region + immutable API guide + bounded structural/compiler diagnostics |
| LLM role | Match Commentator per trace, then Coach | Policy-Code Alignment Reviewer, then generation-prompt Rewriter |
| Editable genotype component | `strategy_prompt` | `generation_prompt` |
| Preserved component | Generation prompt and inherited Java | Policy and inherited Java |
| Expected semantic effect | Change economy/combat intent based on game evidence | Make Java more faithful to existing intent |
| Actual implementation | Single-gene policy mutation; real artifacts confirm isolation and generator propagation | Single-gene deterministic reusable-rule mutation; historical free-form prompts canonicalize on their next successful Code Reflection |
| Generated Java regeneration | Yes, at shared evaluation boundary | Yes, at shared evaluation boundary |
| Saved artifacts | Selection, traces, individual analyses, global summary, Coach IO, parent/child policy, generator policy input | Reviewer IO, Rewriter IO, originals, metadata |
| Main observed risk | Loss evidence can yield brittle or impossible policy instructions | Reviewer may still misclassify editable behavior, but cannot use fixed scaffold source or persist policy-specific Java checklists |

The operators share `create_offspring()`, the shared generator input assembly,
generation retries/repair, and evaluation. They do **not** share the same
reflection prompt or gene assignment. A failed reflection/rewrite returns an
unchanged genotype for either operator; both may therefore look like copy
operations. A blank policy makes only Strategy Reflection eligible, preventing
Code Reflection from inventing strategic intent.

Balance Reflection is the important equivalence-breaking third path. It shares
the generic reflection/rewrite machinery with Code Reflection, consumes only a
W/D/L table, and then rewrites **both** policy and generation prompt. In the
active config it occurs three times as often as either primary operator, so an
experiment described only as Game-vs-Code is misleading.

## 9. Adaptive Operator Selection

The accepted source names are exactly `static`, `aos_opponent`, and
`aos_head2head` (`eagle/aos.py::ReflectionOperatorMode`). All enabled operator
probabilities must sum to one. In adaptive modes the configured initial
probabilities remain exact until the first update; the default floor is 0.10.
If an operator is ineligible, selection renormalizes the current probabilities
over the eligible subset.

### `static`

The selector samples fixed Strategy/Code/Balance probabilities using the shared
EA RNG, records usage, computes no rewards, and never changes probabilities.
Blank policy forces Strategy Reflection. The current 0829 config uses
`0.20 / 0.20 / 0.60`; the corrected static_0824 runs used `0.20 / 0.80 / 0`
and `0.40 / 0.60 / 0`.

### `aos_opponent`

This mode launches no additional matches. It compares the child to its recorded
comparison parent using the completed normal 126-match matrices.

- failed parent → runnable child: `+1`;
- runnable parent → failed child: `-1`;
- both failed: `-0.1`;
- both runnable: reduce each opponent to rank 2 if wins > losses, 1 if tied,
  0 if losses > wins, then
  `(improved_cases - regressed_cases) / compared_cases`, range `[-1,1]`.

It discards score magnitude and map/side detail. An agent can improve shaped
scores substantially without changing an opponent majority rank and receive
zero reward.

### `aos_head2head`

A runnable child plays its comparison parent on the same three maps, three
rounds, and both sides: 18 direct games. Its reward is
`(wins + 0.5·draws) / valid_matches`, range `[0,1]`; errored matches are excluded
from the denominator. A failed child receives 0. A runnable child whose parent
cannot run receives 1.

### Shared update and persistence

For each operator with rewards in a generation:

```text
credit_new = 0.8·credit_old + 0.2·mean_generation_reward
```

Probability matching clamps negative credits to zero, normalizes positive
credits, then enforces the configured floor among enabled operators. If every
credit is nonpositive, normalization falls back to the **current probabilities**,
so probabilities can remain unchanged indefinitely. State is one global
controller for the run, persists in generation AOS records, and is restored on
resume. Rewards are stored against the selected operator and child ID.

The audit originally found a comparison-parent provenance weakness. The current
source corrects it: `create_offspring()` records the evaluated parent used to
construct mutation evidence. Strategy follows `strategy_parent_id`; default-mode
Code/Balance follows `generation_prompt_parent_id`; inherited-mode Code/Balance
follows `java_parent_id`. Component-wise crossover can therefore source either
direct parent without AOS silently comparing the child with the other one.

```text
Implementation:
eagle/aos.py::AdaptiveOperatorSelection.update_generation()
eagle/aos.py::calculate_opponent_reward()
eagle/aos.py::calculate_head_to_head_reward()
evaluation/parent_offspring.py::evaluate_parent_vs_offspring()
eagle/search.py::create_offspring() [comparison_parent_id]
```

Why static and `aos_opponent` may look similar: opponent reward is coarse; most
weak candidates have the same loss-majority rank on all seven cases; zero or
nonpositive credits trigger current-probability fallback; and the minimum floor
limits movement. No current local run tests this empirically. Config files for
`aos_head2head` exist under the four model directories, but no config selects
`aos_opponent`, and every inspected `runs/*/config.yaml` is static.

## 10. Experiment Configuration

The recurrent recent settings are Ministral 3 8B Q4_K_M, temperature 0.2,
population 10, 20 offspring generations, crossover 0.75, mutation 0.85, EA seed
7, tick limit 5000, timeout 120 seconds, the three canonical maps, three rounds,
and side swapping. Static_0824 and later configs set five generation attempts;
older configs may rely on the source default of one.

| Config family | Genotype mode | Seed | Operators | Status at audit |
|---|---|---|---|---|
| `configs/experiments/static_0824/` | default two-prompt | blank | static Strategy/Code ratios 0.2/0.8 through 0.8/0.2 | 0.2 and 0.4 complete; 0.6 interrupted gen10; 0.8 not indexed |
| `configs/experiments/static_0826_seed_variants/` | inherited three-component | blank, random, or worker-rush in separate configs | static 0.5/0.5 | all three indexed and complete |
| `configs/experiments/0829_3_reflection/` | inherited three-component | worker rush | Strategy/Code/Balance ratios 0.2/0.2/0.6, 0.33/0.33/0.34, 0.4/0.4/0.2 | only 0.2/0.2/0.6 indexed; manifest says running at gen18, but no EAGLE or llama-server process was present during audit |
| Four model-root configs | default two-prompt | blank | `aos_head2head`, initial 0.2/0.8 | configs exist; no matching local run found |

The local `configs/experiments/static_0826/experiment.yaml` points at absent run
`runs/20260826_174115_493731`. The 0829 folder and several experiment indexes
are untracked working-tree files; this audit inspected them because they are the
current local experimental state, but they are not part of HEAD `af2c9f5d583`.

## 11. Recent Experiment Results

“Final test ≈ 4 / 418 / 178” means **wins / losses / draws over 600 games**.
The supplied corrected numbers are verified exactly.

### Corrected `static_0824`

| Ratio Strategy/Code | Run | Search candidates | Mutations selected | Best aggregate anywhere | Final representative aggregate | Final W/L/D |
|---|---|---:|---|---:|---:|---:|
| 0.2/0.8 | `20260825_003735_743397` | 201 | S 41, C 125, none 34 | `-74.152099` at gen12 | `-95.759376` | **4 / 418 / 178** |
| 0.4/0.6 | `20260825_130915_559782` | 201 | S 71, C 91, none 38 | `-63.651066` at gen4 | `-100.361131` | **5 / 442 / 153** |
| 0.6/0.4 | `20260826_100828_148670` | incomplete | interrupted at gen10 | not used for final comparison | n/a | no completed final test |

Both complete runs used the blank policy, default two-prompt mode, population
10 but one gen0 seed candidate, 20 offspring generations, Ministral, seed 7,
and the corrected seven-opponent matrix. Static mode recorded no rewards and
kept probabilities unchanged.

The best reporting-aggregate candidates found anywhere in the main trajectories
had these exact seven-case vectors (the active 0829 row is incomplete):

| Run / candidate | Gen | LR | HR | WR | AllIn | Mayari | COAC | TMA | GP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.2/0.8 `gen_0012_67740d19a489` | 12 | -33.432487 | 0.801249 | -101.307706 | -99.799333 | -69.619846 | -68.768873 | -102.679019 | -74.152099 |
| 0.4/0.6 `gen_0004_81c292e8e848` | 4 | -33.048158 | 17.143113 | -67.820745 | -66.126667 | -70.043661 | -69.114784 | -102.932857 | -63.651066 |
| old strong `9e9e162f40ea` | 19 | -33.048157 | 17.143113 | -33.048157 | -66.126667 | -47.371632 | -69.098147 | -102.932857 | -56.364710 |
| worker seed `gen_0020_568ed024992d` | 20 | 35.134266 | 36.224339 | -68.248656 | -66.165333 | -103.408896 | -68.805822 | -103.253995 | -61.832558 |
| 0829 `gen_0017_a6a08dfd4931` | 17 | -16.145723 | 0.905230 | -68.245407 | -66.163000 | -69.766904 | -69.165290 | -103.284402 | -63.658645 |

The 0.2/0.8 final candidate drew 20/60 against LightRush and HeavyRush, lost all
60 against each other search opponent, drew all Passive games, and obtained its
four wins only against RandomAI. The 0.4/0.6 final candidate lost all 420 games
against the seven search opponents; its five wins came only against RandomAI.

Failure stages across all candidate attempts were substantial:

- 0.2/0.8: 136 no failure, 35 validation, 18 runtime, 9 compilation,
  2 generation, 1 integration;
- 0.4/0.6: 138 no failure, 41 runtime, 14 validation, 6 compilation,
  2 integration.

### Seed-variant results under inherited genotype

| Seed | Run | Final W/L/D | Final/search representative aggregate | Search-opponent final wins |
|---|---|---:|---:|---|
| blank | `20260826_213629_074181` | 0 / 499 / 101 | `-99.916780` | 0 |
| random | `20260828_111748_129482` | 112 / 429 / 59 | `-94.175199` | 10 LightRush + 10 WorkerRush |
| worker rush | `20260829_015838_255544` | 258 / 325 / 17 | `-61.832558` | 40 LR, 40 HR, 10 WR, 10 AllIn, 10 COAC; 0 Mayari/TMA |

This is direct evidence that initialization and inherited Java trajectory matter
more than the small difference between the corrected blank-seed static ratios.
The worker-rush final policy is byte-identical to its seed, while its generation
prompt and Java change; useful progress in that lineage is primarily phenotype/
translation evolution around preserved strategic intent.

### New three-operator run

`20260829_221010_299914` is the sole indexed 0829 run. At the audit snapshot its
manifest said `running`, latest generation 18, with no final test and no live
EAGLE/llama process. It contains 190 candidates, selected 87 Balance, 39
Strategy, 25 Code, and 29 no-mutation offspring. Only 58 Balance operations
changed both genes; the rest failed/no-op atomically. Static probabilities
remained 0.2/0.2/0.6 and rewards remained absent. The best aggregate seen was
`-63.658645` at gen17, but this is not a completed-run result.

```text
Observed artifacts:
configs/experiments/static_0824/experiment.yaml
runs/20260825_003735_743397/{config.yaml,summary.json,final_test/}
runs/20260825_130915_559782/{config.yaml,summary.json,final_test/}
configs/experiments/static_0826_seed_variants/experiment.yaml
runs/20260829_015838_255544/{summary.json,final_test/}
runs/20260829_221010_299914/{manifest.json,generations/}
```

## 12. Comparison with 20260820_020955_479858

The older run completed 20 generations with Ministral, population 10, static
Strategy/Code 0.6/0.4, a nonblank `prompts/initial_strategy.txt` seed, and an old
implicit `previous_code.java` genotype. Its final selected candidate
`b64ce7e86805` had reporting aggregate `-58.419243` and final W/L/D
**269 / 312 / 19**. Search-opponent wins were 20 LR, 30 HR, 20 labelled WR,
10 AllInBot, 10 Mayari, 10 COAC, and 0 TMA; 169 of the 269 wins came from the
three simple final-test opponents. Its generation AOS records show 96 Strategy
and 61 Code selections, zero rewards, and unchanged probabilities because it
was static. Across 210 candidate artifacts, 178 had no blocking failure, 27
failed compilation, and 5 failed at runtime.

### Confirmed differences

| Dimension | `20260820_020955_479858` | Corrected static_0824 / current |
|---|---|---|
| Initial policy | Nonblank established strategy | Blank in static_0824; later explicit blank/random/worker seeds |
| Strategy/Code ratio | 0.6/0.4 | 0.2/0.8 and 0.4/0.6 |
| Genotype Java | Old implicit `previous_code.java` | No inherited Java in static_0824; explicit versioned `inherited_java` only in opt-in later configs |
| Gen0 population | 10 candidate artifacts | One seed candidate in default-mode corrected runs; 10 independent decoder calls in current inherited mode |
| WorkerRush | Compatibility subclass of LightRush | Distinct vendored WorkerRush after `e31c94ad067` |
| AllInBot | Pre-current direct upstream behavior | Current fault-contained wrapper can convert opponent faults to neutral draws |
| Generation safeguards | Old generation artifact contract | Current fixed scaffold, bounded repair attempts, validation and delta guards |
| Artifact schema | Old names and 12-hex IDs | v5 candidates, explicit genotype/phenotype split and component lineage |

The old run's final total is therefore not a controlled comparison with the
corrected runs. In particular, its labelled WorkerRush score duplicates
LightRush behavior, and its exact Git checkout was not stored.

### Plausible explanations supported by evidence

- The nonblank strategy and inherited previous code supplied a much stronger
  starting basin than a blank policy and fixed gen0 Java seed.
- More Strategy Reflection may have mattered because blank-policy search first
  needs strategic intent, but single-run ratios cannot isolate this effect.
- The duplicate LightRush/WorkerRush case made the old seven-case fitness easier
  and altered lexicase pressure.
- Current seed variants independently show a large seed effect: 0 wins for
  blank inherited, 112 total for random, 258 for worker rush.

### Unsupported speculation

- That 0.6/0.4 is intrinsically the optimal reflection ratio.
- That current safety fixes alone caused lower strength.
- That AOS would recover the old performance; no local adaptive run exists.
- That the older agent is stronger under the current exact roster without
  recompiling and rerunning it under the current evaluation code.

## 13. Policy and Phenotype Diversity

### Quantitative surface diversity

| Run | Candidate artifacts | Unique policy hashes | Unique generation-prompt hashes | Unique successful Java hashes |
|---|---:|---:|---:|---:|
| 0.2/0.8 blank | 201 | 42 | 119 | 155/155 Java files |
| 0.4/0.6 blank | 201 | 72 | 92 | 181/181 |
| worker seed inherited | 210 | 86 | 73 | 191 unique among 205 Java files |
| 0829 Balance through gen18 | 190 | 98 | 83 | 160 unique among 168 Java files |

These counts establish textual and phenotype diversity, not useful behavioral
diversity. In final populations the counts are much lower: the 0.2/0.8 gen20
population has 4 policy hashes and 9 Java hashes; 0.4/0.6 has 6 and 10; worker
seed has 5 and 10.

### Qualitative policy regions

Representative initial, early, middle, late, best, and failed candidates were
read from the corrected blank runs, the worker-seed run, and the active Balance
run.

| Region | Economy/development | Combat tendency | Evidence |
|---|---|---|---|
| Blank bootstrap descendants | Worker redundancy, resource-node contest, delayed/conditional Barracks | Reactive defense followed by Light/Heavy harassment | 0.2/0.8 gen1, gen10, gen12 |
| Preemptive mixed-unit | Immediate/early Barracks, adaptive worker count | Rush counter, worker targeting, later Heavy pressure | 0.4/0.6 gen4 and gen20 |
| Worker rush | One dedicated harvester; continuous Worker production; no Barracks | Mass Worker pressure on base/nearest enemy | worker-seed gen0/gen10/gen20 |
| Balance-derived defensive macro | Delayed workers, structure-heavy “tech” economy | Positional chokepoint defense, reactive counters | 0829 gen9/gen17 |

Blank-run policies are not mere sentence-level paraphrases: worker-first macro
and early-Barracks mixed-unit plans differ on the two requested abstract axes.
However many descendants remain in the same broad “worker economy plus
conditional production” family, and lexicase populations often converge to a
few policy hashes. Failed candidates also contain policy changes, showing that
text novelty can generate invalid or non-runnable phenotypes.

The worker-seed run is especially diagnostic. Its gen0, gen10, and final/best
gen20 policies have the same SHA-256, but their Java files have distinct hashes
and materially different worker assignment/targeting implementations. The
final generation prompt also differs from the seed. This proves that different
phenotypes can arise under unchanged strategic intent, which is the intended
Code Reflection/inherited-Java role.

The active Balance run shows the opposite failure. Its text is highly diverse
but includes unavailable game concepts—Walls, Doors, Armory, Guards, Siege
Units, upgrades, supply management, and “Mayari tech.” Generated Java compiles
by translating some “structures” into Barracks, and representative code tests
map dimensions against 64×64 and 128×128 although the configured maps are
8×8, 16×16, and 24×24, so its intended map branches do not execute as written.
This is meaningful textual diversity but poor genotype-to-phenotype fidelity.

## 14. Current Failure Hypotheses

| Hypothesis | Rating | Direct evidence |
|---|---|---|
| H1 — Reflection behavior is not correctly grounded | **Historically supported; Code path mitigated** | Gene routing and regeneration were correct, but the 0829 Code Reflection saw fixed scaffold source and wrote questionable API instructions. Current Code Reflection excludes fixed source and accepts only policy-agnostic rule deltas. Balance Reflection's historical inference from aggregate W/D/L remains separate evidence that LLM semantic grounding still requires empirical validation. |
| H2 — Evolutionary selection pressure is ineffective | **Partially supported** | Lexicase is active and discriminating, but it selects exact opponent specialists. Aggregate-best candidates at gen12/gen4 did not remain final representatives, and different candidates own different case maxima. This pressure preserves niches but does not guarantee broad improvement. |
| H3 — Phenotypes lack effective MicroRTS strategies | **Supported** | Corrected blank runs have verified gene deltas and many distinct compiled Java files yet zero final-test wins against all seven search opponents. Worker seed improves rush cases but remains 0/60 against Mayari and TMA. Compilability/API checks do not establish tactics. |
| H4 — Evaluation/reflection evidence is sparse or biased | **Partially supported** | Strategy Reflection reads only up to 10 traces in depth, though it also receives an all-126 W/D/L summary and coverage is good. Three repeated rounds have no explicit match seed and can be redundant. Balance sees only aggregate W/D/L and nevertheless infers mechanisms. Evidence breadth is better than the simple intended description, but causal detail is weak. |

The evidence does **not** support a claim that Strategy and Code Reflection
modify the same stored gene, that their outputs are silently discarded, or that
lexicase is bypassed. It does support a narrower and more actionable concern:
the LLM-produced mutation content and its realization in Java are not reliably
grounded in the actual MicroRTS action vocabulary and map facts.

## 15. Highest-Value Next Verification

**Question:**

Does a controlled Strategy Reflection or Code Reflection delta reach the
Generator and produce a Java behavior change that faithfully matches the
operator's intended semantic boundary?

**Procedure:**

Use one runnable worker-rush parent from `20260829_015838_255544`. From the exact
same stored genotype, make two single-child diagnostic lineages with crossover
disabled: force Strategy Reflection once and Code Reflection once. Preserve all
existing artifacts. For each lineage compare:

1. parent and child policy hashes;
2. parent and child generation-prompt hashes;
3. optional inherited-Java hash;
4. the exact rendered Generator request;
5. the generated Java strategy region, with a short human checklist tied to the
   explicit worker-rush requirements (continuous worker production, exactly one
   harvester, remaining workers attack, no Barracks/non-Worker units);
6. a small smoke matrix on one rush and one strong opponent, both sides on the
   8×8 map. Performance is secondary; semantic fidelity is primary.

This uses current operators and artifact writers and requires no architecture
change. It should be run as a diagnostic experiment, not merged as a behavior
change.

**Expected evidence if reflection propagation/grounding failure is true:**

The wrong gene changes, the Generator request lacks the changed text, both Java
strategy regions remain effectively the same, the Code child alters policy, or
the Java omits/contradicts the explicit delta (for example builds Barracks or
cannot maintain a dedicated harvester).

**Expected evidence if selection/phenotype weakness is true:**

Each operator preserves the correct other genes, its exact delta appears in the
Generator request, and Java clearly implements distinct intended behavior, but
both faithful phenotypes remain weak in the smoke matches. That shifts attention
from mutation propagation to tactical policy quality and selection/evaluation.

**Success/failure criterion:**

Success requires complete artifact-chain identity and at least one observable,
policy-consistent Java decision difference for each forced operator, with no
forbidden strategic concept. Any broken identity, missing request delta, or
contradictory Java is a propagation/grounding failure. Do not use bytewise Java
difference alone as success.

## 16. Known Technical Debt / Obsolete Paths

No cleanup was performed.

| Item | Status | Reason |
|---|---|---|
| Generic Strategy Reflection in `eagle/reflection_prompts.py`, `eagle/rewrite.py::PromptRewriteMutation(mutation_type="strategy")`, `prompts/strategy_reflection.txt`, and `prompts/strategy_rewrite.txt` | **Needs verification** | Production runtime binds Strategy to Commentator/Coach, but generic path remains directly tested and may serve embedded callers. Do not remove without tracing external use. |
| Test named `test_selection_binary_tournament_returns_candidates` | **Safe to rename later** | Name is obsolete/misleading; body exercises current lexicase `select_parent()`. |
| NSGA-II / old tournament / UR implementation | **Safe to remove later: already absent from active source** | Only historical documentation mentions removal; no active implementation path was found. |
| `BASIC_OPPONENTS` Passive/Random/RandomBiased | **Still active** | Correctly excluded from search but used by final test and GUI/compatibility. |
| `MICRORTS_VARIANT_OPPONENTS` and `eagle/opponent_sources` | **Still active / Needs verification by file** | Opponent support is compiled by `evaluation/compiler.py`; not part of search roster but supports variant/inspection paths. |
| Pre-v4 compatibility reads (`generation/normalized_candidate.java`, old genotype names) | **Still active** | Required to inspect and final-test old preserved runs such as 20260820. |
| Historical `previous_code.java` artifacts in old runs | **Safe to archive later; do not delete in place** | Not written by current source, but required for historical reproducibility. |
| `configs/experiments/static_0820`, `static_0823`, `static_0824` | **Needs verification** | Historical configurations and generated indexes remain useful provenance; filenames do not imply current behavior. |
| `configs/experiments/static_0826/experiment.yaml` | **Needs verification** | Points to missing `runs/20260826_174115_493731`. |
| `configs/experiments/0829_3_reflection/experiment.yaml` run status | **Needs verification** | Manifest says running at generation 18, but no live process was present and no final test exists. |
| Multiple generated `experiment.yaml` files | **Still active** | They are the batch-resume index contract, not duplicate executable experiment configs. |
| `docs/model_parameter_audit.md` | **Needs verification when used historically** | Useful runtime audit, but historical claims depend on preserved old schemas; it is not the source of current EA behavior. |
| `docs/implementation/current_status.md` and canonical architecture docs | **Still active** | They mostly match current source, including Balance and inherited genotype, but this audit adds artifact-grounding failures and current run results not captured there. |
| Misspelled `docs/architeture_specification_zh.md` | **Needs verification / safe to rename later with link updates** | Content is current-looking; filename is misleading but may be linked externally. |

## 17. Important Source Files

| Concern | Authoritative implementation/config/artifact |
|---|---|
| Candidate/genotype/phenotype | `eagle/candidate.py::Candidate`, `Candidate.generation_input()` |
| Component crossover | `eagle/crossover.py::crossover()` |
| Search orchestration | `eagle/search.py::_run_search_impl()`, `initialize_population()`, `create_offspring()` |
| Runtime/operator wiring | `eagle/search_runtime.py::build_search_runtime()` |
| Selection | `eagle/selection.py::lexicase_select()`, `select_next_generation()` |
| Opponent cases and weights | `eagle/opponent_cases.py`, `eagle/opponents.py` |
| Evaluation boundary | `eagle/evaluation.py::decode_validate_compile_candidate()`, `evaluate_candidate()` |
| Match matrix/runtime | `evaluation/match_matrix.py`, `evaluation/runtime_evaluation.py` |
| Game score/aggregation | `evaluation/game_performance.py`, `evaluation/game_metrics.py`, `evaluation/objectives.py` |
| Code diagnostics | `evaluation/code_quality.py` |
| Strategy Reflection | `eagle/strategy_reflection.py`, `prompts/match_commentator.txt`, `prompts/coach_*.txt` |
| Code Reflection | `eagle/reflection_prompts.py::build_code_reflection_prompt_bundle()`, `eagle/rewrite.py::PromptRewriteMutation`, `prompts/code_reflection.txt`, `prompts/code_rewrite.txt` |
| Balance Reflection | `eagle/reflection_prompts.py::build_balance_reflection_prompt_bundle()`, `eagle/rewrite.py::BalanceReflectionMutation`, `prompts/balance_*.txt` |
| AOS | `eagle/aos.py`, `evaluation/parent_offspring.py` |
| Artifact serialization | `eagle/artifacts.py`, `eagle/run_artifacts.py`, `eagle/resume.py` |
| Experiment/final test | `experiment.sh`, `eagle/experiment.py`, `eagle/final_test.py` |
| Analysis | `eagle/analysis/loader.py`, `eagle/analysis/report.py` |
| Current active local config | `configs/experiments/0829_3_reflection/ministral3_8b_static_0.2_0.2_0.6_worker_rush.yaml` |
| Corrected static results | `configs/experiments/static_0824/experiment.yaml`, runs `20260825_003735_743397` and `20260825_130915_559782` |
| Seed comparison | `configs/experiments/static_0826_seed_variants/experiment.yaml`, runs `20260826_213629_074181`, `20260828_111748_129482`, `20260829_015838_255544` |
| Historical strong run | `runs/20260820_020955_479858` |

The current analysis loader targets the canonical v2 run/candidate layout and
produces candidate/generation/operator summaries, CSVs, and plots. Historical
v1 runs can still be inspected through compatibility readers and direct
artifacts, but they should not be assumed to load identically through every
current analysis report path.

### Validation performed for this audit

- Parsed every current experiment YAML and checked generated run-index targets;
  all existed except the specifically reported static_0826 target.
- Recomputed the reported weighted aggregates, mutation/component hash counts,
  failure counts, diversity hashes, and final W/L/D tables from run artifacts.
- Inspected representative policies and Java strategy regions at generation 0,
  early, middle, late, best, and failed points.
- Compiled all Python modules with `python3 -m compileall -q eagle evaluation generation`.
- Ran 104 focused architecture/evaluation/mutation/AOS/artifact tests: all passed.
- Ran the full test suite: 362 passed, 1 skipped.
- Ran `git diff --check`: passed.

### Audit uncertainties

- Old run manifests do not identify their Git commit; historical source details
  were inferred only where artifact layout and dated commits make the difference
  explicit.
- No local adaptive-mode run was found, so AOS behavior is source- and test-
  verified rather than empirically demonstrated on a preserved production run.
- The 0829 run is incomplete/stale-running at generation 18 and must not be
  reported as a final result.
- Policy and Java diversity assessment is qualitative plus hash counts; it does
  not claim a behavioral diversity metric.
