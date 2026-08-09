# EAGLE Linux / WSL2 Runtime Audit

Audit scope: the active generated-Java EAGLE architecture only. This document
excludes GEPA, ACE, MIPRO, CAPO, surrogate experiments, and obsolete
runtime-controlled-agent designs.

EAGLE has one Linux runtime. It is intended to run both on native Ubuntu Linux
and Ubuntu under WSL2. Native Windows execution is not currently a target.

## 1. Executive Summary

- Native Ubuntu Linux remains supported: **YES**.
- Windows 11 plus WSL2 Ubuntu is intended to be supported: **YES**.
- Native Windows execution is a target: **NO**.
- A second runtime implementation is required: **NO**.

The previous audit used native Windows as the migration target and therefore
treated Bash, POSIX process control, Linux classpaths, and Linux llama.cpp
binaries as blockers. Under the corrected support matrix those are valid
shared-runtime behavior: native Ubuntu and WSL2 Ubuntu both provide the same
Linux userspace contract.

The actual portability risks are machine-specific rather than Linux-specific:

- configs/runtime.yaml contains deployment-specific /home/mhlab paths;
- docs/operations/inspecting_runs.md contains a deployment-specific run path;
- executable discovery assumes Python, Java, javac, Git, and llama-server are
  installed in the Linux environment PATH;
- active experiments need a Linux filesystem location, especially under WSL2;
- CUDA and llama.cpp availability depend on the host's Linux or WSL2 setup.

These should be documented or made configuration-driven. They do not justify a
PowerShell launcher, Windows Java, Windows classpath syntax, WSL detection in
the runtime, or a second EAGLE implementation.

## 2. Supported Environment Matrix

| Capability | Native Linux | WSL2 Ubuntu |
| --- | --- | --- |
| Bash launchers | Yes | Yes |
| Python / Conda | Yes | Yes |
| Linux llama.cpp | Yes | Yes |
| NVIDIA CUDA | Yes | Yes |
| Java / MicroRTS | Yes | Yes |
| POSIX process management | Yes | Yes |
| Native Windows executable support | Not required | Not required |

Windows applications may be used as a frontend, but runtime commands execute
inside Ubuntu in both supported environments.

## 3. Shared Runtime Architecture

~~~text
Linux userspace
    |
    +-- EAGLE Python / Conda
    +-- llama-server
    +-- Java / javac
    +-- MicroRTS
    +-- Git
~~~

The architecture is identical on bare-metal Ubuntu and WSL2 Ubuntu:

~~~text
run_env.sh
    -> python -m eagle runtime
    -> RuntimeManager
    -> configured Linux llama-server
    -> HTTP health checks

run.sh
    -> python -m eagle run
    -> generation and validation
    -> javac compilation
    -> Java integration probe
    -> ten bounded MicroRTS matches
    -> metrics, objectives, reflection, and artifacts

analyze.sh
    -> python -m eagle analyze
    -> canonical artifact loader and static report
~~~

The Java path intentionally uses cwd=microrts_dir, absolute class/artifact
paths, and a map path interpreted from that cwd. This is a runtime cwd
contract, not an operating-system dependency.

## 4. Previous Native-Windows Findings Reclassified

| Previous finding | Native Linux | WSL2 | Action |
| --- | --- | --- | --- |
| Hardcoded GGUF path in configs/runtime.yaml | C: machine-specific | C: machine-specific | Keep as a deployment configuration issue; replace locally with a path valid in each Linux filesystem |
| Hardcoded llama-server path in configs/runtime.yaml | C: machine-specific | C: machine-specific | Keep as a deployment configuration issue; use the Linux binary path for the selected host |
| /proc command-line identity check | A: valid Linux behavior | A: valid WSL2 Linux behavior | No Windows compatibility change |
| POSIX signals and process groups | A: valid Linux behavior | A: valid WSL2 Linux behavior | Preserve Linux process ownership and safe shutdown |
| Bash run.sh | A: supported launcher | A: supported launcher | Keep as canonical |
| Bash run_env.sh | A: supported launcher | A: supported launcher | Keep as canonical |
| Bash analyze.sh and POSIX absolute-path test | A: supported Linux path semantics | A: supported WSL2 path semantics | Keep; pass Linux paths from the Linux shell |
| Unix executable-bit validation | A: valid Linux behavior | A: valid WSL2 Linux behavior | Do not replace with Windows extension logic |
| Fixed command names java, javac, Git, llama-server | C: host toolchain setup | C: host toolchain setup | Keep PATH/configuration guidance; avoid hardcoded installation paths |
| HTTP LLM transport | A: portable within Linux | A: portable within WSL2 | No change |
| Colon-separated Java classpaths | A: correct Linux behavior | A: correct WSL2 behavior | Keep Linux classpath syntax |
| /tmp Matplotlib cache | A: normal Linux behavior | A: normal WSL2 behavior | No Windows change required |
| Python analysis core | A: portable | A: portable | No change |
| GPU device probing and llama.cpp CLI | A: standard Linux CUDA behavior | B: WSL2 GPU visibility must be configured | Document host setup; EAGLE uses the same Linux checks |
| Vendored MicroRTS Java runtime | A: Linux JDK path | A: WSL2 Linux JDK path | No MicroRTS portability branch |
| Obsolete vendor LLM shell helper | A: inactive Linux vendor residue | A: inactive Linux vendor residue | Do not port or make it part of EAGLE |
| Test fixture using chmod and a shell stub | A: valid Linux test model | A: valid WSL2 test model | Keep Linux tests; do not design tests for native Windows |

