# Mutation responsibility boundaries

The Strategy/Prompt/Code workflows below describe `java_materialization_mode: llm`. In that mode, normal mutation has exactly two mutually exclusive operators: Strategy changes the
DSL policy gene and Prompt changes the reusable policy-to-Java translation gene.
Independent Code Reflection gates reproduction sources before actual variation.

## Strategy Reflection

Strategy Reflection changes only `strategy_prompt`. It resolves its evidence
parent through the child's recorded `strategy_parent_id` and selects exactly
one worst completed match from that parent's evaluation. The lowest finite
numeric per-match `performance` is worst; if missing or non-finite, use outcome
loss `-100`, draw `0`, win `100`. Ties use stable `match_id` order independent
of seed, and failed matches are excluded. Legacy positive `sample_count` and
`sample_budget` values remain accepted, but the effective selection count is one.

```text
one selected match trace
  -> Match Commentator -> one MatchAnalysis diagnosis
all-match global evaluation summary + selected diagnosis
  -> Coach -> validated canonical DSL strategy_prompt
  -> final Java Generator
```

In `llm` mode, the Match Commentator receives the current policy, opponent, map, side, result,
allowlisted match record, canonical trace, and immutable closed-world MicroRTS
gameplay contract. It receives no Java, generation prompt, compiler diagnostics,
or fitness-writing task. If the selected worst match has no usable trace or its
commentary exhausts retries, the existing Strategy Reflection failure path
preserves the parent policy; it does not select another match. The Coach receives
the same gameplay contract, parent policy, all-match global evaluation summary,
exactly one selected-match diagnosis, and
evaluation/selection metadata. Its replacement
may change strategy type, but every condition must use observable state and every
response must be a legal game action.

Coach and strategy-contract-rewriter prompts use one compact JSONL record whose
policy field is a nested DSL object. At the parser boundary, a complete legacy
JSON object or full JSON fence remains readable. Otherwise, non-JSON/non-object
lines are discarded and exactly one complete record carrying the role-specific
field is required (`new_strategy_prompt` for Coach,
`revised_strategy_prompt` for contract rewrite). The parser never searches for
an arbitrary version marker, so an echoed parent policy cannot become the child.
It does not repair, truncate, or delete content inside the selected DSL; the
entire object still passes strict DSL validation and canonicalization.

```text
(policy A1, prompt B1, Java C1) -> (policy A2, prompt B1, Java C1) -> Java C2
```

## Prompt Reflection

In `llm` mode, Prompt Reflection is the behavior formerly named Code Reflection. It changes
only `generation_prompt`:

```text
current policy + editable parent Java strategy region + immutable API guide
+ source-matching validation/compiler diagnostics
  -> Policy-Code Alignment Reviewer -> alignment review
current reusable rules + alignment review
  -> Prompt Rewriter -> validated reusable-rule delta
  -> replacement generation_prompt -> final Java Generator
```

The Reviewer sees only the editable strategy region, never fixed-scaffold Java.
Source-matching validation/compiler diagnostics may explain an implementation
failure. It receives no game performance, opponent scores, W/D/L summaries,
match results, traces, logs, aggregate fitness, or other gameplay evidence. It
distinguishes policy ambiguity, Java violating a clear policy, and faithful
implementation; it does not improve the strategy.

The Rewriter returns exactly `remove_rule_ids` and `add_rules`, with one compact
policy-agnostic addition and at most one removal. Runtime validates the fixed
category vocabulary, length, ten-rule limit, policy independence, and absence of
Java/API/scaffold instructions, then renders the canonical prompt
deterministically. A failed attempt does not partially modify the gene.

```text
(policy A1, prompt B1, Java C1) -> (policy A1, prompt B2, Java C1) -> Java C2
```

## Code Reflection source gate

`strategy_prompt` remains the policy gene, serialized as canonical versioned JSON
DSL (`version: "eagle-strategy-dsl-v1"`). Its ordered `rules` contain `actor`,
`when`, and `action`; `eagle/strategy_dsl.py` validates and normalizes the closed
vocabulary. Legal-action guards are intrinsic, and zero rules mean idle. The DSL
is translated into Java offline; there is no runtime interpreter. New runs reject
natural-language policies. Historical natural-language artifacts remain read-only;
incompatible old checkpoints fail resume clearly, without silent conversion.

