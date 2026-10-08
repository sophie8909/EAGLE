# Monitoring a local EAGLE experiment

EAGLE includes a read-only local status agent for the experiment host. It reads
the canonical `eagle-run-v2` `manifest.json` and the latest atomic
`generation_*.json`; it does not parse terminal output and it cannot start,
stop, or modify an experiment.

## Start the agent

For a local-only check, bind to loopback:

```bash
python -m eagle monitor \
  --run-dir runs/<run_id> \
  --host 127.0.0.1 \
  --port 8765
```

For a monitor on another computer in the private network, bind explicitly and
use a long random token:

```bash
python -m eagle monitor \
  --run-dir runs/<run_id> \
  --host 0.0.0.0 \
  --port 8765 \
  --token '<shared-secret>' \
  --pid <experiment-pid>
```

The agent refuses a non-loopback bind without `--token`. Restrict the port in
the host firewall to the monitor computer or VPN address. The API is read-only;
`POST` requests are rejected.

Use `--once` to validate the run and inspect one snapshot without opening a
server:

```bash
python -m eagle monitor --run-dir runs/<run_id> --once
```

## Endpoints

- `GET /health` is an unauthenticated liveness check.
- `GET /status` returns `eagle-monitor-status-v1`; when a token is configured,
  send `Authorization: Bearer <shared-secret>`.

The status includes host CPU load, memory, disk, NVIDIA GPU telemetry when
`nvidia-smi` is available, the run status and latest generation, match progress,
fitness summaries, opponent summaries, AOS state, bounded error-memory records,
and an optional experiment PID. A running or initialized run is marked `stale`
when its manifest update is older than `--stale-after` seconds (180 by default).

The monitor only reports the latest atomically recorded generation. A partially
written candidate or console line is not treated as completed evidence.
