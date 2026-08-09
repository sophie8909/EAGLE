# Canonical runtime paths

| Responsibility | Canonical owner |
| --- | --- |
| Runtime configuration | `configs/runtime.yaml` |
| Runtime shell command | `run_env.sh` |
| Optional runtime watchdog | `watchdog.sh` |
| Runtime CLI | `eagle.cli.runtime` |
| Health check | `eagle.runtime.endpoints` |
| Process/PID/log ownership | `eagle.runtime.processes` |
| Experiment shell command | `run.sh` |
| Experiment CLI and EA | `eagle.cli.run`, `eagle.search`, `eagle.evaluation` |
| Offline analysis shell command | `analyze.sh` |

Runtime files are only `runtime/logs/llm-server.log` and
`runtime/pids/llm-server.pid`; the independent watchdog additionally uses
`runtime/pids/llm-watchdog.pid` while it is running.