Categories used above:

- A: valid shared Linux behavior requiring no change.
- B: WSL2 deployment consideration requiring documentation, not runtime
  branching.
- C: machine-specific setup or path portability affecting Linux hosts.
- D: native-Windows-only behavior. No active EAGLE finding needs category D
  treatment because native Windows is outside the support target.

## 5. Machine Portability

The following are real portability concerns on both native Linux and WSL2:

1. configs/runtime.yaml currently contains /home/mhlab/EAGLE model and
   llama.cpp paths. These are valid Linux paths but only on one deployment.
2. The run-analysis documentation contains /home/mhlab/EAGLE as an example.
3. Executable discovery depends on the selected Linux environment PATH.
4. The runtime cwd and relative map path must remain aligned.
5. Model, llama.cpp build, JDK, Conda, and MicroRTS locations are deployment
   inputs and must not be assumed to exist on every host.

The recommended deployment practice is to keep machine-local values in
configs/runtime.yaml or a local uncommitted configuration. Do not encode a
username, fixed home directory, LAN address, or host-specific CUDA path into
EA or artifact logic.

## 6. Filesystem

Native Linux may use any normal Linux filesystem location, including ~/EAGLE.

For WSL2, place the repository and active runs inside the WSL2 Linux filesystem,
for example:

~~~bash
mkdir -p ~/EAGLE
~~~

Do not use /mnt/c/... or /mnt/d/... as the canonical experiment location.
EAGLE performs substantial I/O for generations, candidates, Java source and
classes, match logs, per-tick logs, replay data, reflection artifacts, and
analysis output. WSL2 mounted Windows filesystems can materially reduce this
I/O performance and introduce permission or line-ending friction.

Windows applications can still access results through WSL integration, Windows
Terminal, an editor's WSL integration, or the WSL network share. This is a
frontend/access concern; EAGLE continues to read and write through Linux paths.

The active artifact writers use pathlib.Path, ordinary UTF-8 files, and normal
Linux permissions. They do not require symlinks or case-sensitive tricks. Stable
metadata may use POSIX separators deliberately; that is part of artifact
stability and should not be changed.

## 7. GPU / CUDA

Native Ubuntu uses the normal NVIDIA Linux driver, CUDA installation, and
CUDA-enabled Linux llama.cpp build.

WSL2 uses the Windows NVIDIA driver with WSL GPU support. The llama.cpp process
still runs as a Linux binary inside WSL2 and must be visible from the Ubuntu
environment.

EAGLE does not install or manage GPU drivers. In both environments, verify the
Linux-visible toolchain from the Ubuntu shell:

~~~bash
nvidia-smi
llama-server --list-devices
~~~

The active EAGLE runtime uses the configured llama.cpp CLI and checks its device
output. There are no active hardcoded /dev/nvidia paths, LD_LIBRARY_PATH
assignments, or CUDA_VISIBLE_DEVICES assumptions that require a WSL-specific
code path. CUDA loader and driver configuration remain host setup.

## 8. llama.cpp

Both supported environments use a Linux llama-server binary:

~~~text
Native Ubuntu: Ubuntu -> llama-server
WSL2:         WSL2 Ubuntu -> llama-server
~~~

EAGLE communicates with the server over the configured HTTP endpoint. It should
not invoke llama-server.exe, Windows processes from WSL, or a separate Windows
server for the normal architecture.

The model path, server executable, host, port, and server arguments are runtime
configuration. The checked-in values still represent one deployment and should
be replaced with local Linux paths when moving to another Ubuntu host or WSL2
distribution.

For same-environment operation, keep EAGLE and llama.cpp in the same Ubuntu
environment and use 127.0.0.1. Verify /health and /v1/models before real EA
execution.

## 9. Java / MicroRTS

Both environments use Linux Java:

~~~text
Native Ubuntu: Python -> Linux java/javac -> MicroRTS
WSL2:          Python -> WSL Linux java/javac -> MicroRTS
~~~

The active Java compilation, integration, match, and Final Test paths use direct
argument lists, explicit cwd values, and Linux classpath separator :. Do not
add Windows classpath ; or invoke Windows java.exe.

Java paths are machine setup concerns. java and javac may come from PATH or a
local Linux configuration, but no source path should assume a specific JDK
installation such as /usr/lib/jvm/some-version.

## 10. Networking

### Case 1: same Linux environment

