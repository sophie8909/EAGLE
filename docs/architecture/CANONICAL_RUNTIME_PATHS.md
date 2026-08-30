# Canonical runtime paths

| Responsibility | Canonical owner |
| --- | --- |
| Experiment/model configuration | `configs/experiments/<group>/*.yaml`, excluding a generated run index |
| Directory-batch run index | `configs/experiments/<group>/experiment.yaml` when that name is not an existing config |
| Production shell command | `experiment.sh` |
| Experiment CLI/lifecycle | `eagle.cli.experiment`, `eagle.experiment` |
| Runtime adaptation and validation | `eagle.runtime.config` |
| Health check | `eagle.runtime.endpoints` |
| Owned process/PID/log lifecycle | `eagle.runtime.processes` |
| EA search/resume | `eagle.search`, `eagle.resume` |
| Offline analysis | `analyze.sh`, `eagle.cli.analyze` |
| Optional network watchdog | `watchdog.sh` |

Runtime PID/log names include the resolved model name and port. They are transient process state, not configuration.
