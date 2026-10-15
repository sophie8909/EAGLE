# Groq GPT-OSS framework and finite-slot evolution

`java_materialization_mode: framework_slots` is a two-stage execution mode. An
explicit bounded bootstrap operation asks Groq GPT-OSS to design a complete
Java agent framework and a finite control surface. A later EAGLE run freezes the
validated bundle and evolves only typed slot values. Groq is outside the
evolutionary loop; transport retries belong to the explicit bootstrap operation.

This document is the canonical owner of the framework-bundle, slot-domain, and
bootstrap boundary. The shared downstream Java and MicroRTS stages remain owned
by [Java generation](java_generation.md) and the
[evaluation pipeline](../evaluation/evaluation_pipeline.md).

## Evolution policy

`framework.evolution_mode` selects how complete `control_genome` values are
chosen. It defaults to `local`, preserving seeded local sampling, per-slot
crossover, and at-most-one-slot mutation. The opt-in `llm_coach` mode keeps the
same bundle schema, exact-byte run freeze, active genotype, renderer, and
materializer/protocol version (`eagle-framework-slots-v1`). The resolved mode is
part of run identity; resume rejects a mode mismatch.

Bootstrap remains an explicit preparation step: `python -m eagle framework`
uses the existing Groq GPT-OSS flow to design the Java framework and its rich
finite control surface. Bootstrap is never run by an experiment. The bootstrap
request targets at least 24 nonconstant slots, including at least six
`expression_choice` slots with at least four distinct choices each, covering
economy, production, targeting, combat, conditions, and priorities. These are
requested design targets; slot counts do not prove that evolved agents achieve
strategic diversity. Numeric domains remain finite lattices and formula domains
remain enumerated expressions. Once the run starts, the bundle bytes, Java
template, slot IDs, domains, and expressions are frozen.

With `llm_coach`, the configured experiment model selects one complete initial
genome for each generation-zero population slot and, when Strategy mutation is
assigned, proposes one complete replacement genome for that child. Strategy
mutation reuses the existing evidence path: use the evaluated mutation-context
parent (parent A), distinct from the per-slot crossover donors, select exactly
that parent's one worst completed match, have Match Commentator diagnose that
match, then give the Coach that diagnosis and the parent's all-match summary.
The Coach returns only the complete fixed-shape object below; it cannot
edit the Java template, bundle, slot schema, prompts, or arbitrary Java:

```json
{
  "schema_version": "eagle-framework-selection-v1",
  "framework_bundle_sha256": "<exact-byte frozen hash>",
  "control_genome": {
    "<every exact bundle slot_id>": "<one legal value for that slot>"
  }
}
```

The genome must contain every bundle slot exactly once. Numeric values must be
on their declared lattice; expression values must be declared `choice_id`
strings. Unknown or missing slot IDs, extra response keys, arbitrary Java,
prompt text, and values outside a slot's domain fail validation. Raw response
bytes are persisted before parsing, and every bounded attempt has request,
response, result, and timing evidence. Initial selection is candidate-owned under
`initialization/framework_coach/`; failed selection retains the sampled genome
and marks the candidate failed at `initialization`. Failed Strategy mutation
preserves the child's complete pre-Coach genome and lineage, then marks it failed
at `reflection`; it never substitutes a random genome or partially applies a
response. `slot_parent_ids` continues to describe the pre-mutation genotype's
slot sources, while Coach metadata and its result artifacts record the complete
selected genome, changed slot IDs, and evidence parent.

`llm_coach` makes no candidate-time Java-generation, Code Reflection, source
repair, or compile-repair request. Its only candidate-time LLM work is initial
genome selection and the existing Commentator/Coach Strategy path. Rendering
and Java validation remain local and deterministic.


## Minimal use

Create and review the framework explicitly; the default model is the existing
Groq GPT-OSS bootstrap model:

```bash
python -m eagle framework --output runs/framework_bootstrap/my_framework --brief "Design a complete CandidateAgent framework with a rich finite control surface."
```

Start from an ordinary experiment config that already contains the desired
`model` profile and add this fragment:

```yaml
java_materialization_mode: framework_slots
framework:
  bundle_path: runs/framework_bootstrap/my_framework/bundle.json
  evolution_mode: llm_coach
```

