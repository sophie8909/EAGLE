# Mutation responsibility boundaries

EAGLE has three mutation operators over its two prompt spaces.
Strategy Reflection searches policy space; Code Reflection searches reusable
policy-to-code translation instructions; Prompt Compliance repairs contract
violations in both genes. All stop at prompt genes. The Generator remains a
separate complete-Java revision stage. In
`inherited_genotype` mode the selected Java component is preserved through
mutation and supplied to that stage; no mutation edits Java directly.

## Strategy Reflection

Strategy Reflection changes only `strategy_prompt` (the policy gene):

```text
selected match traces
  -> one Match Commentator call per selected match
  -> MatchAnalysis summaries
  -> Coach
  -> replacement strategy_prompt
```

The Match Commentator receives the current policy, opponent identity, map,
player side, result, an allowlisted compact match record, and the canonical
raw/compact trace. It also receives the immutable strategy-level MicroRTS
gameplay contract, which defines the complete entity/action/observable-state
world but is domain context rather than match evidence. It receives no Java, code-generation prompt, compiler
diagnostics, or fitness-writing task. It analyzes one game and reports observed
strategies, turning points, strengths, weaknesses, and decisive causes.
The response boundary validates the canonical MatchAnalysis schema and performs
only bounded structural normalization: a full `match_analysis` wrapper may be
unwrapped, strategy summaries may be strings, and `key_observations.time` ranges
may supply the first tick. A response still fails when it has no numeric
tick-backed turning point or crosses the role boundary.

The Coach receives the same immutable gameplay contract, the current policy,
selected MatchAnalysis summaries, and the existing global evaluation/selection
metadata. It receives no Java or code-generation diagnostics. Its replacement
policy may change strategic type substantially, but every condition must map to
observable MicroRTS state and every response must use a legal entity/action.
Commentator and Coach transport, parsing, and semantic validation share the
configured bounded attempt budget. Each attempt has candidate-owned raw
evidence plus one run timing event. The validated Coach result always uses the
authoritative input policy as its parent-policy field; a model echo remains only
in raw/parsed evidence and cannot rewrite provenance.

Canonical state transition:

```text
(policy A1, code prompt B1, Java C1) -> (policy A2, code prompt B1, Java C1) -> Java C2
```

## Code Reflection

Code Reflection changes only `generation_prompt` (the code-generation gene):

```text
current policy + editable Java strategy region + immutable API guide
  -> Policy-Code Alignment Reviewer
  -> alignment review
current reusable rules + alignment review
  -> Code Prompt Rewriter
  -> structured rule delta
  -> deterministic replacement generation_prompt
```

The Reviewer receives policy plus only the Java between the strategy markers.
The immutable action/API guide is supplied separately so fixed helper semantics
are known without exposing fixed scaffold source as behavioral evidence.
Optional static/compiler evidence may explain structural failure. It never
receives raw game logs as evidence and does not propose a better game policy.
Each mismatch records the policy requirement, observed Java behavior, mismatch,
and required generation behavior. The Reviewer distinguishes a clear policy
violated by Java, an ambiguous policy, and faithful implementation. A bad but
faithfully implemented policy belongs to Strategy Reflection.

Reviewer fields are persisted and forwarded in canonical form. The parser
accepts a local model splitting one textual generation correction into a JSON
string array (or a documented text object) and joins it into the required
single string; it does not accept missing alignment fields, prose outside the
JSON object, Java output, or an unknown alignment classification.

The Code Prompt Rewriter receives only the current code-generation prompt, its
canonical reusable-rule view, Reviewer output, and immutable API guide. It
returns exactly `remove_rule_ids` and `add_rules`, with exactly one compact
12–240-character addition and at most one removal per mutation. Added rules use
a fixed category vocabulary and policy-agnostic prose: they cannot name a
concrete strategy, unit type, Java/API symbol, or fixed scaffold edit. Runtime
derives stable IDs, applies removals/additions in order, enforces a ten-rule
bound, and deterministically renders the replacement prompt. A semantic
validation failure remains a failed attempt; the next bounded attempt receives
the original request plus the exact validator error so it can produce a fresh
delta without runtime truncation, filtering, or partial application. A legacy
free-form prompt has no retained canonical rules and is therefore replaced
rather than copied when its first structured Code Rewrite succeeds.

Canonical state transition:

```text
(policy A1, code prompt B1, Java C1) -> (policy A1, code prompt B2, Java C1) -> Java C2
```

## Prompt Compliance Reflection

Prompt Compliance Reflection audits the active strategy and code-generation
prompt genes against the immutable MicroRTS gameplay contract and action/API
guide. It does not consume Java, compiler diagnostics, match records, aggregate
W/D/L data, fitness values, or raw traces, and it does not judge whether a
strategy is strong. Aggressive, defensive, economic, mixed, and unconventional
strategies are equally valid when all their rules are executable in the closed
game world.

