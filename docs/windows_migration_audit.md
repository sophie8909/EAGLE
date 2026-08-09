# EAGLE Windows Migration Audit

Audit scope: the current generated-Java EAGLE architecture in this checkout. The
audit intentionally excludes GEPA, ACE, MIPRO, CAPO, surrogate experiments, and
the old runtime-controlled-agent designs. No implementation migration is made
by this document.

## 1. Executive Summary

Current EAGLE cannot use the checked-in `./run_env.sh` / `./run.sh` /
`./analyze.sh` workflow unchanged on native Windows. The core EA is much closer
to portable than the launcher experience suggests:

- Python uses `pathlib.Path` for run, candidate, class, match, and analysis
  artifacts.
- LLM calls are ordinary HTTP requests to the configured loopback endpoint.
- Java, `javac`, and MicroRTS are invoked as argument lists rather than through
  shell command strings.
- Java classpaths use `os.pathsep`, so the active compiler, integration probe,
  match runner, and Final Test path already select `;` on Windows.
- The active analysis reader/report is Python and does not depend on shell tools.

Three active surfaces block a clean native-Windows migration:

1. `configs/runtime.yaml` contains deployment-specific Linux `/home/...` paths
   for the GGUF file and `llama-server` binary.
2. `eagle/runtime/processes.py` reads `/proc/<pid>/cmdline` and stops the server
   with POSIX signal assumptions.
3. The intended command surface is implemented only by Bash scripts, including
   Bash-only path/argument logic in `analyze.sh`.

Migration difficulty is low-to-moderate and localized. Linux is not materially
required by the EA, LLM HTTP protocol, Java/MicroRTS execution, or artifact
format. A Windows runtime config, a small cross-platform process-lifecycle
change, and thin PowerShell wrappers are sufficient. The current llama.cpp
binary and Conda installation still need native Windows builds/configuration.

## 2. Active Runtime Architecture

The reachable current path is:

```text
run_env.sh
  -> conda run -n eagle python -m eagle runtime <operation>
  -> eagle.cli.runtime
  -> load_runtime_config(configs/runtime.yaml)
  -> RuntimeManager.start/stop/status/check
  -> configured llama-server process
  -> urllib health checks: /health and /v1/models

run.sh
  -> conda run -n eagle python -m eagle run --config ... --runtime-config ...
  -> eagle.cli.run
  -> ExperimentConfig + runtime endpoint override
  -> eagle.search.run_search
  -> eagle.evaluation.evaluate_candidate
  -> generation backend HTTP request
  -> complete CandidateAgent.java generation and validation
  -> evaluation.compiler: javac -Xlint:all
  -> evaluation.microrts_runner: Java integration probe
  -> evaluation.runtime_evaluation: bounded Java MicroRTS matches
  -> game metrics, code quality, objectives, candidate/run artifacts
  -> Strategy Reflection and Code Reflection in the EA offspring path

analyze.sh
  -> python -m eagle analyze
  -> eagle.cli.analyze
  -> eagle.analysis.loader
  -> eagle.analysis.report
  -> CSV, JSON, Markdown, and static Matplotlib outputs under the run
```

The Java path passes absolute artifact/class paths and uses `cwd=microrts_dir`.
The configured map path is intentionally relative to that MicroRTS working
directory. This is a current cwd contract, not a Linux dependency.

`evaluation/microrts_runner.py` is active for the integration probe and
re-exports the canonical match implementation from
`evaluation/runtime_evaluation.py`; it must not be dismissed as entirely dead.

## 3. OS Dependency Inventory

