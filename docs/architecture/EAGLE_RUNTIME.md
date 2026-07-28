# EAGLE runtime architecture

`configs/runtime.yaml` (`runtime-v1`) owns Conda, filesystem roots, local and
remote server endpoints, model paths, ports, llama.cpp arguments, role
assignments, health checks, logs, PIDs, and watchdog policy.

`eagle.runtime.config` validates the typed schema. `eagle.runtime.endpoints`
constructs client URLs and writes `runtime/resolved_endpoints.json`.
`eagle.runtime.processes` starts and stops only validated managed local
processes. Remote endpoints are health-checked but never launched or restarted.
`eagle.runtime.watchdog` is one process monitoring all enabled local servers.

The EA reads the resolved role mapping but never owns model processes.
Analysis reads run artifacts but never owns runtime or EA processes.
