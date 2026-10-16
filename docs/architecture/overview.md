# Architecture overview

EAGLE evolves one complete Java MicroRTS agent. Candidate state mode and Java
materialization mode are independent settings. `candidate_java_mode` controls
whether generated Java is phenotype-only or an inherited genotype component;
`java_materialization_mode` selects LLM translation, deterministic DSL
compilation, or run-frozen framework-slot rendering. Deterministic DSL and
framework-slot configurations require `candidate_java_mode: generated_phenotype`
and `parent_evaluation_mode: reuse_cached`. Framework-slot mode bootstraps
inline on fresh startup when no explicit `framework.bundle_path` is supplied; it
freezes the framework and finite domains in the run. `framework.evolution_mode`
defaults to local deterministic EA; opt-in `llm_coach` uses the experiment model for initial genome selection and
Strategy mutation while Java rendering stays local. The active evolutionary contract is documented in
[`../opponent-wise-lexicase.md`](../opponent-wise-lexicase.md).

## System boundary

In scope:

- a canonical versioned JSON DSL policy gene, an optional active
  policy-to-Java code-generation prompt, and optionally inherited Java;
- whole-policy crossover/copy and Strategy Reflection in deterministic DSL
  mode; LLM mode additionally supports Prompt Reflection, Code Reflection, and
  Java generation;
- per-slot crossover and local one-slot mutation, or opt-in complete-genome
  Coach selection/mutation, over finite `integer`, `number`, or enumerated
  `expression_choice` domains in framework-slot mode;
- validation, compilation, integration, and fixed-roster or immutable-snapshot self-play evaluation;
- fixed-roster opponent-wise lexicase or self-play scalar Game Performance
  selection with semantic tie-breaking, artifacts, and analysis.
- one resolved experiment config and one owned local llama.cpp lifecycle; each
  model phase may add one ordered unmanaged OpenAI-compatible endpoint, while an
  optional second generation model may share the owned-local lifecycle through
  explicit phase switches.

Code quality, compiler output, function coverage, alignment, and match
telemetry remain diagnostics. They are not additional evolutionary objectives.

## Pipeline

```mermaid
flowchart TD
    CFG["Config YAML or directory"] --> L["Experiment orchestrator"]
    L --> RI["experiment.yaml run index"]
    L --> Z["Generation 0: configured policy, sampled genome, or LLM selection"]
    L -->|LLM roles enabled| RT["Owned local llama.cpp primary"]
    L -->|optional per phase| EXT["Unmanaged additional endpoint"]
    RT --> PF["Fail-closed chat preflight for all endpoints"]
    EXT --> PF
    PF -.-> Z
    Z --> SW
    P["Evaluated population"] --> S["Mode-specific parent selection"]
    S --> CG{"Java materialization mode"}
    CG -->|llm| GATE["Gate each source against its DSL policy + Java"]
    GATE -->|Healthy| X["Crossover/copy + mode-allowed reflection"]
    GATE -->|Defect| CR["One-parent corrective child; preserve genes"]
    GATE -->|Diagnosis failure| FAIL["Failed child; no crossover/mutation"]
    CG -->|deterministic_dsl| XDSL["Whole-policy copy/crossover"]
    CG -->|framework_slots| FM{"Framework evolution mode"}
    FM -->|local| XFS["Local per-slot crossover/mutation"]
    FM -->|llm_coach| XFC["Complete-genome selection/Coach mutation"]
    XDSL --> M
    XFS --> SW
    XFC --> SW
    X --> M{"Run mode-allowed reflection work"}
    M -->|Strategy| SR["Strategy Reflection + Coach"]
    M -->|Prompt (llm only)| PR["Prompt Reflection + prompt rewrite"]
    M -->|No| SW["Materialization phase"]
    SR --> SW
    PR --> SW
    CR --> SW
    SW --> GM{"Java materialization mode"}
    GM -->|llm| G["LLM generation/revision or fixed generation-zero source"]
    GM -->|deterministic_dsl| D["Compile strategy DSL to Java"]
    GM -->|framework_slots| FW["Render immutable framework bundle"]
    G --> V["Validation"]
    D --> V
    FW --> V
    V -->|valid| C["Compile"]
    C -->|success| I["Integration"]
    V -->|invalid, llm| REP["Bounded compile-guided repair"]
    C -->|failure, llm| REP
    REP --> G
    D -->|compiler failure| FAIL
    V -->|invalid, deterministic_dsl| FAIL
    C -->|failure, deterministic_dsl| FAIL
    I --> SP["Diagnostic semantic probe when enabled"]
    SP --> E["180 MicroRTS matches"]
    E --> O["10 fixed-roster cases or self-play scalar"]
    FAIL --> FS["Canonical failure sentinel + artifacts"]
    FS --> N
    O --> R{"Reflection operator mode"}
    R -->|static| F["Fixed probabilities"]
    R -->|aos_opponent| Q["Ten-opponent rank reward"]
    R -->|aos_head2head| H["Configured parent-vs-offspring matches"]
    Q --> A["Shared EMA operator update"]
    H --> A
    F --> N["Parent + offspring mode-specific survivor selection"]
    A --> N --> P
    N --> FT["Final test"]
    FT --> CL["Finalize artifacts; stop owned runtime if any"]
```

## Invariants

- One generated source and one compiled class directory serve all 180 matches.
- In LLM materialization mode, `inherited_genotype` generation zero replicates
  one seed policy to the fixed population and performs one independent Generator
  call per individual under `configured_seeds` initialization.
