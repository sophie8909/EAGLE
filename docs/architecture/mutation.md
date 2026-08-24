# Mutation responsibility boundaries

EAGLE has two mutation operators because it searches two different spaces.
Strategy Reflection searches policy space; Code Reflection searches reusable
policy-to-code translation instructions. Both stop at a prompt gene. The
Generator remains a separate genotype-to-phenotype stage.

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
raw/compact trace. It receives no Java, code-generation prompt, compiler
diagnostics, or fitness-writing task. It analyzes one game and reports observed
strategies, turning points, strengths, weaknesses, and decisive causes.
The response boundary validates the canonical MatchAnalysis schema and performs
only bounded structural normalization: a full `match_analysis` wrapper may be
unwrapped, strategy summaries may be strings, and `key_observations.time` ranges
may supply the first tick. A response still fails when it has no numeric
tick-backed turning point or crosses the role boundary.

The Coach receives the current policy, selected MatchAnalysis summaries, and
the existing global evaluation/selection metadata. It receives no Java or
code-generation diagnostics. Its replacement policy describes economy,
production, attack timing, defense, expansion, and targeting—not Java.

Canonical state transition:

```text
(policy A1, code prompt B1) -> (policy A2, code prompt B1) -> Java phenotype P2
```

## Code Reflection

Code Reflection changes only `generation_prompt` (the code-generation gene):

```text
current policy + current Java phenotype
  -> Policy-Code Alignment Reviewer
  -> alignment review
current code-generation prompt + alignment review
  -> Code Prompt Rewriter
  -> replacement generation_prompt
```

The Reviewer receives policy plus Java. Optional static/compiler evidence may
explain structural failure. It never receives raw game logs as evidence and
does not propose a better game policy. Each mismatch records the policy
requirement, observed Java behavior, mismatch, and required generation
behavior. The Reviewer distinguishes a clear policy violated by Java, an
ambiguous policy, and faithful implementation. A bad but faithfully implemented
policy belongs to Strategy Reflection.

Reviewer fields are persisted and forwarded in canonical form. The parser
accepts a local model splitting one textual generation correction into a JSON
string array (or a documented text object) and joins it into the required
single string; it does not accept missing alignment fields, prose outside the
JSON object, Java output, or an unknown alignment classification.

The Code Prompt Rewriter receives only the current code-generation prompt and
Reviewer output. It returns one replacement code-generation prompt and cannot
modify policy.

Canonical state transition:

```text
(policy A1, code prompt B1) -> (policy A1, code prompt B2) -> Java phenotype P2
```

## Selection and persistence

The configured static/AOS controller selects exactly one mutation operator.
Reward calculation changes neither responsibility boundary nor the seven-case
fitness contract.

New artifacts live under:

```text
mutation/strategy_reflection/
mutation/code_reflection/
```

Each directory retains requests, raw responses, parsed/scoped evidence,
attempts, errors, and timing. Full Java is canonical only at
`phenotype/CandidateAgent.java`; reflection metadata uses a path reference when
the request artifact already contains the needed Java evidence.

For Code Reflection, that reference identifies the evaluated source
candidate's phenotype (`reviewed_phenotype_artifact`). This is the previous
program in the reviewer workflow, but it remains evidence: it is not copied
into the child genotype and is not supplied to the Generator.

After crossover, Strategy Reflection evidence comes from the recorded policy
parent. Code Reflection evidence comes from the recorded code-generation-prompt
parent, so the reviewed policy/Java pair is the evaluated source that actually
used the translation gene being mutated. Prompt text equality is never used to
choose evidence.

## Hard invariants

- Strategy mutation preserves `generation_prompt` exactly.
- Code mutation preserves `strategy_prompt` exactly.
- Neither mutation directly edits Java.
- Generator and Evaluation preserve both prompt genes exactly.
- Evidence routing tests use sentinels to prove Match Commentator/Coach exclude
  Java and code prompt, and Code Reviewer excludes raw game logs.