Then run that config through the usual `python -m eagle experiment` or
`./experiment.sh` entrypoint. Omitting `evolution_mode` keeps the local EA
behavior. The experiment never invokes the bootstrap command.

## Two-stage boundary

1. An operator runs `python -m eagle framework` with a design brief and new
   output directory. The command defaults to `openai/gpt-oss-120b`; `--model`
   selects an override. `GROQ_API_KEY` is read from the environment only.
2. The bootstrap sends the checked-in `groq_framework_design` prompt to
   `https://api.groq.com/openai/v1/chat/completions` with Bearer authorization.
   The request includes user-message content, model, temperature,
   `max_completion_tokens`, and `response_format` JSON Schema named
   `eagle_framework` with `strict: false`. Strict mode cannot express dynamic
   keys in the preserved `report.slot_rationale` map. Provider schema enforcement
   is best-effort; local exact validation remains authoritative. Retries are
   bounded, and raw responses are persisted before parsing.
3. EAGLE validates and normalizes the response into one
   `eagle-framework-bundle-v1` `bundle.json`. The output also retains the exact
   rendered bootstrap prompt, request bodies, raw responses, timing, hashes,
   generated template, slot-generation prompt, and structured report.
4. An experiment config selects that file through `framework.bundle_path`.
   Config resolution records its exact byte SHA-256 and schema version. Run
   creation copies the validated bundle into run-owned evidence and freezes the
   same hash. Resume must use the run-frozen bytes and reject a version or hash
   mismatch.
5. In `local`, generation zero samples legal values and later seeded EA
   operators cross over values independently by slot and mutate at most one slot
   to another legal value. In `llm_coach`, the experiment model selects complete
   generation-zero genomes and returns a complete genome for each assigned
   Strategy mutation. Rendering replaces every declared marker exactly once.
6. The complete rendered Java follows the existing validation, one-attempt
   `javac`, Integration, semantic-probe, and evaluation pipeline. Fixed-roster
   evaluation is still ten opponents x three maps x three rounds x two sides,
   or 180 matches per successfully evaluated candidate.

The bootstrap is an explicit preparation action, never an implicit experiment
startup action. Reusing a bundle for multiple runs makes the framework constant
across their EA seeds; generating a new bundle is a new experimental condition.

## Exact bundle schema

The top-level object has exactly these keys:

```json
{
  "schema_version": "eagle-framework-bundle-v1",
  "framework_id": "nonempty_stable_identifier",
  "java_template": "complete ai.generated.CandidateAgent source",
  "slots": [],
  "slot_generation_prompt": "nonempty prompt explaining how the finite slots were chosen",
  "report": {}
}
```

Each `slots` entry has exactly these keys:

```json
{
  "slot_id": "lower_snake_case",
  "kind": "integer | number | expression_choice",
  "marker": "{{EAGLE_SLOT:<slot_id>}}",
  "default": 0,
  "minimum": 0,
  "maximum": 10,
  "step": 1,
  "choices": [],
  "purpose": "nonempty explanation"
}
```

An `integer` or `number` slot has finite numeric `default`, `minimum`, `maximum`,
and positive `step`; its range is exactly divisible by `step`, its default lies
on that lattice, and `choices` is empty. An `expression_choice` has string
`default`, null `minimum`/`maximum`/`step`, and a nonempty finite `choices` list.
Each choice has exactly:

```json
{
  "choice_id": "lower_snake_case",
  "java_expression": "one complete predeclared Java expression",
  "description": "nonempty explanation"
}
```

Candidate genomes store the `choice_id`; deterministic materialization substitutes
the corresponding `java_expression`. Formula evolution therefore means choosing
among reviewed, bundle-frozen expressions. Candidates cannot synthesize arbitrary
Java, expression text, identifiers, statements, methods, or prompts.

`java_template` is a complete `ai.generated.CandidateAgent` extending
`AbstractionLayerAI`. Every slot marker is canonical, declared once, appears
exactly once in the template, and lies inside the single editable strategy
region. Undeclared, duplicate, malformed, or unresolved markers are invalid.

## Exact report and prompt contract

`report` has exactly these keys:

```json
{
  "architecture_summary": "nonempty string",
  "decision_flow": ["nonempty string"],
  "invariants": ["nonempty string"],
  "slot_rationale": {
    "<exact slot_id>": "nonempty string"
  },
  "assumptions": ["nonempty string"],
  "risks": ["nonempty string"]
}
```

