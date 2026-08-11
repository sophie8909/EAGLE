# Current implementation status

Snapshot: 2026-08-11 after the four-entrypoint cleanup. This file describes active source/tests/configuration. It is not normative. Historical runs use legacy artifact layouts and are rejected by the canonical readers.

## Status summary

| Area | Active behavior | Contract alignment |
| --- | --- | --- |
| Candidate | Frozen `Candidate` retains the pre-generation `strategy_prompt`, `previous_code`, and `generation_prompt`, stores normalized output separately as `generated_java`, and exposes first-class identity, operator, mutation, component provenance, failure, artifact, and timing fields. | The Phase 1 genotype/phenotype boundary and Phase 2 mutation state transitions are implemented; later validation/integration/match stages remain outside this milestone. |
| Java generation | One request asks for complete `ai.generated.CandidateAgent`; raw/fenced source is normalized and written once. | Complete-file boundary exists. Validation imposes a fixed template/marker/action-helper layout not required by the spec. |
| Crossover | `eagle/crossover.py` independently chooses all three components, takes Previous Code from the selected parent's `generated_java`, and records each selected parent ID. Search feedback routing uses recorded provenance rather than prompt equality. | Phase 1 inheritance and component provenance are implemented and deterministic under the EA RNG. |
| Mutation | Strategy and Code mutations use Reflection followed by prompt-only Rewrite and the existing final Java Generation stage. Rewritten prompts are candidate state; inherited previous Java remains distinct from the generated phenotype. | Phase 2C is implemented; later validation/integration/match stages remain outside this milestone. |
| Selection | Binary tournament, Pareto sorting, crowding distance, and elitist parent+offspring survivors operate on two objective values. | Broadly aligned; population manifests and tie behavior need contract tests. |
| Validation | Checks exact `ai.generated.CandidateAgent` identity, both constructors, `getAction`/`reset`/`clone`, forbidden capabilities, and unavailable imports with structured passed/failed/blocked results. | External runtime/security contract is implemented without fixed helper names, markers, or internal layout. |
| Compilation | Runs `javac -Xlint:all` in an isolated candidate directory with the MicroRTS classpath and persists stdout/stderr/command. | Structured, deduplicated diagnostics with severity/code/file/line/column are implemented; objective scoring remains a later milestone. |
| Integration | Runs a standalone seven-check MicroRTS probe (load, inheritance, constructors, reset, clone, getAction, PlayerAction) before matches, with fail-fast routing and timing/artifacts. | Implemented for mock and bounded real runtime probes; weighted 180/198 map-round-side execution follows the probe. |
| Match protocol | After standalone Integration, one source/class hash pair runs ten independently seeded weighted matches against the canonical search roster; generation 1+ appends one frozen previous-generation champion match. Each match persists complete result, telemetry, logs, replay/round-state references, failure, weight, and timing. | Phase 4 protocol plus weighted adaptive opponent evaluation is implemented; no generation, mutation, validation, compilation, or integration work occurs inside the match batch. |
| `game_performance` | Canonical +100/0/-100 result scoring plus bounded tanh material/resource and survival shaping is averaged over 18 records per opponent, then normalized by the fixed weights over 180 matches (198 with the dynamic champion). | Implemented by `evaluation/game_performance.py` and `evaluation/game_metrics.py`; partial/invalid matrices yield -1000. |
| `code_quality` | Successful evaluation uses `100 - complexity_penalty`; complexity is weighted 40/25/20/15 for cyclomatic/nesting/logical LOC/longest function. All failure stages use `-1000` for both objectives. | Implemented with versioned `code_quality_details`; compiler, capability, validation, runtime, and alignment data remain diagnostics. |
| Failure handling | Runtime exception, illegal action, timeout, deadlock, crash, invalid/missing result, and partial evaluation are classified with retained match evidence. | Generation/validation/compilation/integration/runtime classification is implemented; every failure receives both objective values `-1000`. |
| Artifacts | Candidates persist canonical Phase 4 evaluation summaries, per-match artifacts, runtime failures, capability evidence, Strategy Alignment request/raw/parsed result, objective values, and schema/formula versions. | Evaluation-layer persistence and the active canonical candidate layout are implemented. |
| LLM logging | Final-generation, Reflection, Rewrite, and Strategy Alignment calls retain raw responses and UTC/monotonic attempt timing. | Phase 4 alignment plus evaluation/match/objective timing are active; candidate-total and selection/crossover timing remain broader artifact work. |

## Active configuration

- `ExperimentConfig.matches_per_candidate` is the 180-match fixed-roster count; generation 1+ evaluates 198 matches after adding `eagle_previous_best`.
- The canonical weighted search roster, fixed weight sum 12.5, adaptive schedule, map, cycles, timeout, material/resource scales, unit values, and distinct fixed/dynamic seeds are resolved and persisted.
- The vendored runtime lacks `ai.abstraction.WorkerRush`; the evaluator compiles a run-local compatibility subclass of `LightRush` under that canonical class name.
- The parser keeps legacy `opponent` input compatible, while `resolved_config.json` records the actual fixed roster used for runtime evaluation.
- `alignment_backend` is active (`mock`, `openai`, or `openai`) and is independent from the generation call while sharing configured endpoint/model values when applicable.
- Resolved configuration records `artifact_schema_version = phase4-v3` and `objective_formula_version = eagle-objectives-simplicity-v1`; default compact match artifacts store gzip telemetry and remove transient replay/round-state files after scoring.
- Only `game_performance` and `code_quality` are active optimizer objectives; Strategy Alignment is diagnostic evidence.

