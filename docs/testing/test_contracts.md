# Test contracts

Tests must prove the normative architecture, not preserve accidental current structure. Read the canonical document for every changed responsibility.

## Standard command

Run from either native Ubuntu Linux or WSL2 Ubuntu, with the checkout inside the
Linux filesystem:

```bash
cd ~/EAGLE
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
| Matches | compile once; same source/class hash; exactly 10 roster matches (5 vendored basic, 5 vendored pathfinding variants); distinct directories/seeds; no regeneration |
| Game Performance | exact canonical component math, clamps, bands, aggregation, partial-batch failure |
| Code Quality | `[0,100]` simplicity score from four weighted complexity penalties, persisted details, diagnostic separation, and `-1000` failure sentinel for both objectives |
| Artifacts | golden tree, schemas, hashes, resolved config, readback reconstruction, interruption safety; generation/final snapshots preserve fitness and timing while excluding raw match output and full mutation envelopes; evolution writes no duplicate `results.jsonl` or flat population snapshot |
| Timing | UTC fields, monotonic durations, attempts, optional null stages, 10 match durations |
| Opponent-wise lexicase | exactly ten maximized opponent cases; seeded case-order filtering; fixed-size elite plus lexicase survivor behavior |
| Adaptive Operator Selection | Lexicase selects parents; AOS selects two reflection operators; parent A is the explicit comparison parent; runnable offspring use 18 direct map/round/side matches and `[0,1]` W/D/L reward; failed offspring skip matches for reward `0`; seven-case fitness separation, EMA, floor, generation update, artifacts, and analysis totals are covered |
| Operations | readers reject/migrate unsupported schema versions; legacy names never leak into active output |
| Offline analysis | explicit/latest run resolution is deterministic; only direct canonical children are eligible; partial runs produce derived outputs; unsupported or historical schemas fail explicitly; `results.jsonl` is never read |
| LLM server lifecycle | missing executable/model; immediate exit; bounded loading/readiness; occupied port; bind/client host separation; local/remote launch ownership; durable stdout/stderr; useful failure state; process-group stop; topology/client URL identity; no READY on process creation |

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

Server-management tests must cover explicit CPU/CUDA/remote backend resolution, capability rejection of CPU-only binaries in CUDA mode, device-list parsing, logical GPU-layer/VRAM-fit argument mapping, and the invariant that CPU commands contain no GPU-specific arguments.

Focused runtime tests must prove that the default GGUF path is accepted, a
direct `--model` override is accepted, the selected model is passed to
llama.cpp, unrelated processes are never stopped, and all EA LLM operations
use the same endpoint/model identity.
