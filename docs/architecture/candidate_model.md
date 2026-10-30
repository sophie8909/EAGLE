# Candidate model

Framework reflection candidates additionally preserve optional natural-language
`strategy_description`, with old snapshots omitting it remaining readable.
Generation-zero Coach fills slots from the authored description; boundary Coach
reflection revises the description before a separate slot-filling stage.
Local offspring inherit parent A's description. The executable active genotype
remains `control_genome`; description prose is supporting strategy intent and is
not rendered as Java or used as an extra local mutation component.
This state is shared by whole-framework `reflection` and frozen-framework
`option_reflection`; the latter keeps every candidate pinned to the initial
bundle hash for the full run.

## Genotype and phenotype modes

In `java_materialization_mode: llm`, active genes are `strategy_prompt` and
`generation_prompt`. The default `candidate_java_mode: generated_phenotype`
keeps complete Java as phenotype/evidence; `inherited_genotype` adds a complete
pre-generation Java component that the Generator revises into the phenotype.

`java_materialization_mode` is independent of candidate Java state mode. An
absent value defaults to `llm` for old configs. In `deterministic_dsl`, only the
complete `strategy_prompt` is active genotype. Generation prompt and optional
inherited Java are inactive compatibility data and do not participate in
materialization, crossover, or mutation. Candidate snapshots record mode,
compiler version, and `active_genotype_components: ["strategy_prompt"]`.
Deterministic mode uses whole-policy copy/crossover only; it has no rule-level crossover. New deterministic configs require `candidate_java_mode: generated_phenotype` and `parent_evaluation_mode: reuse_cached`.

LLM-mode initialization and inheritance continue to follow the configured
`generated_phenotype`/`inherited_genotype` and seed initialization modes. The
Generator call and inherited-Java context apply only when materialization mode is
`llm`; deterministic materialization consumes normalized policy and the canonical
scaffold.

In `framework_slots`, the only active gene is `control_genome`: an exact mapping
from every run-frozen bundle slot ID to one typed finite-domain value. The
framework template, structured report, and `slot_generation_prompt` are immutable
run inputs, never genes. `framework.evolution_mode` selects local seeded genome
sampling/variation or Coach-assisted complete-genome selection/mutation without
changing the active component. Each candidate pins `framework_bundle_sha256`,
uses `candidate_java_mode: generated_phenotype`, and records
`active_genotype_components: ["control_genome"]`. See
[framework slots](framework_slots.md) for the exact bundle and domain schema.
With `framework.evolution_mode: local`, the optional positive
`framework.gpt_initial_candidates` count changes only the first N Gen-0
initialization slots: direct GPT returns complete hash-pinned genomes, while
the remaining Gen-0 slots and all offspring stay local. It is not a second
genotype or a Coach mode; the count defaults to zero and is fenced by resume.
Alternatively, `framework.initial_genomes` supplies a validated list of
complete mappings for the same first-N Gen-0 prefix. It is local-only,
mutually exclusive with `gpt_initial_candidates`, and its resolved list plus
manifest hash/count are resume-fenced; the list does not add a genotype
component or affect offspring variation.

## Policy contract

`strategy_prompt` stores canonical `eagle-strategy-dsl-v1` JSON, validated by
`eagle/strategy_dsl.py`. Ordered rules contain `actor`, `when`, `action`; intrinsic
legality guards are fixed, and empty rules idle. The LLM Generator or the
`deterministic_dsl` compiler implements this policy offline without a runtime
DSL interpreter. New runs reject natural language. The independent Java source
gate and corrective Code Reflection apply only to `llm` mode. See
[mutation](mutation.md) for the mode-specific mutation contract.

## Required logical fields

| Group | Fields |
| --- | --- |
| Identity | `candidate_id`, `generation`, `parent_ids` |
| Genotype | `active_genotype_components`; mode-specific prompt/optional Java values or framework `control_genome` |
| Phenotype | `generated_java`, `generated_java_path` |
| Variation | `operator`, `mutation_type` |
| Component provenance | prompt/optional Java parent IDs, or framework `slot_parent_ids` plus `framework_bundle_sha256` |
| State/failure | `status`, `failure_stage`, `failure_reason` |
| Objectives/evidence | active-mode fitness, executable semantic signature, game/code diagnostics |
| Persistence references | `artifacts`, `timing` |

EA factories derive new runtime IDs as
`gen_<zero-padded-generation>_<12-hex-deterministic-suffix>` from the root seed
and stable lineage identity. `Candidate` does not synthesize an ID: every
candidate must receive an explicit non-empty identity before entering the
pipeline. Explicit IDs loaded from supported artifacts remain opaque and
unchanged.

## Construction invariants

- A child genotype is complete only when every active component and its provenance are known.
- In `llm` mode, whole-component crossover chooses the two prompt genes
  independently and, in inherited mode, Java independently.
- In `deterministic_dsl` mode, whole-policy copying/crossover is the only
  genotype operation; rule-level crossover is absent.
- In `framework_slots` mode, per-slot crossover chooses each value independently
  and mutation changes at most one slot to a different legal value. Every slot
  has `slot_parent_ids` provenance; prompt/Java component provenance is absent.
- Strategy mutation changes only `strategy_prompt` in LLM and deterministic
  DSL modes; framework `llm_coach` may replace the complete `control_genome`.
- Prompt Reflection may change only `generation_prompt` in `llm` mode and is
  disabled in deterministic mode.
- Code Reflection preserves active genes and revises Java only in `llm` mode;
  deterministic mode disables Code Reflection and source repair.
- Java materialization and Evaluation do not modify active genotype
  components.
- Framework-slot materialization substitutes typed values into the run-frozen
  template and cannot call an LLM or synthesize a new expression. Its
  `expression_choice` values name predeclared Java expressions from the bundle.
- The LLM Generator uses the canonical scaffold and receives selected parent
  Java only in inherited candidate mode. The deterministic compiler uses
  normalized policy and canonical scaffold only.
- Failure never erases genotype, partial phenotype, lineage, mutation
  evidence, or timing.
- `semantic_signature` describes the compiled full agent on the versioned
  probe dataset; it is distinct from prompt-derived `strategy_signature` metadata.
## Compatibility

New candidate artifacts use `genotype/policy_prompt.txt`,
`genotype/code_generation_prompt.txt`, and `phenotype/CandidateAgent.java`.
Historical artifacts remain read-only. Resume rejects incompatible natural-language
policy and old reproduction/operator contracts; it never silently converts them.
