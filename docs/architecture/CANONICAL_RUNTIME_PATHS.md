# Canonical runtime paths

| Responsibility | Canonical owner |
| --- | --- |
| Runtime configuration | `configs/runtime.yaml` |
| Runtime shell command | `run_env.sh` |
| Runtime CLI | `eagle.cli.runtime` |
| Endpoint resolution | `eagle.runtime.endpoints` |
| Process/PID/log ownership | `eagle.runtime.processes` |
| Local-server supervision | `eagle.runtime.watchdog` |
| Experiment shell command | `run.sh` |
| Experiment CLI and EA | `eagle.cli.run`, `eagle.search`, `eagle.evaluation` |
| Offline analysis shell command | `analyze.sh` |
| Analysis loader/report | `eagle.analysis.loader`, `eagle.analysis.report` |

Runtime logs and PIDs live under the roots configured in
`configs/runtime.yaml`. Run-specific artifacts remain under the configured
run root and never contain model-server logs.