- In LLM materialization mode, `llm_generated_policies` keeps one configured
  policy and runs independent policy-only calls for remaining slots in a bounded
  pool. Their first-wave prompts share one configured-seed snapshot; outputs are
  resolved and duplicate retries are processed in candidate order. Java generation
  also runs per candidate in the bounded pool. WorkerRush Java is inherited
  prompt context.
- Policy generation and strategy-facing reflection/rewrite roles share one
  immutable closed-world MicroRTS gameplay contract; it permits strategy
  diversity while grounding every rule in legal entities, actions, and
  observable state.
- New policy genes are validated canonical `eagle-strategy-dsl-v1` JSON with
  ordered actor/when/action rules, intrinsic legal-action guards, and idle empty
  rules. The `llm` materializer asks the Generator to implement the DSL;
  `deterministic_dsl` compiles it through the versioned typed-IR compiler. Neither
  mode adds a runtime interpreter.
- Under `java_materialization_mode: llm`, every selected source passes its own
  independent Code gate before actual crossover/mutation. Normal mutation/AOS
  covers Strategy and Prompt; corrective Java bypasses ordinary Generator
  overwrite. Under `deterministic_dsl`, the active genotype is only the complete
  policy component: crossover copies a whole policy, Strategy mutation remains
  enabled, and Prompt Reflection, Code Reflection/source repair, and Java LLM
  generation/repair are disabled.
- Under `framework_slots`, fresh startup bootstraps from `design_brief` unless an
  external bundle is supplied, then freezes `eagle-framework-bundle-v1` bytes
  and SHA-256; candidates evolve only
  `control_genome`. The local default uses seeded EA operators. Opt-in
  `llm_coach` uses the experiment model for initial complete-genome selection
  and the one-worst-match Commentator/Coach Strategy path. Formula-like control
  remains an enumerated choice among bundle-frozen Java expressions. Prompt/Code
  Reflection, source gating, Java Generation, and Java repair are disabled.
- LLM-mode Code diagnosis has only strategy fidelity and code correctness; cosmetic
  simplification is forbidden and ambiguous/correct Java needs no revision.
- `model` handles initialization and mode-allowed reflection/rewrite work. In
  LLM mode, optional `generation_model` handles final Java generation, Code
  Reflection revision, and compile-guided generation repair; when omitted,
  `model` handles both phases. Deterministic DSL mode has no generation-model
  phase.
- `model.additional_endpoints` and the same field under `generation_model` may
  contain at most one `{base_url, model}` entry. The primary endpoint remains
  the managed local llama.cpp process; an additional endpoint is unmanaged.
  Canonical input index selects the ordered endpoint slot, retries remain sticky,
  and there is no cross-endpoint failover. Results remain candidate ordered and
  request evidence records the actual endpoint and model.
- In inherited candidate mode with `llm` materialization, crossover selects
  policy, generation prompt, and Java parents independently; generated child
  Java becomes the inheritable Java component available to the next generation.
  In deterministic mode, generation-prompt and inherited-Java values are
  inactive and do not participate in crossover or phenotype materialization.
- Fixed-roster fitness is the ten-opponent mapping in
  `Candidate.fitness_objectives`. Self-play fitness is the single
  `game_performance` value.
- The reporting aggregate uses fixed `0.5/1/2` weights and denominator `12.5`,
  but does not participate in lexicase case filtering.
- Failed candidates remain in the joint parent-plus-offspring input and artifact records with the canonical failure sentinel and stage diagnostics, but cannot displace completed candidates during survivor selection. If fewer than the configured population size completed candidates remain, selection fails explicitly.
- Survivor selection uses the joint parent-plus-offspring (`mu_plus_lambda`)
  pool. Fixed roster uses seeded lexicase without replacement. Self-play forms
  non-chained fitness tiers anchored at each current maximum; scores within
  `1.0` inclusive are tied and exact probe-action diversity resolves any
  boundary cut.
- The canonical `parent_evaluation_mode` is `reuse_cached`: parents are not
  regenerated between generations. `regenerate_same_genotype` is a
  non-canonical diagnostic treatment restricted to inherited Java with static
  reflection. It creates fresh-ID, fully evaluated parent replicas and selects
  from those replicas plus offspring, preserving the old parent artifacts.
- `static` uses fixed probabilities; `aos_opponent` reuses ten-opponent rank
  changes; `aos_head2head` uses a separate direct matrix. Neither reward path
  creates another objective or changes normal selection.
- Self-play is explicit (`evaluation.mode: self_play`), starts with a fixed
  `PassiveAI` baseline at generation zero, and then uses delayed birth-generation
  cohorts as equally weighted immutable contexts under static reflection.
  With the default interval of five, generations 1–5 use the generation-zero
  cohort and generation 6 switches to generation one. The bounded semantic
  opponent library remains an archive, while each changed context creates
  phenotype-preserving parent replicas before offspring planning and selection.
  Every executable candidate is also measured on nine immutable semantic
  probes (three configured maps × early/mid/late); this evidence is a
  tie-break/diagnostic and never changes Game Performance.

See [`evolutionary_flow.md`](evolutionary_flow.md),
[`../evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md),
and [`../implementation/current_status.md`](../implementation/current_status.md)
for ownership and artifact details.

## Python ownership

`eagle/evolution/` owns lifecycle and phase order; `eagle/operators/` contains one independently editable implementation per EA operator; `eagle/generation/` owns LLM Java generation, deterministic DSL compilation, framework bootstrap/rendering, and validation; `eagle/evaluation/` separates decoding, opponent preparation, matrix dispatch, scoring, and pipeline records. See the [framework-slot contract](framework_slots.md) and [repository map](../implementation/repository_map.md) for edit entrypoints. This organization does not change fitness formulas, phase barriers, configuration, or serialized run contracts.