## Active tests

The suite now covers Phase 2C mutation, Phase 3 validation/compilation/integration, and Phase 4 runtime evaluation, weighted adaptive Game Performance, failure-aware Code Quality, Function Capability, Strategy Alignment, objective aggregation, artifacts, and timing. Focused tests prove the fixed ten-opponent roster, deterministic 3-map × 3-round × 2-side matrix, champion tie-breaking, weighted normalization, no regeneration, timeout/invalid/partial failures, formula boundaries, successful and partial end-to-end persistence, and two-objective output.

The full WSL unit suite passes. In addition to the bounded seven-check Integration probe, a real candidate completed the canonical 18-match one-opponent matrix (three maps, three rounds, both sides, 5,000-cycle limit) with all 18 result artifacts written to a temporary smoke directory; this is runtime proof, not performance evidence or a full EA run.
The full Linux unit suite passes on the canonical Ubuntu runtime; native Linux and WSL2 Ubuntu use the same commands. A bounded real seven-check Integration probe exists from Phase 3; the one-opponent 18-match smoke run described above is runtime proof, not performance evidence or a full EA run.

## Recent run evidence

The most recent complete saved population run (`runs/20260712_154209_634218`) uses an obsolete split/function-body schema and `strategy_alignment` objective. `contract-smoke-*` and `code_quality_smoke` also predate the current complete-file boundary. Historical runs are not active-runtime evidence and are intentionally outside current analysis readers.

## Operational state

- `python -m eagle run --config configs/experiments/microrts.yaml --runtime-config configs/runtime.yaml --mock` exercises the contract-shaped weighted 180/198-match evaluation pipeline, but mock execution is not real MicroRTS proof.
- Real EA mode requires the local generation endpoint, `javac`, the vendored
  MicroRTS runtime, and resolved search-opponent artifacts (including AlliBot and
  the pinned TMA/Mayari/COAC JARs).
- WSL is the project default for Python/Java/MicroRTS commands.
- Native Ubuntu Linux is the primary runtime, and WSL2 Ubuntu is also supported for Python/Java/MicroRTS commands.
- Candidate inspection is artifact-only; the obsolete manual viewer has been removed.

See [`architecture_gaps.md`](architecture_gaps.md) for the remaining implementation status.

## Canonical runtime update (2026-07-24)

The user-facing workflow is now exactly `./run_env.sh`, `./run.sh`, and `./analyze.sh`. Runtime process ownership, EA execution, and static analysis are separate. Every completed generation writes an atomic surviving-population snapshot, compact objective metrics, and an updated `eagle-run-v1` manifest.

## LLM server lifecycle update (2026-07-25)

`configs/runtime.yaml` (`runtime-v1`) is the single runtime source of truth. The
active runtime supports exactly one local Qwen3.5-9B llama-server process on
127.0.0.1:8080. The process manager validates its PID command line, performs a
two-path health check, and does not embed a watchdog loop or remote server.
The optional independent `watchdog.sh` monitors/restarts the local network
interface and leaves server lifecycle ownership with `run_env.sh`.

Generation and Strategy Alignment retain their existing transport bounds. Reflection
and Rewrite now use deterministic section budgets before final prompt construction;
their request metadata records section sizes and omitted/truncated sections instead
of applying the old blind 60,000-character head/tail slice. Full match telemetry
remains in run artifacts.

The local launcher passes configured model IDs through llama.cpp `--alias`, so
strict `/v1/models` preflight and inference use the same identifier. The
checked-in local profile also disables both RAM and per-slot prompt caches
because the installed CUDA build aborts while reusing an identical one-token
preflight prompt; two consecutive real preflights now pass on one stable PID.

## Canonical offline analysis update (2026-07-28)

`./analyze.sh` and `python -m eagle analyze` resolve either one explicit
canonical run or the newest valid direct child of the configured run root.
`eagle.analysis.loader` reads only versioned compact manifests, generation
metrics, final populations, timing, and error artifacts. It never reads
`results.jsonl`.

Analysis writes derived Markdown, JSON, CSV, and static Matplotlib output under
the run's configured analysis directory. Partial initialized/running runs
remain analyzable, unsupported schemas fail explicitly, and historical layouts
are rejected without a migration subcommand.

## Compact persistence and OOM fix (2026-08-04)

Evolution persistence now uses `phase4-v3`, `eagle-candidate-v2`, and
`eagle-generation-v2`. Per-match stdout/stderr, raw results, commands, and
telemetry have a single owner under `candidates/<id>/matches/`; candidate,
generation, final-population, and summary payloads retain fitness/timing and
bounded reflection summaries without copying raw process output. The duplicate
run-level `results.jsonl` and flat generation population files are no longer
written. This removes the serialization amplification that previously exhausted
RAM and caused the kernel to terminate Python together with VSCode processes.

## Match Commentator update (2026-08-06)

The canonical match runner now persists a streamed gzip tick trace and integrity
metadata for the complete evaluation matrix. Strategy Reflection selects one
strict-priority outcome pool (`loss > draw > win`), samples at most three matches
with reproducible run-derived randomness, calls the in-pipeline
`match_commentator` role only for those matches, and cleans temporary raw logs
after terminal handling. Aggregate fitness still uses every configured match.

## Four-entrypoint cleanup (2026-08-11)

The executable surface is limited to `run_env.sh`, `run.sh`, `analyze.sh`, and
`watchdog.sh`. Final-test, GUI-match, migration, standalone commentator, and
unused legacy analysis utilities were removed. External opponent assets remain
because the active evolution roster still resolves them during evaluation.