This is canonical:

~~~text
EAGLE -> 127.0.0.1 -> llama.cpp
~~~

It works identically on native Ubuntu and WSL2 Ubuntu. Health checks and LLM
requests use Python HTTP; EAGLE does not depend on Linux network commands.

### Case 2: intentional LAN service

If a service is intentionally hosted on another physical machine, use a
configuration-driven host or bind address. A service intended for LAN access
may bind 0.0.0.0 instead of 127.0.0.1, subject to firewall and routing policy.
Do not hardcode an interface address or add interface-discovery commands.

### Case 3: Windows host and WSL2

Windows-to-WSL networking details are WSL2 host configuration. They are not part
of normal same-environment EAGLE operation. Do not add PowerShell, netsh, or
Windows-specific port discovery to the runtime unless a later requirement
explicitly needs Windows-host access.

## 11. Runtime / Process Management

The Linux process model is supported in both environments. RuntimeManager owns
one local llama-server PID, persists the PID path, reads Linux process identity,
redirects logs, polls HTTP health, and uses POSIX process-group and signal
semantics where required.

This is acceptable on native Ubuntu and WSL2 Ubuntu. The important architecture
boundary is that shell launchers remain thin and Python owns server state,
health, PID safety, and errors. No Windows process-management API or WSL
detection is needed.

Java, MicroRTS, and Git subprocesses are direct argument-list invocations. Their
portability requirements are Linux PATH, cwd, Java classpath, and artifact path
correctness, not Windows process semantics.

## 12. Git / Development Workflow

Native Linux users should run Git normally inside Linux.

WSL2 users should prefer WSL Git with a WSL filesystem working tree. Avoid
alternating Windows Git and WSL Git on one checkout because executable-bit,
line-ending, and permission changes can create noisy diffs or broken launchers.

Do not change repository-wide line-ending settings without an actual current
problem. Use Windows Terminal, an editor with WSL integration, or another
frontend while keeping commands and the working tree inside Ubuntu.

## 13. Native Linux Setup

Typical deployment:

~~~text
Ubuntu
  -> NVIDIA Linux driver / CUDA
  -> Conda environment
  -> JDK 17+
  -> CUDA-enabled Linux llama.cpp
  -> EAGLE
~~~

Typical commands:

~~~bash
cd ~/EAGLE
conda activate eagle
./run_env.sh start
./run.sh
./analyze.sh
~~~

The checked-in runtime config must contain paths valid on the selected machine.

## 14. WSL2 Setup

Typical deployment:

~~~text
Windows 11
  -> WSL2 Ubuntu
  -> WSL GPU visibility from the Windows NVIDIA driver
  -> Conda environment
  -> JDK 17+
  -> CUDA-enabled Linux llama.cpp
  -> EAGLE in the WSL Linux filesystem
~~~

Runtime commands are intentionally identical:

~~~bash
cd ~/EAGLE
conda activate eagle
./run_env.sh start
./run.sh
./analyze.sh
~~~

Do not add a WSL-specific environment file or separate launcher. Only host
setup, filesystem placement, GPU visibility, and Windows/WSL frontend access
differ.

## 15. Shared Smoke-Test Plan

Run the same sequence from a native Ubuntu shell and from a WSL2 Ubuntu shell:

~~~bash
python --version
java -version
javac -version
git --version
nvidia-smi
~~~

Then verify:

1. runtime config loads;
2. llama.cpp starts;
3. the CUDA backend is active;
4. one LLM HTTP request succeeds;
5. strategy/code generation succeeds;
6. one generated Java candidate compiles;
7. one MicroRTS match completes;
8. match and per-tick artifacts are written;
9. reflection inputs can be read;
10. one minimal EA generation completes;
11. analyze.sh analyzes the resulting run.

Do not run or modify EA experiments as part of this documentation-only audit.
The smoke sequence is the acceptance plan for a separately approved runtime
validation task.

## 16. Remaining Risks

- The checked-in runtime model and server paths are deployment-specific.
- WSL2 GPU support depends on the Windows driver, WSL version, and Ubuntu
  userspace/toolchain.
- WSL2 mounted Windows filesystem I/O can make experiments substantially slower.
- A Linux JDK, Git, Conda environment, llama.cpp binary, and model must be
  installed inside the selected Ubuntu environment.
- LAN or Windows-host access requires deliberate host binding and firewall
  configuration.
- Historical run artifacts are not proof of current runtime compliance.
- No native Windows execution path is maintained or tested.

## Non-goals

This audit does not:

- remove native Linux support;
- make WSL2 the only target;
- implement native Windows support;
- add PowerShell or batch launchers;
- use llama-server.exe;
- use Windows Java or Windows classpath syntax;
- replace Linux signals for Windows compatibility;
- add Windows process APIs or WSL detection;
- create separate WSL2 code paths;
- introduce Docker;
- change EA behavior, fitness, reflection, mutation, crossover, evaluation,
  opponents, or artifact schemas.