`slot_rationale` is an object whose keys are exactly the declared slot IDs. The
other lists may be empty, but every item they contain is nonempty. The report is
audit evidence; it does not alter selection, rendering, or evaluation.

The checked-in bootstrap prompt is `prompts/groq_framework_design.txt`,
registered as `groq_framework_design` in `prompts/manifest.toml`. Its exact
rendering inputs are `design_brief`, `gameplay_contract`, and `action_api_guide`.
It instructs the model to return the exact bundle above and to place in
`slot_generation_prompt` the reusable instructions that guided the finite
control-surface design. The stored prompt is explanatory provenance only after
bootstrap: candidate generation, mutation, repair, and evaluation never execute
it.

## Candidate and local EA contract

The active genotype is exactly `control_genome`. It maps every declared slot ID
to one valid domain value and contains no unknown or missing key. Candidate
snapshots pin `framework_bundle_sha256`; lineage records `slot_parent_ids` for
every slot. Framework source, report, and prompt are immutable run input, not
candidate genes.

In `local`, generation-zero sampling and variation derive independent per-slot
RNG streams from the experiment seed and stable identities. Uniform crossover
chooses each slot from one parent and retains exact slot provenance. Mutation
selects at most one mutable slot and chooses a different legal lattice point or
expression choice. Equal seed, bundle, parents, generation, and child index must
produce the same genome and source bytes regardless of mapping insertion order
or worker completion order. In `llm_coach`, initial selection and Strategy
mutation return complete validated genomes; their external model outputs are
recorded with exact bundle-hash and slot-domain validation evidence.

This mode requires:

- `candidate_java_mode: generated_phenotype`;
- `parent_evaluation_mode: reuse_cached`;
- `reflection_operator_mode: static`;
- evolution protocol and materializer version `eagle-framework-slots-v1`;
- active genotype metadata `['control_genome']`.

With `framework.evolution_mode: local`, the EA performs no candidate-time
provider or other LLM request. Strategy Reflection, Prompt Reflection, Code
Reflection/source gating, Java Generation, and compile-guided repair are all
disabled. Under `llm_coach`, only initial genome selection and the
Commentator/Coach Strategy path make candidate-time requests; Prompt Reflection,
Code Reflection/source gating, Java Generation, source repair, and compile
repair remain disabled. A render, validation, or compilation failure remains at
its actual stage with hashes and diagnostics; it never falls back to an LLM.

## Bootstrap artifacts and security

The standalone bootstrap output is:

```text
<output>/
|-- prompt.txt
|-- bundle.json
|-- CandidateAgent.template.java
|-- slot_generation_prompt.txt
|-- report.json
|-- bootstrap.json
`-- attempts/
    `-- attempt_NNN/
        |-- request.json
        |-- response_raw.json
        `-- result.json
```

`response_raw.json` is written before provider-envelope or generated JSON
parsing. Attempt records include UTC boundaries, monotonic duration, status,
retryability, HTTP status, model/endpoint, redacted error, and request/response
SHA-256. `bootstrap.json` identifies the selected attempt and exact published
bundle bytes. The command refuses a nonempty output directory.

Credentials are never accepted in YAML or CLI arguments, embedded in request
bodies, or persisted in any artifact. Only the HTTP Bearer authorization header
receives `GROQ_API_KEY`; stored errors redact that value. Bundle content is
untrusted generated input until strict schema, Java-envelope, marker, normal
validation, `javac`, and Integration checks succeed.

During a run, candidate evidence must make the result reconstructible from the
run-frozen bundle, `control_genome`, materializer version, and hashes. Partial
materialization evidence survives failure. Resume starts only from an atomic
generation, reloads the run-owned bundle, verifies its byte hash and version,
and rejects external bundle drift rather than silently adopting it.

## Unchanged downstream semantics

Framework slots change only genotype construction and deterministic Java
materialization. They do not change the Java security envelope, compiler or
Integration checks, fixed/self-play match scheduling, Game Performance,
opponent-wise lexicase, survivor selection, semantic diagnostics, failure
sentinels, final test, or match evidence ownership. The generated framework has
more architectural freedom than the fixed DSL compiler, but every evolved
degree of freedom remains finite, explicit, typed, and reconstructible.