In `llm` mode, every selected reproduction source passes an independent Code Reflection gate
against its own policy and exact Java before actual crossover or mutation. All
contributors must be healthy. A diagnosed defect instead creates a one-parent
corrective Java child with unchanged policy/generation genes and source provenance,
skipping crossover and ordinary mutation. Failed/unusable diagnosis is never a
healthy pass and cannot enter crossover/mutation. Healthy sources follow normal
crossover and Strategy/Prompt mutation. Code gating has no adaptive probability
or AOS reward. Corrective revision runs at the `generation_model` boundary (or
primary model when absent) and bypasses ordinary Generator overwrite.

Code diagnosis schema `eagle-code-reflection-v6` has exactly two independent
dimensions: `strategy_fidelity` (`faithful`, `unfaithful`, `ambiguous_strategy`)
and `code_correctness` (`correct`, `incorrect`). Only failing dimensions may have
diagnosis entries, each with concrete evidence and a minimum required correction.
Correctness covers real compilation/runtime/control-flow defects and game/API
violations. Unknown fields, cosmetic/simplification dimensions, and extra
directives are rejected. Ambiguous strategy with correct Java needs no revision.
No win/loss optimization or cosmetic refactoring is allowed. Strategy Reflection
continues to use exactly one worst completed match; its Coach returns validated
DSL while changing only the policy gene.

## Selection and persistence

Select source candidates before the independent Code gate. Actual component
crossover and normal mutation assignment use only healthy source contributors.
The static/AOS controller selects only Strategy or Prompt; policy provenance
selects Strategy evidence, and generation-prompt (default) or Java (inherited)
provenance selects Prompt evidence and the comparison parent. Corrective children
have one source parent and receive no ordinary mutation or adaptive credit.

| Mutation | Probability key | Operator ID | Owned output |
| --- | --- | --- | --- |
| Strategy | `strategy_reflection_probability` | `strategy_reflection` | canonical DSL `strategy_prompt` |
| Prompt | `prompt_reflection_probability` | `prompt_reflection` | `generation_prompt` |

New artifacts live under:

```text
mutation/strategy_reflection/
mutation/prompt_reflection/
mutation/code_reflection/
```

Prompt artifacts retain reviewer/rewrite requests, raw responses, structured
rule deltas, attempts, and errors. Code artifacts retain the diagnosis request,
raw and parsed conclusion, Java-revision request/raw response, selected parent
source, extracted reflected source, hashes, attempts, and status. The
validated/compiled result remains canonical at
`phenotype/CandidateAgent.java`.

The standalone inspection exercises all three reflection workflows independently from one fixed
Worker Rush subject. Its expected scopes are `strategy_prompt`,
`generation_prompt`, and `generated_java`, respectively.

## Hard invariants

- In `llm` mode, Strategy preserves `generation_prompt` and inherited Java.
- In `llm` mode, Prompt preserves `strategy_prompt` and inherited Java.
- In `llm` mode, Code preserves both prompt genes and inherited Java input.
- In `llm` mode every selected source is gated before actual crossover/mutation; normal
  reflection/rewrite work completes before Java materialization.
- In `llm` mode, a successful Code Reflection source bypasses the final Generator.
- In `llm` mode, optional `generation_model` owns ordinary final Java generation, deferred
  Code revision, and compile-guided repair; otherwise the primary `model` owns
  those calls too.
- Java materialization and Evaluation never change active genotype components.
- Match Commentator/Coach exclude Java and generation prompts.
- Prompt Reviewer excludes raw game logs and fixed-scaffold behavior.
- Code diagnosis receives only strategy, parent Java, immutable contracts,
  interface/unit reference, and scaffold; Java revision additionally receives
  exactly that diagnosis and runs only for a reported defect.


## Materialization-mode boundary

In `llm` mode, Strategy and Prompt remain the normal mutually exclusive
operators, and Code Reflection is the independent source gate. In
`deterministic_dsl`, only Strategy mutation is selectable and credited; Prompt
Reflection, Code Reflection/source repair, and the pre-crossover Java source gate
are disabled. The active genotype is one complete policy component, with no
rule-level crossover. Existing Strategy Reflection changes only that policy.