The reflector separately identifies strategy-prompt violations—nonexistent
game concepts, unobservable conditions, illegal actions or production, and
implementation-blocking ambiguity—and generation-prompt violations such as
policy-specific instructions, unsupported API assumptions, immutable-scaffold
edits, or conflicting reusable rules. The exact source prompts, their canonical
reusable-rule view, and both immutable contracts are its complete evidence.

The resulting two rewrite calls are one atomic mutation. The Strategy Rewriter
corrects only compliance problems, preserves the intended strategy type, and
expresses every condition and response through observable state and legal game
actions. The Code Rewriter corrects the highest-priority compliance problem
through the same exact `remove_rule_ids`/`add_rules` delta used by Code
Reflection and receives both immutable contracts again; runtime validates and
canonically renders it. Both rewrites must
succeed before either gene changes. Historical malformed whole-prompt output is
treated as having no retained rules only at this rewrite boundary and is never
copied into the replacement.

```text
(policy A1, code prompt B1, Java C1)
  -> prompt genes + gameplay/API contracts -> Prompt Compliance Reflection
  -> strategy rewrite A2 + generation-prompt rewrite B2
  -> (policy A2, code prompt B2, Java C1) -> Java C2
```

## Selection and persistence

The configured static/AOS controller selects exactly one mutation operator.
Reward calculation changes neither responsibility boundary nor the ten-case
fitness contract.

For adaptive credit, `create_offspring()` records the same evaluated parent
used to construct mutation evidence as `comparison_parent_id`. Strategy routes
through policy provenance. Code and Prompt Compliance route through generation-prompt
provenance in default mode and inherited-Java provenance in inherited mode.
Direct-parent order and prompt-text equality never select the AOS baseline.

New artifacts live under:

```text
mutation/strategy_reflection/
mutation/code_reflection/
mutation/prompt_compliance_reflection/
```

Each directory retains requests, raw responses, parsed/scoped evidence,
attempts, errors, and timing. Full Java is canonical only at
`phenotype/CandidateAgent.java`; reflection metadata uses a path reference when
the request artifact already contains the needed Java evidence.

## Standalone reflection inspection

`eagle.reflection_inspection` runs outside the evolutionary loop for controlled
manual audits. It evaluates one configured checked-in Worker Rush parent, then
creates one fixed generation-one inherited-Java subject. Strategy, Code, and
Prompt Compliance Reflection each run independently from that same subject and typed
evaluation context; no trial consumes a previous trial's output. The configured
Strategy intent and context index also remain fixed, so repeated root requests
contain the same evidence while downstream Coach/Rewriter requests may differ
because they consume earlier stochastic role output.

Each trial retains the normal production mutation directory and adds a response
index, final genotype component files, unified diffs, and an expected-versus-
actual field-change summary. The inspection checks Strategy changes only the
policy prompt, Code changes only the generation prompt, Prompt Compliance changes both
atomically, and all three preserve inherited Java. A failed/retried response is
evidence rather than a discarded trial. Dedicated configs live under
`configs/reflection_inspections/`, and generated inspection runs live below the
ignored `runs/reflection_inspections/` tree.

For Code Reflection, default-mode evidence identifies the evaluated source
candidate's phenotype (`reviewed_phenotype_artifact`). In inherited mode the
Reviewer instead evaluates the child's current policy against its independently
selected inherited Java component; artifacts retain both its Java-parent
provenance and the exact inherited source. The Rewriter still changes only the
selected code-generation prompt.

After crossover, Strategy Reflection evidence comes from the recorded policy
parent. In default mode, Code and Prompt Compliance evidence comes from the recorded
code-generation-prompt parent, whose evaluated phenotype used the translation
gene being mutated. In inherited mode, Code and Prompt Compliance uses the
independently selected Java parent as its AOS comparison parent. Prompt text
equality is never used to choose evidence; the compliance audit itself always
examines the child's active prompt pair.

## Hard invariants

- Strategy mutation preserves `generation_prompt` exactly.
- Code mutation preserves `strategy_prompt` exactly.
- Prompt Compliance mutation changes both prompt genes only after its reflector and both
  rewrite stages succeed; its code rewrite is a validated reusable-rule delta,
  and otherwise it preserves both genes exactly.
- All mutation operators preserve inherited Java input exactly and never edit it directly.
- Generator and Evaluation preserve both prompt genes and the recorded
  pre-generation Java input exactly.
- Evidence routing tests use sentinels to prove Match Commentator/Coach exclude
  Java and code prompt, and Code Reviewer excludes raw game logs.
- Prompt Compliance receives only the two prompt genes and immutable gameplay/API
  contracts; it never receives outcome or implementation evidence.