| Component | File | Linux Dependency | Windows Impact | Category | Recommended Action |
| --- | --- | --- | --- | --- | --- |
| Runtime model path | `configs/runtime.yaml:7` | Hardcoded `/home/mhlab/.../model.gguf` | Fails file validation on Windows | C | Replace with a Windows deployment path; keep it config-only |
| Runtime server path | `configs/runtime.yaml:8` | Hardcoded Linux `llama-server` path with no `.exe` | Fails file validation and launch | C | Point `server_binary` to the native CUDA `llama-server.exe` |
| Server lifecycle identity | `eagle/runtime/processes.py:149` | Reads `/proc/<pid>/cmdline` | Command matching always fails on Windows | C | Use a cross-platform process inspection method, preferably a small `psutil`-based implementation or an equivalent Windows-safe query |
| Server stop/aliveness | `eagle/runtime/processes.py:170-200` | POSIX `os.kill`, `SIGTERM`, `SIGKILL`, and `start_new_session` semantics | Stop/escalation behavior is not portable | C | Use cross-platform process handles/termination; retain PID and command-identity safety |
| EA launcher | `run.sh` | Bash shebang, `BASH_SOURCE`, `exec`, parameter expansion, `conda run` | Not a PowerShell command | B | Add a thin `run.ps1`; keep business logic in `python -m eagle run` |
| Runtime launcher | `run_env.sh` | Bash shebang, `[[ ]]`, `case`, `exec` | Not a PowerShell command | B | Add a thin `run_env.ps1`; keep lifecycle logic in Python |
| Analysis launcher | `analyze.sh` | Bash `[[ ]]`, `exec`, and POSIX absolute-path test `/*` | Windows `C:\...` paths are treated incorrectly | B | Add `analyze.ps1` or remove the wrapper and document the Python CLI |
| Server executable validation | `eagle/runtime/config.py:138` | Uses Unix executable-bit semantics in tests and validation | Windows executable permission bits are not equivalent | B | Validate existence plus native launchability/extension; update tests to use a native executable fixture or mock |
| Tool discovery | `evaluation/compiler.py`, `evaluation/runtime_evaluation.py`, `evaluation/microrts_runner.py`, `eagle/final_test/opponents.py` | None at runtime, but names are fixed as `javac`, `java`, and `git` | Requires those tools on `PATH` | B | Keep standard PATH discovery for the minimum migration; add explicit config only if deployment PATH cannot be controlled |
| LLM transport | `generation/backend.py`, `eagle/mutation.py`, `eagle/runtime/endpoints.py` | None; HTTP only | Portable | A | No change |
| Java classpaths | `evaluation/compiler.py:138`, `evaluation/runtime_evaluation.py:195`, `eagle/final_test/opponents.py:558` | No Linux dependency | Already uses `os.pathsep` (`;` on Windows) | A | No change |
| Analysis plotting helper | `scripts/analysis/plot_game_performance_by_generation.py:21` | Hardcoded `/tmp/matplotlib` | May fail or write to the wrong place | B | Use `tempfile.gettempdir()` or a run-local cache directory |
| Analysis core | `eagle/analysis/loader.py`, `eagle/analysis/report.py` | None | Portable | A | No change |
| GPU handling | `eagle/runtime/processes.py:108-124`, `configs/runtime.yaml:12` | No `/dev/nvidia*`, `LD_LIBRARY_PATH`, or Linux CUDA loader assumption | Native llama.cpp CUDA build must support the same CLI | A/B | No EAGLE GPU refactor; verify the Windows llama.cpp build with `--list-devices` |
| Vendored MicroRTS | `third_party/microrts/` | Java runtime/source, not Linux-specific in the active path | Portable with JDK 17 and correct paths | A | No change to MicroRTS for migration |
| Legacy LLM shell helper | `third_party/microrts/src/ai/abstraction/llm-json-completion.sh` | `/bin/sh`, `python3`, `curl`, shell JSON construction | Not reachable from current EAGLE | D | Remove rather than port; current EAGLE agents do not use runtime LLM calls |
| Test executable fixture | `tests/test_runtime_workflow.py:16-18,84-88` | `/bin/sh` text and `chmod` executable-bit assertions | Native Windows does not model this fixture the same way | B | Replace with platform-aware fixtures and mock process launch where appropriate |

## 4. Shell / Launcher Audit

### `run.sh`

