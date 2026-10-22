# Framework bootstrap and finite-slot evolution

`java_materialization_mode: framework_slots` uses a configurable fresh-run
bootstrap when no external bundle is configured, then evolves only typed slot
values. Startup
validates the generated framework, writes it under the run-owned `framework/`
directory, and freezes its exact bytes and hash before search. API bootstrap is
outside the evolutionary loop; bounded retries belong to startup bootstrap.
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

In `llm_coach`, optional `framework.coach_offspring_probability` selects the
Coach offspring route before crossover. `null` (the default) preserves legacy
Coach behavior for existing configurations; a numeric value from `0.0` through
`1.0` routes that fraction of offspring to Coach. This choice is independent of
`mutation_rate`; selection is stochastic per offspring, not an exact
per-generation quota, and uses an independent seeded RNG. A Coach-routed child
copies parent A's genome and asks Coach for a complete genome, without
crossover or parent B. A traditionally routed child uses the configured
`crossover_rate` and existing donor-selection behavior, followed by the local
single-slot mutation at `mutation_rate`. These are
exclusive offspring routes, not a Coach-versus-local-mutation choice. At `0.0`
all offspring use the traditional route; at `1.0` all use Coach. Generation-zero
genomes remain Coach-selected in `llm_coach` regardless of this setting. The
resolved probability is resume-fenced; older manifests without the field mean
`null`, and changing it requires a new run.

Without `framework.bundle_path`, fresh startup requires `framework.design_brief`
and optionally accepts `framework.model` (default `openai/gpt-oss-120b`).
`framework.bootstrap_backend` selects `groq` (the default API path), `mistral`
(the Mistral API path), or `local` (the configured local llama-server, without
an API key). The standalone
`python -m eagle framework` command remains available to prepare an external
bundle for reuse. The bootstrap requests at least 24
nonconstant slots, including at least six `expression_choice` slots with at least
four distinct choices each, covering economy, production, targeting, combat,
conditions, and priorities. These are requested design targets, not a guarantee
of strategic diversity. Once the run starts, bundle bytes, template, slot IDs,
domains, and expressions are frozen.
With `llm_coach`, the configured experiment model selects one complete initial
genome for each generation-zero population slot. Under legacy
`coach_offspring_probability: null` behavior, an assigned Strategy mutation
proposes one complete replacement genome after crossover. With an explicit
numeric probability, Coach is a separate offspring operator selected before
crossover; it copies parent A and has no parent-B donor. Both Coach paths reuse
the existing evidence protocol: select exactly the evaluated mutation-context
parent's (parent A's) one worst completed match, have Match Commentator
diagnose that match, then give the Coach that diagnosis and the parent's
all-match summary.
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

Put the design brief and bootstrap model in the experiment config. The model is
optional and defaults to `openai/gpt-oss-120b`; the API key stays in the process
environment:

```yaml
java_materialization_mode: framework_slots
reflection_operator_mode: static
framework:
  bootstrap_backend: mistral  # groq, mistral, or local
  design_brief: "Design a complete CandidateAgent framework with a rich finite control surface."
  model: mistral-small-latest
  evolution_mode: llm_coach
  coach_offspring_probability: 0.5  # Exclusive Coach and traditional offspring routes
```

For `groq`, set `GROQ_API_KEY` in the environment. For `mistral`, EAGLE reads
the key from `api_key/mistral`. For `local`, the top-level experiment `model`
profile supplies the already managed llama-server and no API key is read. Start
the ordinary experiment with
`python -m eagle experiment --config-dir configs/experiments/framework.yaml` or
`./experiment.sh configs/experiments/framework.yaml`. The top-level experiment
`model` still configures the experiment runtime. Omit `evolution_mode` for the
local EA. For mock/offline runs, provide an existing `framework.bundle_path`;
mock mode rejects an inline brief without that bundle. An explicit shared bundle
path also holds the framework constant across replicate seeds. The standalone
`python -m eagle framework` command remains available to prepare that bundle.

