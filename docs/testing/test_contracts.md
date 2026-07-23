# Test contracts

Tests must prove the normative architecture, not preserve accidental current structure. Read the canonical document for every changed responsibility.

## Standard command

Run from WSL:

```bash
cd /mnt/d/Project/EAGLE
python3 -m unittest discover -s tests
```

Use narrower test modules while iterating, then run the full suite. A real MicroRTS/Java check must be bounded and explicitly identified; do not run an evolutionary experiment as validation.

## Contract matrix

| Area | Required proof |
| --- | --- |
| Candidate | all required logical fields; pre/post Java separation; terminal failure retains state |
| Lineage | seed/copy/crossover/mutation schemas; IDs resolve; graph acyclic |
| Crossover | independent component selection; latest evaluated Java; exact provenance; equal-text case |
| Strategy Mutation | Reflection ??Strategy Rewrite ??final Java generation; only strategy changes; full game evidence |
| Code Mutation | Reflection ??Generation Prompt Rewrite ??final Java generation; only generation prompt changes; full failure/code evidence |
| Generation | complete-file only; raw response durability; no direct patches/body maps |
| Validation | exact `ai.generated.CandidateAgent` package/class/superclass, both constructors, required `getAction`/`reset`/`clone`, security restrictions, and no fixed internal layout |
| Compilation | isolated output; warning flags; diagnostic parsing/deduplication |
| Integration | all seven ordered load/type/two-constructor/reset/clone/getAction/PlayerAction checks; `passed`/`failed`/`blocked`; no match execution |
| Matches | compile once; same source/class hash; exactly 10 LightRush matches; distinct directories/seeds; no regeneration |
| Final Test | pinned revision and interrupted-checkout recovery; explicit adapter hashes; selection before matches; both sides; exact counts; compile once; stable hashes; no LLM/evolutionary operators; aggregation and incomplete rejection; real three-champion smoke |
| Game Performance | exact canonical component math, clamps, bands, aggregation, partial-batch failure |
| Code Quality | selected `+500` base, `[0,610]` range, warning/capability/alignment components, formula version, and failure ordering |
| Artifacts | golden tree, schemas, hashes, resolved config, readback reconstruction, interruption safety |
| Timing | UTC fields, monotonic durations, attempts, optional null stages, 10 match durations |
| NSGA-II | exactly two maximized objectives; failure candidates retained; rank/crowding survivor behavior |
| Operations | readers reject/migrate unsupported schema versions; legacy names never leak into active output |

## Failure fixtures

Maintain deterministic fixtures for:

- backend/empty/extraction failure;
- source validation failure;
- compilation failure with controlled error counts;
- each of the seven integration-check failures and prerequisite-blocked states;
- runtime failure after 0, 5, and 9 matches;
- successful win/draw/loss batches;
- mutation Reflection failure, Rewrite failure, and final generation failure;
- artifact write interruption where supported.

Each fixture asserts both objectives, terminal stage, retained artifacts, and timing closure.

## Test quality rules

- Prefer typed fixtures and exact persisted payloads over checking console prose.
- Do not make fixed helper names, strategy markers, code length, or function count a contract unless the normative spec is changed.
- Mock LLM calls must record stage/order/attempts and return realistic raw payloads.
- Test no-regeneration by counting backend calls and comparing source hashes across matches.
- Test formulas only in their canonical test module; other tests assert references/results, not copied arithmetic.
- Use a schema-version fixture for every supported legacy reader.
- A mock search is a smoke test, not proof of real Java/MicroRTS integration.

## Documentation completion

When tests reveal a code/spec discrepancy, update [`../implementation/architecture_gaps.md`](../implementation/architecture_gaps.md). When documented behavior changes by explicit decision, update the authoritative/canonical docs and the Chinese overview according to [`../README.md`](../README.md).
## Dual-host LLM deployment

Focused tests must prove that coder-profile updates preserve the general section, general-profile updates preserve the coder section, updates are atomic, placeholder or unsafe coder URLs are rejected, aliases and ports may differ, and stage identity records Reflection/Rewrite as general and Generation as coder. Single-machine tests must opt into coder loopback explicitly.
