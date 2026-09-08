# Mutation responsibility boundaries

EAGLE has exactly three mutually exclusive reflection operators: Strategy,
Prompt, and Code. Strategy changes the policy gene, Prompt changes the reusable
policy-to-Java translation gene, and Code changes the candidate Java directly.

## Strategy Reflection

Strategy Reflection changes only `strategy_prompt`:

```text
selected match traces
  -> Match Commentator -> MatchAnalysis summaries
  -> Coach -> replacement strategy_prompt
  -> final Java Generator
```

The Match Commentator receives the current policy, opponent, map, side, result,
allowlisted match record, canonical trace, and immutable closed-world MicroRTS
gameplay contract. It receives no Java, generation prompt, compiler diagnostics,
or fitness-writing task. The Coach receives the same gameplay contract, parent
policy, selected analyses, and evaluation/selection metadata. Its replacement
may change strategy type, but every condition must use observable state and every
response must be a legal game action.

```text
(policy A1, prompt B1, Java C1) -> (policy A2, prompt B1, Java C1) -> Java C2
```

## Prompt Reflection

Prompt Reflection is the behavior formerly named Code Reflection. It changes
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

## Code Reflection

Code Reflection first diagnoses the selected parent Java. Its conditional Java
revision is deferred until every child in the generation has completed its
assigned reflection/rewrite work:

```text
current strategy_prompt + selected parent Java
+ immutable gameplay/API contracts + concise interface/unit reference + canonical scaffold
+ source-matching validation/compiler diagnostics
  -> three-part structured diagnosis: strategy fidelity, code simplicity,
     and game compliance
  -> generation-wide materialization boundary
  -> diagnosis + the same authoritative inputs
  -> complete corrected CandidateAgent.java
  -> validation -> javac -> integration -> evaluation
```

The Reflector independently reports whether the Java is faithful to the strategy,
concise, and compliant with the game setting, and records concrete code changes
plus behaviors to preserve; it never returns Java. The two Code calls also receive
an explicit list of the fixed interfaces and every available entity/unit with its
Java symbol and mechanics. The Java revision stage receives the exact parsed
conclusion only when at least one dimension requires correction; an all-passing
conclusion preserves the parent Java without a second LLM call. Neither stage receives
`generation_prompt`, game performance, opponent scores, W/D/L summaries, match
results, traces, logs, aggregate fitness, or other gameplay evidence. The
revision output must be one complete Java source. Both prompt genes and the
pre-mutation inherited Java remain byte-identical. The output is sent directly
to validation and compilation and is not overwritten by a final Generator
call. If either the diagnosis or Java response is unusable, the selected parent
Java is preserved. A structurally complete response that fails validation or
javac may enter the existing bounded diagnostic-only compile-repair chain.

```text
(policy A1, prompt B1, Java C1) -> (policy A1, prompt B1, reflected Java C2)
```

In `generated_phenotype` mode the source is the recorded mutation-evidence
parent phenotype. In `inherited_genotype` mode it is the independently selected
`inherited_java` component. The latter remains the recorded input/provenance;
the validated reflected source becomes the child's phenotype and
next-generation inheritable Java.

## Selection and persistence

Before any mutation LLM call, search constructs a complete generation plan that
records every child's selected parents, component crossover/copy result, and
assigned mutation. The configured static/AOS controller selects exactly one operator. Strategy uses
policy-parent provenance. Prompt and Code use generation-prompt provenance in
default mode and Java-parent provenance in inherited mode. This evaluated source
parent is also the AOS `comparison_parent_id`.

| Mutation | Probability key | Operator ID | Owned output |
| --- | --- | --- | --- |
| Strategy | `strategy_reflection_probability` | `strategy_reflection` | `strategy_prompt` |
| Prompt | `prompt_reflection_probability` | `prompt_reflection` | `generation_prompt` |
| Code | `code_reflection_probability` | `code_reflection` | complete Java |

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

The standalone inspection runs all three operators independently from one fixed
Worker Rush subject. Its expected scopes are `strategy_prompt`,
`generation_prompt`, and `generated_java`, respectively.

## Hard invariants

- Strategy preserves `generation_prompt` and inherited Java.
- Prompt preserves `strategy_prompt` and inherited Java.
- Code preserves both prompt genes and inherited Java input.
- Every offspring assignment is complete before the first reflection/rewrite
  request, and every reflection/rewrite is complete before Java materialization.
- A successful Code Reflection source bypasses the final Generator.
- Optional `generation_model` owns ordinary final Java generation, deferred
  Code revision, and compile-guided repair; otherwise the primary `model` owns
  those calls too.
- Generator and Evaluation never change prompt genes or pre-generation Java.
- Match Commentator/Coach exclude Java and generation prompts.
- Prompt Reviewer excludes raw game logs and fixed-scaffold behavior.
- Code diagnosis receives only strategy, parent Java, immutable contracts,
  interface/unit reference, and scaffold; Java revision additionally receives
  exactly that diagnosis and runs only for a reported defect.
