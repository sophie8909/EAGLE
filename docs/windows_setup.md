# EAGLE Native Windows Setup

This is the minimum setup for the active EAGLE MicroRTS pipeline. It does not add a
GUI, a second optimizer, or an alternate evaluation protocol.

## Prerequisites

Install and expose these tools in the active PowerShell environment:

- Git
- Python 3.10-3.12, preferably through Conda
- Java and javac from a JDK 17 or newer
- NVIDIA driver/toolkit appropriate for the selected llama.cpp build
- A Windows llama-server.exe build with CUDA support when GPU execution is enabled

Create or activate the project environment, then install the repository dependencies.
The launcher does not run conda activate internally; it uses the Python found in
the active PowerShell environment.

~~~
conda env create -f environment.yml
conda activate eagle
~~~

If the environment already exists, update it with the repository dependency files as
appropriate for the local Conda/pip workflow.

## Runtime configuration

Edit configs/runtime.yaml for the machine-local model and server:

~~~
llm:
  model_path: C:/models/qwen3.5-9b.gguf
  server_binary: C:/tools/llama.cpp/llama-server.exe
  host: 127.0.0.1
  port: 8080
  arguments: []
~~~

server_binary may instead be llama-server when the executable is on PATH.
Java, javac, and Python normally resolve from the active environment and PATH;
explicit overrides can be added under tools:

~~~
tools:
  python: null
  java: null
  javac: null
~~~

Use forward slashes or normal Windows paths in YAML. The repository does not include
the GGUF model or the llama.cpp executable.

## Start and run

From the repository root:

~~~
.\run_env.ps1 start
.\run.ps1
~~~

The runtime command also supports stop, restart, status, and check:

~~~
.\run_env.ps1 status
.\run_env.ps1 check
~~~

Arguments after run.ps1 are forwarded to python -m eagle run, for example:

~~~
.\run.ps1 --mock
.\run.ps1 --resume runs\20260809_120000_000000
~~~

## Analyze

Analyze the newest run:

~~~
.\analyze.ps1
~~~

Analyze a selected run using an absolute or caller-relative Windows path:

~~~
.\analyze.ps1 D:\Project\EAGLE\runs\20260809_120000_000000
.\analyze.ps1 runs\20260809_120000_000000
~~~

If PowerShell execution policy blocks local scripts, use the normal per-user policy
approved by your organization or invoke the underlying Python module directly:

~~~
python -m eagle analyze --latest --runtime-config configs/runtime.yaml
~~~