This is an active, thin wrapper. It resolves the repository root using
`BASH_SOURCE`, changes directory, selects a default experiment config, and
executes `conda run -n eagle python -m eagle run`. It contains no EA business
logic. The Windows equivalent should be a PowerShell wrapper or a documented
direct Python command.

### `run_env.sh`

This is also an active, thin wrapper. It validates one operation name and
delegates to `python -m eagle runtime`. It has a duplicated shebang but no
application logic. The Windows equivalent should be `run_env.ps1`, not a second
runtime implementation.

### `analyze.sh`

This wrapper delegates to `python -m eagle analyze`, but it contains a small
path-normalization branch. The test `RUN_DIR != /*` only recognizes POSIX
absolute paths, so a Windows `C:\Users\...` path is incorrectly prefixed with
the caller directory. The clean equivalent is `analyze.ps1` or direct use of
the Python CLI; do not duplicate analysis logic in PowerShell.

### Other shell files

The only other tracked shell file is the vendored
`third_party/microrts/src/ai/abstraction/llm-json-completion.sh`. No active
Python or Java path references it. It belongs in the obsolete/deletion category,
not in a Windows compatibility layer.

## 5. Python Compatibility Audit

The active Python core is mostly cross-platform:

- Filesystem operations use `Path`, `Path.resolve`, `mkdir`, `read_text`,
  `write_text`, and `relative_to`.
- Java and MicroRTS commands are passed as lists to `subprocess.run` with
  explicit `cwd`, `capture_output`, timeouts, and no `shell=True`.
- No active code uses `os.system`, `shlex`, `preexec_fn`, `os.setsid`, or
  `os.killpg`.
- HTTP uses `urllib.request`; no `curl`, `wget`, `ip`, `ifconfig`, `ss`, or
  `netstat` dependency exists.
- `.as_posix()` is used for stable artifact/hash metadata, not to execute a
  filesystem path.

The Python portability exceptions are concentrated in runtime process
management, executable-bit validation, fixed executable names, and one plotting
helper. `conda_env` is parsed into runtime configuration but the Python core
does not activate Conda; the Bash wrappers invoke `conda run`. This means a
future PowerShell launcher must either invoke `conda run` successfully or run
with the target environment's Python interpreter already selected. It should
not depend on `.bashrc` or interactive `conda activate` state.

## 6. llama.cpp Compatibility Audit

1. The repository currently expects a Linux binary because the checked-in
   configuration points to `/home/mhlab/.../llama-server`.
2. No code inspects ELF headers or assumes a Linux loader. The server is passed
   as the first element of a `Popen` argument list.
3. Replacing the path with `llama-server.exe` is necessary but not sufficient:
   the `/proc` command matcher, POSIX termination path, and executable check
   still need Windows-safe behavior.
4. The binary/model paths are already configuration fields, but there is no
   environment-variable expansion or executable discovery. A Windows runtime
   config must carry the actual absolute or project-relative paths.
5. The server arguments (`--model`, `--host`, `--port`, `--ctx-size`,
   `--n-gpu-layers`, `--parallel`, `--threads`, `--batch-size`, and
   `--list-devices`) are llama.cpp CLI contracts rather than Linux contracts.
6. The EAGLE side only needs the OpenAI-compatible HTTP endpoint. Health checks
   call `/health` and `/v1/models`; no Linux network utility is involved.

## 7. Java / MicroRTS Compatibility Audit

The active Java path is portable in principle:

- `javac` compilation in `evaluation/compiler.py` uses `os.pathsep` and an
  explicit `cwd=microrts_dir`.
- The integration probe in `evaluation/microrts_runner.py` uses the same
  `os.pathsep` rule and direct `javac`/`java` argument lists.
- Match execution in `evaluation/runtime_evaluation.py` uses absolute class,
  replay, round-state, and result paths, while the relative map path is resolved
  against the explicit MicroRTS cwd.
- Final Test source rebuilds and probes also use `os.pathsep` and direct Git,
  Java, and compiler commands.