The repository includes a ready-to-run fixed-initialization example at
`configs/framework_coach_mock.yaml`. It uses the real checked-in
`configs/framework_bundles/fixed_worker_combat/bundle.json`, which contains a
complete compilable `CandidateAgent` scaffold and 27 finite controls across
economy, construction, production, army composition, attack timing, targeting,
rallying, fallback, and defense. The explicit `bundle_path` skips only fresh
framework bootstrap; `execution_mode: openai` and
`framework.evolution_mode: llm_coach` retain normal EA LLM calls through the
managed local primary plus the configured additional endpoint. Java compilation,
Integration, semantic probes, and MicroRTS scoring remain enabled.

## Startup and evolution boundary

1. On a fresh run without `bundle_path`, startup requires `design_brief`, calls
   the backend selected by `framework.bootstrap_backend` (default `groq`) with `framework.model` (default
   `openai/gpt-oss-120b`), and writes bootstrap evidence under run-owned
   `framework/`. `GROQ_API_KEY` is read only for `groq`; `api_key/mistral` is
   read only for `mistral`; the local backend reads no API key. Each fresh
   replicate designs a separate framework unless it uses the same explicit
   `bundle_path` as the other replicates.
2. The Groq backend sends the checked-in `groq_framework_design` prompt to
   `https://api.groq.com/openai/v1/chat/completions` with Bearer authorization.
   The Mistral backend sends the same prompt to
   `https://api.mistral.ai/v1/chat/completions` with Bearer authorization and
   uses Mistral JSON Object Mode with `max_tokens`. The local backend sends the
   same prompt to the configured local
   `llama-server/v1/chat/completions` endpoint without authorization and starts
   with the framework JSON Schema plus `chat_template_kwargs.enable_thinking: false` so
   the Qwen reasoning channel does not consume the framework output budget. The
   first Groq request uses the `eagle_framework` JSON Schema. If Groq returns
   `json_validate_failed`, EAGLE retains that raw response and performs a
   bounded retry in JSON Object Mode; local bundle validation remains
   authoritative. On failure, attempt artifacts and a failed manifest remain
   with the pending config. The failed run cannot resume until a valid frozen
   bundle exists; the unsuccessful replicate is not added to the folder-batch
   index, so a folder rerun can retry the missing slot.
3. EAGLE validates and normalizes one `eagle-framework-bundle-v1` bundle. The
   run-owned framework directory retains the exact prompt, request bodies, raw
   responses, timing, hashes, generated template, slot prompt, report, and
   manifest.
4. With an explicit `bundle_path`, config resolution validates that external
   file. Otherwise, startup generates the bundle in the run-owned directory.
   Both paths freeze exact bytes and hash before search. Resume reads only that
   frozen bundle, checks its version/hash, compares `design_brief`, bootstrap
   backend/model, and `evolution_mode`, and never regenerates a framework.
5. In `local`, generation zero samples legal values and later seeded EA
   operators cross over values independently by slot and mutate at most one slot.
   In `llm_coach`, the experiment model selects complete initial genomes.
   Legacy `null` Coach behavior returns a complete genome for each assigned
   Strategy mutation; an explicit numeric setting selects the exclusive Coach
   offspring operator before crossover.
6. Rendered Java follows the existing validation, one-attempt `javac`,
   Integration, semantic-probe, and evaluation pipeline. Fixed-roster evaluation
   remains ten opponents x three maps x three rounds x two sides (180 matches
   per successfully evaluated candidate).

The standalone bootstrap command remains a compatibility path for preparing a
bundle to use through `framework.bundle_path`. Both inline and external bundles
use the same frozen run artifact contract.
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

Standalone bootstrap outputs use this layout; inline run bootstrap stores the same evidence under the run-owned `framework/` directory:

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

Failed bootstrap attempts and manifest remain while config is pending; resume requires a usable frozen bundle. Each fresh replicate designs its own framework unless replicates share an explicit `bundle_path`. Provider credentials remain outside config and artifacts. Credentials are never accepted in YAML or CLI arguments, embedded in request
bodies, or persisted in any artifact. Only the HTTP Bearer authorization header
receives the selected provider key; stored errors redact that value. Bundle content is
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
