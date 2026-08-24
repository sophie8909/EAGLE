# Architecture traceability matrix

This is the active implementation tracker for
[`../eagle_architecture_spec.md`](../eagle_architecture_spec.md). Historical
NSGA-II and `eagle-run-v1` rows were removed on 2026-08-19.

| ID | Contract | Canonical owner | Implementation | Verification | Status |
| --- | --- | --- | --- | --- | --- |
| CAND-01 | Two-prompt genotype and complete Java phenotype remain distinct | candidate model | `eagle/candidate.py`, `eagle/evaluation.py` | candidate/state-transition tests | Implemented |
| CAND-02 | First-class lineage and component provenance | lineage schema | `eagle/crossover.py`, `eagle/artifacts.py` | lineage/crossover tests | Implemented |
| EVO-01 | Seeded seven-case lexicase parent/survivor selection | evolutionary flow | `eagle/selection.py`, `eagle/search.py` | lexicase tests | Implemented |
| EVO-02 | Static/opponent/head-to-head reflection operator modes | mutation | `eagle/aos.py`, `evaluation/parent_offspring.py` | AOS tests | Implemented |
| MUT-01 | Strategy/Code boundaries, bounded structured retries, and authoritative mutation inputs | mutation | `eagle/mutation.py`, `eagle/rewrite.py`, `eagle/strategy_reflection.py` | mutation/reflection tests | Implemented |
| PROMPT-01 | One executable prompt per file under `prompts/` | prompt manifest | `eagle/prompts.py`, `prompts/manifest.toml` | prompt-resource tests | Implemented |
| GEN-01 | Checked-in generation-zero seed plus bounded compile-guided full-file decoding with immutable genes and per-attempt request/source/diagnostic evidence | Java generation | `generation/backend.py`, `generation/java_agent_generator.py`, `eagle/evaluation.py` | generation-attempt/prompt-resource tests | Implemented |
| VAL-01 | External Java/security contract, immutable scaffold, and deterministic strategy scope/array/API checks | Java generation | `generation/java_agent_generator.py` | validation tests | Implemented |
| EVAL-01 | Compile each validated decoder sample at most once, promote the first success, and run seven distinct opponents × three maps × three rounds × two sides once | evaluation | `eagle/evaluation.py`, `evaluation/match_matrix.py`, `third_party/microrts/src/ai/abstraction/WorkerRush.java` | generation-attempt/evaluation matrix/opponent compile tests | Implemented |
| EVAL-02 | Integration probe and match execution have separate single owners | evaluation | `evaluation/microrts_runner.py`, `evaluation/runtime_evaluation.py` | integration/runtime tests | Implemented |
| EVAL-03 | One canonical match trace retained through sibling construction and retired after atomic survivor persistence | match evidence | `evaluation/match_trace.py`, `eagle/strategy_reflection.py`, `eagle/search.py`, `eagle/resume.py` | trace/reflection tests | Implemented |
| SCORE-01 | Seven opponent fitness cases; aggregate and quality are diagnostics | objectives | `evaluation/objectives.py`, `evaluation/code_quality.py` | objective/quality tests | Implemented |
| ART-01 | Only `eagle-run-v2` compact referenced artifacts are supported | artifact schema | `eagle/run_artifacts.py`, `eagle/analysis/loader.py` | artifact/analysis tests | Implemented |
| CFG-01 | File-only prompts and one execution mode | config schema | `eagle/config.py`, `configs/experiments/` | config/prompt tests | Implemented |
| OPS-01 | Unified experiment lifecycle, resumable folder-batch run index, and static analysis entrypoint | operations | `eagle/experiment.py`, `experiment.sh`, `analyze.sh` | launcher/runtime tests | Implemented |
| TIME-01 | Candidate/stage/attempt/match timing plus one run event per mutation-role attempt | timing schema | `eagle/timing.py`, `eagle/llm.py`, evaluation/mutation modules | timing/logging tests | Partial: selection/crossover event detail remains optional hardening |

## Update rule

A row is implemented only when source, configuration, artifacts, tests, and the
canonical documentation agree. Old run folders are not proof of current behavior.