There is no active hardcoded `:` classpath separator. Windows changes `.java`
and `.class` file locations but not the Java source/runtime contract. MicroRTS
itself is effectively portable Java for this path. The only Java-related
requirements are a working JDK 17, the vendored runtime build/classes/libs,
and standard `java`/`javac` PATH entries.

The main migration test risk is cwd disagreement. The current code is explicit:
`cwd=microrts_dir`, absolute class/artifact paths, and a map path interpreted
from that cwd. A Windows smoke test must preserve those relationships.

## 8. Process Management Audit

### LLM server

`RuntimeManager` starts one process with `subprocess.Popen`, redirects stdout and
stderr to a runtime log, stores one PID, polls health, and refuses to stop a PID
whose command line does not match the configured server/model/port. This is the
right ownership model, but its current implementation is POSIX-specific in
three places:

- `/proc/<pid>/cmdline` is the command identity source.
- `start_new_session=True` expresses a Unix session boundary.
- `os.kill(..., SIGTERM/SIGKILL)` supplies the stop/escalation path.

The minimum change is a small cross-platform process identity/termination
implementation. It must preserve unrelated-process protection; simply deleting
the command match would be unsafe.

### Java/MicroRTS and EA subprocesses

The active Java and Git subprocesses do not use process groups, shell quoting,
signals, or background daemons. Their Windows behavior is governed by PATH,
JDK installation, cwd, and classpath separator, all of which are manageable.

## 9. Filesystem / Artifact Compatibility Audit

The canonical run/candidate/match artifact writers are Path-based and use normal
UTF-8 text/JSON writes. They do not require symlinks, Unix permissions, or
case-sensitive lookup. Stable hash metadata deliberately uses POSIX separators
inside hashes/relative artifact metadata, which is correct and should not be
changed into host-native separators.

The current runtime config is the only active hardcoded POSIX deployment path.
The standalone plotting helper has one `/tmp` cache path. No reserved Windows
names (`CON`, `AUX`, `NUL`, etc.) or case-only tracked source collisions were
found.

Existing run artifacts were measured at a maximum path length of 171 characters
under `D:\Project\EAGLE`, below the traditional 260-character limit. Current
candidate IDs and match names are short, so path length is not an immediate
blocker. A user-selected deep repository/run root could still approach the
limit; keeping the Windows checkout near a short root and enabling Windows long
paths is prudent, but not part of the minimum code migration.

## 10. Networking Audit

Networking is not a Linux blocker. The active design is a same-machine HTTP
client/server pair:

- Server host/port are config-driven; the current host is `127.0.0.1:8080`.
- Health checks use Python `urllib` against `/health` and `/v1/models`.
- LLM generation and reflection use the configured OpenAI-compatible HTTP URL.
- Port occupancy uses a Python socket bind probe.
- There is no LAN IP discovery, Linux interface command, firewall API, curl,
  wget, or remote-server process discovery in the active path.

Native Windows therefore changes server installation/firewall policy, not the
EAGLE networking model. Keep loopback binding for a same-machine deployment;
only expose a LAN host deliberately.

## 11. Test Compatibility Audit

Most tests use `tempfile`, `Path`, mocks, direct subprocess argument lists, and
`os.pathsep`, so they are portable. The notable Windows issues are:

- `tests/test_runtime_workflow.py` creates a text `#!/bin/sh` fake server and
  relies on `chmod(0o755/0o644)`. Windows does not use that executable-bit model
  the same way; the non-executable assertion is not a reliable native-Windows
  contract.
- `tests/test_canonical_run_cli.py` reads `run.sh` as text. It verifies wrapper
  content but does not prove a Windows launcher.
- Documentation/test-contract commands use `python3` and WSL paths. They are
  workflow guidance, not production imports, but should gain Windows commands.
- Final Test tests invoke Git directly and may require network access when
  exercising repository fetch behavior; Git itself is portable.

