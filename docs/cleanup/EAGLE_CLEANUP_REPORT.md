# EAGLE Cleanup Report

## 1. Executive summary

The cleanup reviewed the live worktree, branches, Git history, source imports,
launchers, configuration, tests, documentation, and marker references. The
completed code cleanup removed two duplicate gameplay evaluator modules and
moved their effective implementations to the public `evaluation` import paths.
The framework/application boundary remains unchanged: MicroRTS execution stays
under the evaluation application boundary.

The review did not find a smoke-only file that could be safely deleted. The
final-test bounded smoke protocol provides unique real Java/opponent coverage,
and the mock backend is used by deterministic contract tests. Historical reader
and LLM configuration migrations were identified but intentionally deferred
because active configs and historical artifacts still depend on them.

## 2. Files removed

- `evaluation/canonical_game_metrics.py`
- `evaluation/canonical_game_performance.py`

No vendored MicroRTS, final-test adapter, failure-evidence, or operator launcher
was removed without a caller and artifact review.

## 3. Files consolidated

- `evaluation/game_metrics.py` is now the single gameplay-metrics module.
- `evaluation/game_performance.py` is now the single gameplay-formula module.
- `docs/architecture/CANONICAL_RUNTIME_PATHS.md` records ownership for EA,
  candidate lifecycle, operators, evaluation, artifacts, configuration, LLM
  routing, GUI, analysis, and launchers.

## 4. Canonical implementations selected

The canonical paths are documented in the architecture document. In brief:
`eagle.search` owns EA execution; `eagle.candidate` and `eagle.offspring` own
candidate state; `eagle.mutation`, `eagle.rewrite`, and `eagle.crossover` own
variation; `generation.java_agent_generator` owns complete-source generation and
validation; `evaluation.compiler` owns compilation; `eagle.evaluation` plus
`evaluation.microrts_runner` own runtime evaluation; `evaluation.*` owns
objective formulas; `eagle.artifacts` owns evolution artifacts; and
`eagle_ui` consumes `eagle.analysis` readers.

## 5. Compatibility layers removed

The duplicate wildcard-import evaluator implementations were removed. The
following layers remain with evidence and are not silently deleted: historical
artifact readers, the endpoint-to-role LLM configuration fallback, the bounded
final-test smoke subset, and the TMA build marker required by an unchanged
upstream import.

## 6. Config keys removed or migrated

None. No configuration key was removed without a completed active-config and
historical-artifact migration. The endpoint-to-role fallback is recorded as a
future migration target in the inventory.

## 7. Launch scripts removed or replaced

None. `scripts/run_eagle.py`, `scripts/run_final_test.py`, `run.sh`,
`tmux_services.sh`, and the local LLM helpers have active documentation or
operator callers. They remain the canonical launch surface pending a separate
environment migration.

## 8. Smoke tests retained and why

- The final-test `--smoke` option is retained because it performs the bounded
  real six-match TMA/Mayari/COAC compatibility check and is documented as a
  non-formal final test.
- The mock generation/compile/evaluation path is retained because it is the
  deterministic backend used by automated pipeline contracts.

The root documentation now distinguishes deterministic offline verification
from real Java/MicroRTS evaluation; no production evaluator selects behavior by
smoke mode.

## 9. Tests added or converted

No new test file was added. Existing tests were traced and retained because
they cover evaluator formulas, artifact readback, GUI services, final-test
selection, and LLM profile routing. The duplicate evaluator consolidation was
validated by import/reference inspection; runtime execution could not be
completed in this environment because the WSL command did not return output.

## 10. Architecture issues fixed

- Removed two parallel gameplay evaluator implementations.
- Removed the wildcard-import mechanism that silently selected one duplicate at
  module import time.
- Documented canonical ownership and remaining smells.
- Preserved the framework/application boundary and existing artifact schemas.

## 11. Remaining known risks

- `eagle/llm_profiles.py` still supports endpoint sections while role sections
  are being adopted.
- `scripts/analyze_run.py` still reads historical result/debug formats.
- `evaluation/code_quality.py` still requires a separate focused consolidation
  because its active static region APIs and failure-aware objective APIs must be
  merged without changing research scoring.
- Full real MicroRTS, pinned-opponent final test, GUI startup, and external LLM
  execution were not run in this environment.

The ranked list is in `docs/cleanup/EAGLE_ARCHITECTURE_SMELLS.md`.

## 12. Verification commands

- `git status --short`
- `git diff --check`
- `git grep` marker, import, launcher, and canonical-module searches
- `git branch -a`
- `git log --all --oneline`
- `wsl.exe bash -lc "cd /mnt/d/Project/EAGLE && python3 -m pytest -q"`
- `python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock`

## 13. Verification results

- The initial worktree was clean.
- Git marker/reference/history inventory completed.
- `git diff --check` passed for the committed changes.
- Canonical-module reference search showed no remaining imports of the removed
  `canonical_game_metrics` or `canonical_game_performance` paths.
- Git history confirms the duplicate modules were transitional copies and that
  older surrogate/split-agent/GUI launchers are already deleted from the live
  tree.

## 14. Validation not performed and why

The WSL Python smoke/test commands hung without producing test output and were
terminated; therefore no test pass is claimed. Real MicroRTS and external LLM
execution were not performed because they require the Java/vendor runtime,
pinned opponent dependencies, and local model servers. GUI startup was not
performed because it is an interactive NiceGUI process.

## Git deletion summary

Compared with the pre-cleanup `cb77447d` revision:

- Files deleted: 2
- Files added: 3 documentation files
- Files modified: 2
- Lines added: 381
- Lines removed: 905

## Commits

- `5e199595` — `docs(cleanup): inventory smoke code patches and legacy paths`
- `e4e02929` — `refactor(core): define canonical runtime and evaluation paths`
- `76a276ef` — `docs(architecture): record remaining cleanup risks`
