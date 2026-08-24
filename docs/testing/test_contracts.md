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
| Candidate | exactly two prompt genes; generation-qualified automatic IDs and explicit-ID preservation; Java phenotype separation; terminal failure retains state |
| Lineage | seed/copy/crossover/mutation schemas; IDs resolve; graph acyclic |
| Crossover | two independent whole-component choices; exact provenance; equal-text case; no Java inheritance |
| Strategy Mutation | Commentator per selected match → Coach → final Java generation; only policy changes; no Java/code-prompt evidence |
| Code Mutation | Policy-Code Reviewer → exact `rewritten_prompt` JSON object → final Java generation; only code-generation prompt changes; no raw game logs |
| Generation | blank-policy checked-in Java seed at generation zero; later two genes + fixed scaffold/API constraints; base retry only after extraction failure; compile-guided retry from the immediately previous complete failed source and structured diagnostics; unchanged genes/lineage/AOS; per-attempt request hashes and interruption-safe evidence; deterministic fixed-scaffold/non-diagnostic drift guard; first compile success selected; failed source is not phenotype; no game logs |
| Validation | exact `ai.generated.CandidateAgent` package/class/superclass, both constructors, required `getAction`/`reset`/`clone`, security restrictions, direct strategy-map reads rejected in favor of bounds-safe `isFreeCell`, and no fixed internal layout |
| Compilation | attempt-isolated output; each validated source compiled at most once; first success promoted without recompilation; warning flags; diagnostic parsing/deduplication |
| Integration | all seven ordered load/type/two-constructor/reset/clone/getAction/PlayerAction checks; two populated real 8×8 maps, independent one-argument instances/states for both sides, action integrity plus safe issuance/cycle; `passed`/`failed`/`blocked`; no match execution or decoder retry |
| Matches | one promoted source/class tree; complete configured matrix with a real distinct WorkerRush; population-summed generation counts; distinct directories and round indices; both sides; no fake match-seed property; no regeneration after Integration starts |
| Game Performance | exact canonical component math, clamps, bands, aggregation, partial-batch failure |
| Code Quality | `[0,100]` simplicity score from four weighted complexity penalties, persisted details, diagnostic separation, and `-1000` failure sentinel for both objectives |
| Artifacts | v2 root allowlist; one resolved `config.yaml`; referenced generation/candidate reconstruction; interruption safety; absence of obsolete config, population, candidate-summary, and match-result duplicates |
| Timing | UTC fields, monotonic durations, attempts, optional null stages, 126 match durations |
| Opponent-wise lexicase | exactly seven maximized opponent cases; seeded case-order filtering; offspring-first fixed-size lexicase survivor behavior |
| Reflection operator selection | Exactly `static`, `aos_opponent`, and `aos_head2head`; config validation and resume identity; fixed static probabilities with no credit matches; historical execution-first seven-case rank reward without direct matches; configured head-to-head matrix with `[0,1]` W/D/L reward; shared EMA/floor; common artifacts and mode-labelled analysis |
| Operations | shell positional mapping; sorted non-recursive directory batch; single YAML; folder resume prioritizes incomplete indexed runs, skips complete entries, and continues unindexed configs; final-test-only recovery avoids LLM startup; mock port isolation; start/reuse/switch/owned-stop ordering; failure/interrupt cleanup; foreign-process safety; stale-state reconciliation; experiment-state isolation; skip-final-test |
| Offline analysis | explicit/latest run resolution is deterministic; only direct canonical children are eligible; partial runs produce derived outputs; unsupported or historical schemas fail explicitly; `results.jsonl` is never read |
| LLM server lifecycle | missing executable/model; bounded readiness; occupied port; configured endpoint identity; durable logs; and stopping only the process created by the experiment orchestrator |

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
- Test compile-guided decoding as a chain: extraction-only retries preserve the
  base request, while validation/javac failures produce distinct requests that
  contain both authoritative genes, immutable API/scaffold, only the immediately
  previous source and diagnostics, and matching request/source hashes. Exhaustion
  must leave `selected_attempt: null` and no phenotype.
- Use sentinel-based structural tests to prove Commentator/Coach exclude Java,
  Code Reviewer excludes raw game logs, and both mutation operators preserve the
  gene they do not own.
- Keep regression fixtures for observed structured-output variants: wrapped
  Commentator analyses with tick ranges and Reviewer generation corrections
  split into arrays. Assert their canonical parsed form as well as rejection of
  missing evidence and responsibility-boundary violations.
- Test formulas only in their canonical test module; other tests assert references/results, not copied arithmetic.
- Unsupported run schemas must fail explicitly; no legacy reader may silently activate.
- Compact v3 analysis fixtures must prove candidate references recover
  `opponent_results.match_scores` from the canonical evaluation artifact as
  narrow per-generation violin distributions while
  leaving bulky raw per-match payloads out of the in-memory analysis view.
- A mock search is a smoke test, not proof of real Java/MicroRTS integration.

## Documentation completion

When tests reveal a code/spec discrepancy, update [`../implementation/architecture_gaps.md`](../implementation/architecture_gaps.md). When documented behavior changes by explicit decision, update the authoritative/canonical docs and the Chinese overview according to [`../README.md`](../README.md).
Focused runtime tests prove that the selected experiment GGUF is passed to
llama.cpp, an identical folder-batch runtime is started only once, A/A/B/B/A
switching is exact, PID reuse cannot satisfy ownership, unrelated processes are
never stopped, verified stale state is cleaned, and all EA LLM operations use
the same resolved endpoint/model identity. Actual shell and direct-Python mock
commands remain required workflow checks in addition to unit tests.