No test currently proves Windows-shaped absolute runtime paths, a `.exe` server
path, PowerShell wrapper behavior, or cross-platform server stop behavior.

## 12. Obsolete Linux-Specific Code

One tracked file is Linux-specific and outside the current architecture:

- `third_party/microrts/src/ai/abstraction/llm-json-completion.sh` uses
  `/bin/sh`, `python3`, shell JSON assembly, `curl`, and a separate localhost
  Ollama-style endpoint. Current EAGLE generates complete Java offline before
  matches and does not invoke this helper. It should be removed or explicitly
  quarantined with the obsolete vendor material, not ported.

The old runtime-controlled-agent, multi-model, watchdog, and remote-topology
surfaces are already rejected/removed by the active EAGLE configuration and are
not migration targets. Documentation that says WSL or `python3` is stale
operational guidance, not an active Linux runtime dependency.

## 13. Minimum Migration Plan

1. Create a Windows deployment config based on `configs/runtime.yaml`, with a
   native GGUF path and CUDA-enabled `llama-server.exe` path. Do not add model
   or endpoint selection to experiment configs.
2. Refactor `eagle/runtime/processes.py` only at its platform boundary: retain
   one managed PID, command identity validation, durable logs, health polling,
   and safe unrelated-process refusal; replace `/proc` and POSIX signals with a
   Windows-safe/cross-platform process query and termination path.
3. Add thin `run_env.ps1`, `run.ps1`, and `analyze.ps1` wrappers, or document
   direct `python -m eagle ...` commands as the primary Windows interface. Keep
   all application logic in Python.
4. Update the runtime executable check and its tests so native Windows
   launchability is tested rather than Unix mode bits.
5. Replace the plotting helper's `/tmp/matplotlib` with Python's temp directory
   handling.
6. Update README/operations/test-contract command examples and the runtime CLI
   error hint to show PowerShell/Windows paths while retaining the optional Bash
   wrappers for Linux.
7. Install/verify the native toolchain: Python/Conda environment, JDK 17,
   Git, CUDA llama.cpp build, model file, and vendored MicroRTS classes/libs.
8. Run the Windows smoke-test sequence below. Do not claim real MicroRTS proof
   from the existing mock path.

No Docker, WSL default, duplicated EA implementation, or broad OS abstraction
layer is required.

## 14. Estimated Change Surface

### Mandatory

- `configs/runtime.yaml` — replace Linux model/server paths for the Windows
  deployment, or create a Windows-specific deployment config if the existing
  Linux file must remain usable.
- `eagle/runtime/processes.py` — replace `/proc` and POSIX process-control
  assumptions while preserving PID and command identity safety.
- `eagle/runtime/config.py` — adjust executable validation if the selected
  Windows process strategy cannot use `os.access(..., X_OK)`.
- `tests/test_runtime_workflow.py` — replace Unix executable-bit fixtures and
  add Windows-shaped process/config coverage.
- New thin PowerShell wrappers: `run_env.ps1`, `run.ps1`, `analyze.ps1`, if the
  three-command workflow remains the user-facing contract.

### Recommended cleanup

- `scripts/analysis/plot_game_performance_by_generation.py` — remove `/tmp`.
- `README.md`, `docs/operations/running_eagle.md`,
  `docs/operations/inspecting_runs.md`, `docs/testing/test_contracts.md`,
  `docs/implementation/migration_plan.md` — add native-Windows commands and
  stop presenting WSL/`python3` as the only workflow.
- `eagle/cli/run.py` — update the error hint from `./run_env.sh` to the
  platform-neutral or PowerShell command.
- `third_party/microrts/src/ai/abstraction/llm-json-completion.sh` — delete as
  obsolete, subject to vendor-tree ownership policy.
- Add a Windows smoke-test job or documented manual check; no production Java
  classpath rewrite is expected.

### No change expected

- `generation/backend.py` and `eagle/mutation.py` HTTP transport.
- `eagle/search.py`, `eagle/evaluation.py`, and active Strategy/Code Reflection
  orchestration.
- `evaluation/compiler.py`, `evaluation/microrts_runner.py`, and
  `evaluation/runtime_evaluation.py` classpath/cwd construction, because they
  already use `Path` and `os.pathsep`.
- `eagle/analysis/loader.py` and `eagle/analysis/report.py`.
- Vendored MicroRTS Java sources and the Java agent generation contract.

## 15. Windows Smoke-Test Plan

Run from PowerShell in the native Conda environment:

1. Confirm `python`, `conda`, `java`, `javac`, `git`, `nvidia-smi`, and the
   configured `llama-server.exe` are discoverable or explicitly configured.
2. Load the Windows runtime and experiment configs without Linux absolute
   paths.
3. Run `python -m eagle runtime check` and verify llama.cpp CUDA device output.
4. Start the server, verify `/health` and `/v1/models`, then run one LLM
   generation request.
5. Generate one complete Java agent and compile it with `javac -Xlint:all`.
6. Run the integration probe and one real MicroRTS match with a short tick
   limit; verify `cwd`, map resolution, classpath, and result paths.
7. Verify result, telemetry, replay/round-state, timing, and candidate/run
   artifacts are written and reopen correctly from Windows paths.
8. Run one minimal EA generation with the native server; use the existing
   `--mock` path only as a Python/artifact smoke test, not as Java/MicroRTS
   proof.
9. Run `python -m eagle analyze --run-dir <windows-run-path>` and verify CSV,
   JSON, Markdown, and plot outputs.
10. Stop/restart/status the managed server and verify stale/unrelated PID
    protection and clean shutdown.

## Final terminal report

Using one count per independent active surface:

- Active Linux-specific blockers: **3**
  (`configs/runtime.yaml`, POSIX runtime process management, Bash-only command
  wrappers).
- Minor portability issues: **5**
  (Windows executable-bit semantics, PATH-only tool discovery, `/tmp` plotting
  cache, Linux/WSL operational examples, and missing Windows-specific tests).
- Obsolete Linux-specific files: **1**
  (`third_party/microrts/src/ai/abstraction/llm-json-completion.sh`).
- Native Windows migration: **recommended**, after the small runtime/lifecycle
  adaptation; Linux is not materially required by the EAGLE EA core.
- Top 5 files requiring changes: `configs/runtime.yaml`,
  `eagle/runtime/processes.py`, `eagle/runtime/config.py`,
  `tests/test_runtime_workflow.py`, and the new PowerShell launcher set
  (`run_env.ps1`, `run.ps1`, `analyze.ps1`).


## Implementation status

The minimum Windows migration has been applied without changing EA operators, fitness,
opponents, scoring, reflection, mutation, crossover, or selection behavior.

Resolved in the runtime surface:

- configs/runtime.yaml no longer contains machine-specific /home/... paths.
  The model path is project-relative, while the llama.cpp server is resolved from an
  explicit path, PATH, or the platform default (llama-server.exe on Windows).
- eagle/runtime/config.py resolves llama.cpp, Python, Java, and javac executables
  and accepts optional additional llama-server arguments.
- eagle/runtime/processes.py no longer reads /proc or sends POSIX signals. It
  uses psutil for PID inspection/termination and keeps the small platform branch
  limited to process-group creation flags at launch.
- Java compilation, integration probing, and MicroRTS match execution use resolved
  executables and retain os.pathsep classpaths.
- run_env.ps1, run.ps1, and analyze.ps1 are thin wrappers that invoke the
  active Python interpreter. The Linux wrappers remain available and delegate to
  active-environment Python rather than activating Conda internally.
- Analysis plotting uses the platform temporary directory instead of /tmp.
- The unreferenced vendor llm-json-completion.sh helper was removed instead of ported.

Remaining operational prerequisites are deployment-specific: install the JDK, install
the psutil dependency, place llama-server.exe on PATH or configure its path,
and set llm.model_path to the locally installed GGUF file. No model or llama.cpp
binary is committed to this repository.
